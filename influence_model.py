# influence_model.py
"""
BGS influence estimation engine.
Formulas derived from community testing (SINC guide, Jane Turner, Taipandot).

Bounty credits:
  Journal Manual does **not** split Powerplay payout perks on RedeemVoucher.
  Face-value (base) vouchers are recorded on kill-time ``Bounty`` events;
  cash paid (often including Powerplay bonuses such as ALD rank payouts) is on
  ``RedeemVoucher``. BGS estimates use **base** credits only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def _log2(x: float) -> float:
    return math.log2(max(x, 1.0))


def mission_points(inf_str: str) -> float:
    """Map journal Influence string ('+', '++', ...) to points."""
    n = len(inf_str.strip().replace(" ", ""))
    n = max(1, min(n, 5))
    return 0.5 * _log2(n)


def bounty_points(credits: float) -> float:
    """Points from **base** (face-value) bounty voucher credits."""
    return 1.33 * _log2(credits)


def population_factor(population: int) -> float:
    """Effort → influence multiplier. Larger pop → smaller swing."""
    pop = max(int(population), 1000)
    return max(0.025, 1.0 - math.log10(pop) / 10.875)


def resolve_redeem_base_and_bonus(pending_base: float, cash: float) -> tuple[float, float, float]:
    """
    Split RedeemVoucher cash into base face value and implied payout bonus.

    Returns ``(base, bonus, remaining_pending)``.

    Heuristic (pending face value tracked from ``Bounty`` events):
    - ``pending <= 0``: no kill tracking → treat full cash as base, bonus 0
      (cannot detect Powerplay perk without pending stack).
    - ``cash > pending``: assume full cash-in of known stack with extra payout
      (e.g. Powerplay rank bonus) → base=pending, bonus=cash-pending, pending=0.
    - ``cash <= pending``: partial/full redeem without detectable surplus →
      base=cash, bonus=0, pending reduced by cash.
    """
    if cash <= 0:
        return 0.0, 0.0, max(pending_base, 0.0)
    pending = max(pending_base, 0.0)
    if pending <= 0:
        return cash, 0.0, 0.0
    if cash > pending:
        return pending, cash - pending, 0.0
    return cash, 0.0, pending - cash


@dataclass
class Action:
    timestamp: str
    kind: str  # "mission" | "bounty" | "exploration"
    faction: str
    system: str
    raw_value: float  # mission: INF count; bounty/exploration: **base** credits
    points: float
    est_delta: float  # estimated % contribution of this action
    cash_value: float = 0.0  # cash received (may include Powerplay / first-disc bonus)
    bonus_value: float = 0.0  # cash_value - base (raw_value), if known


@dataclass
class TrackerState:
    system: str = ""
    faction: str = ""
    population: int = 0
    current_influence: float = 0.0  # 0–1
    actions: list[Action] = field(default_factory=list)
    bucket_counts: dict[str, int] = field(
        default_factory=lambda: {"mission": 0, "bounty": 0, "exploration": 0}
    )
    total_points: float = 0.0
    total_est_delta: float = 0.0
    # Face-value vouchers earned (Bounty events) not yet attributed to a redeem.
    pending_bounty_base: float = 0.0
    # Session aggregates (bounty)
    total_bounty_base: float = 0.0
    total_bounty_cash: float = 0.0
    total_bounty_bonus: float = 0.0
    # Session aggregates (cartographics — journal BaseValue / TotalEarnings)
    total_exploration_base: float = 0.0
    total_exploration_bonus: float = 0.0
    total_exploration_earnings: float = 0.0
    # Last system where vouchers/data were handed in (for Discord report)
    last_turnin_system: str = ""

    def note_bounty_award(self, system: str, faction: str, base_credits: float) -> float:
        """
        Record kill-time voucher face value for the tracked system/faction.

        Returns the amount added to ``pending_bounty_base`` (0 if ignored).
        """
        if system != self.system or faction != self.faction or base_credits <= 0:
            return 0.0
        self.pending_bounty_base += base_credits
        return base_credits

    def add_mission(self, ts: str, system: str, faction: str, inf_str: str) -> Action | None:
        if system != self.system or faction != self.faction:
            return None
        pts = mission_points(inf_str)
        # mild diminishing returns
        self.bucket_counts["mission"] += 1
        decay = 1.0 / (1.0 + 0.15 * math.log1p(self.bucket_counts["mission"]))
        pts *= decay
        delta = pts * population_factor(self.population) * 0.35  # empirical scale → %
        act = Action(ts, "mission", faction, system, float(len(inf_str)), pts, delta)
        self.actions.append(act)
        self.total_points += pts
        self.total_est_delta += delta
        return act

    def add_bounty(
        self,
        ts: str,
        system: str,
        faction: str,
        base_credits: float,
        cash_credits: float | None = None,
    ) -> Action | None:
        """
        Record a bounty hand-in. Influence uses ``base_credits`` only.

        ``cash_credits`` defaults to ``base_credits`` when the cash figure is
        unknown or identical (no Powerplay surplus detected).
        """
        if system != self.system or faction != self.faction:
            return None
        if base_credits <= 0:
            return None
        cash = float(base_credits if cash_credits is None else cash_credits)
        bonus = max(0.0, cash - base_credits)
        pts = bounty_points(base_credits)
        self.bucket_counts["bounty"] += 1
        decay = 1.0 / (1.0 + 0.12 * math.log1p(self.bucket_counts["bounty"]))
        pts *= decay
        delta = pts * population_factor(self.population) * 0.28
        act = Action(
            ts,
            "bounty",
            faction,
            system,
            base_credits,
            pts,
            delta,
            cash_value=cash,
            bonus_value=bonus,
        )
        self.actions.append(act)
        self.total_points += pts
        self.total_est_delta += delta
        self.total_bounty_base += base_credits
        self.total_bounty_cash += cash
        self.total_bounty_bonus += bonus
        return act

    def redeem_bounty_cash(
        self,
        ts: str,
        system: str,
        faction: str,
        cash_credits: float,
        *,
        turnin_system: str = "",
    ) -> Action | None:
        """
        Hand-in path: split cash vs pending base, then ``add_bounty``.

        Updates ``pending_bounty_base`` via :func:`resolve_redeem_base_and_bonus`.
        """
        if system != self.system or faction != self.faction:
            return None
        base, bonus, remaining = resolve_redeem_base_and_bonus(
            self.pending_bounty_base, cash_credits
        )
        self.pending_bounty_base = remaining
        if base <= 0 and cash_credits <= 0:
            return None
        # Prefer base for BGS; still record cash/bonus when base resolved to 0 but cash > 0
        use_base = base if base > 0 else cash_credits
        act = self.add_bounty(ts, system, faction, use_base, cash_credits=cash_credits)
        if act and turnin_system:
            self.last_turnin_system = turnin_system
        return act

    def add_exploration(
        self,
        ts: str,
        turnin_system: str,
        base_value: float,
        bonus: float = 0.0,
        total_earnings: float | None = None,
    ) -> Action | None:
        """
        Record cartographics sale (``SellExplorationData`` / ``MultiSellExplorationData``).

        Journal provides BaseValue, Bonus, and TotalEarnings (Total may include
        Powerplay rank payout multipliers). Session report prefers BaseValue.
        Exploration is not yet folded into est. influence Δ (BGS formula TBD).
        """
        if base_value <= 0 and (total_earnings or 0) <= 0:
            return None
        cash = float(
            total_earnings if total_earnings is not None else (base_value + max(bonus, 0.0))
        )
        base = float(base_value) if base_value > 0 else cash
        bon = max(0.0, float(bonus) if bonus else cash - base)
        self.bucket_counts["exploration"] = self.bucket_counts.get("exploration", 0) + 1
        act = Action(
            ts,
            "exploration",
            self.faction or "",
            turnin_system or self.system,
            base,
            points=0.0,
            est_delta=0.0,
            cash_value=cash,
            bonus_value=bon,
        )
        self.actions.append(act)
        self.total_exploration_base += base
        self.total_exploration_bonus += bon
        self.total_exploration_earnings += cash
        if turnin_system:
            self.last_turnin_system = turnin_system
        return act

    def reset_session(self) -> None:
        self.actions.clear()
        self.bucket_counts = {"mission": 0, "bounty": 0, "exploration": 0}
        self.total_points = 0.0
        self.total_est_delta = 0.0
        self.pending_bounty_base = 0.0
        self.total_bounty_base = 0.0
        self.total_bounty_cash = 0.0
        self.total_bounty_bonus = 0.0
        self.total_exploration_base = 0.0
        self.total_exploration_bonus = 0.0
        self.total_exploration_earnings = 0.0
        self.last_turnin_system = ""
