# influence_model.py
"""
BGS influence estimation engine.
Formulas derived from community testing (SINC guide, Jane Turner, Taipandot).

Estimates are *your contribution share* only — see competition_factor() for a
heuristic dilution for concurrent CMDR / contested-system effort.

Bounty credits use **base** (face-value) vouchers, not Powerplay cash perks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def _log2(x: float) -> float:
    return math.log2(max(x, 1.0))


def mission_inf_level(inf_str: str) -> int:
    """Map journal Influence string ('+', '++', …) to level 1–5."""
    n = len(inf_str.strip().replace(" ", ""))
    return max(1, min(n, 5))


def mission_points(inf_str: str) -> float:
    """Map journal Influence string ('+', '++', ...) to points."""
    return 0.5 * _log2(mission_inf_level(inf_str))


def bounty_points(credits: float) -> float:
    """Points from **base** (face-value) bounty voucher credits."""
    return 1.33 * _log2(credits)


def bond_points(credits: float) -> float:
    """Points from combat bond face-value credits (slightly below bounties)."""
    return 1.15 * _log2(credits)


def trade_points(profit: float) -> float:
    """Points from market trade **profit** (TotalSale − cost basis)."""
    return 1.1 * _log2(max(profit, 0.0))


def population_factor(population: int) -> float:
    """Effort → influence multiplier. Larger pop → smaller swing."""
    pop = max(int(population), 1000)
    return max(0.025, 1.0 - math.log10(pop) / 10.875)


def competition_factor(
    num_factions: int,
    population: int,
    opposing_players: int = 0,
    ally_players: int = 0,
) -> float:
    """
    Heuristic player-side / contest multiplier for Est. Δ.

    We cannot observe other players' actions. Proxies:
    - More minor factions → more contested space
    - Higher population → typically more traffic
    - ``opposing_players`` (O): active CMDRs working against your faction
    - ``ally_players`` (A): active same-faction CMDRs (not counting you)

    Player-side multiplier (assuming similar effort per CMDR):

        (1 + A) / (1 + O)

    You are the leading ``1``. Each ally is treated as adding another full
    unit of same-side effort (so Est. Δ becomes a *faction-side* estimate if
    allies match your pace). Each opponent dilutes that share. Combined with
    system contest, clamped to [0.15, 4.0].
    """
    fac_n = max(int(num_factions), 1)
    fac_part = 1.0 / (1.0 + 0.14 * max(fac_n - 1, 0))
    pop = max(int(population), 1000)
    pop_part = 1.0 / (1.0 + 0.10 * max(0.0, math.log10(pop) - 4.0))
    system_part = fac_part * pop_part
    allies = max(int(ally_players), 0)
    opponents = max(int(opposing_players), 0)
    # You (1) + allies, diluted by opponents (not by allies in the denominator)
    player_share = (1.0 + allies) / (1.0 + opponents)
    return max(0.15, min(4.0, system_part * player_share))


# Empirical scales → estimated % points (after pop × competition).
# Bounty scale kept deliberately below mission scale (user feedback: BVs over-valued).
SCALE_MISSION = 0.35
SCALE_BOUNTY = 0.12
SCALE_BOND = 0.14
SCALE_TRADE = 0.16


def scale_for_kind(kind: str) -> float:
    """Empirical scale for action kind (0 for non-scored kinds)."""
    return {
        "mission": SCALE_MISSION,
        "bounty": SCALE_BOUNTY,
        "bond": SCALE_BOND,
        "trade": SCALE_TRADE,
    }.get(kind, 0.0)


def resolve_redeem_base_and_bonus(pending_base: float, cash: float) -> tuple[float, float, float]:
    """
    Split RedeemVoucher cash into base face value and implied payout bonus.

    Returns ``(base, bonus, remaining_pending)``.
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
    kind: str  # "mission" | "bounty" | "bond" | "trade" | "exploration"
    faction: str
    system: str
    raw_value: float  # mission: INF level; credits/profit for others
    points: float
    est_delta: float  # estimated % contribution of this action
    cash_value: float = 0.0
    bonus_value: float = 0.0


@dataclass
class TrackerState:
    system: str = ""
    faction: str = ""
    population: int = 0
    num_factions: int = 1  # minor factions in system (competition proxy)
    # User estimates of other active CMDRs (settings).
    opposing_players: int = 0
    ally_players: int = 0  # same-faction allies (not including you)
    current_influence: float = 0.0  # 0–1
    actions: list[Action] = field(default_factory=list)
    bucket_counts: dict[str, int] = field(
        default_factory=lambda: {
            "mission": 0,
            "bounty": 0,
            "bond": 0,
            "trade": 0,
            "exploration": 0,
        }
    )
    # Mission INF by level 1–5 (count of missions at that + tier)
    mission_inf_counts: dict[int, int] = field(
        default_factory=lambda: {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    )
    total_points: float = 0.0
    total_est_delta: float = 0.0
    # Face-value vouchers earned (Bounty events) not yet attributed to a redeem.
    pending_bounty_base: float = 0.0
    # Session aggregates
    total_bounty_base: float = 0.0
    total_bounty_cash: float = 0.0
    total_bounty_bonus: float = 0.0
    total_bond_credits: float = 0.0
    total_trade_profit: float = 0.0
    total_exploration_base: float = 0.0
    total_exploration_bonus: float = 0.0
    total_exploration_earnings: float = 0.0
    last_turnin_system: str = ""

    def competition(self) -> float:
        return competition_factor(
            self.num_factions,
            self.population,
            self.opposing_players,
            self.ally_players,
        )

    def recompute_est_deltas(self) -> None:
        """
        Rebuild each action's est_delta and total_est_delta from stored points
        using current population / competition (opponents + allies).
        """
        pop_f = population_factor(self.population)
        comp = self.competition()
        total = 0.0
        for act in self.actions:
            scale = scale_for_kind(act.kind)
            if scale <= 0 or act.points <= 0:
                act.est_delta = 0.0
                continue
            act.est_delta = act.points * pop_f * comp * scale
            total += act.est_delta
        self.total_est_delta = total

    def set_opposing_players(self, count: int) -> None:
        """Update opposing-player estimate and refresh Est. Δ."""
        self.opposing_players = max(0, int(count))
        self.recompute_est_deltas()

    def set_ally_players(self, count: int) -> None:
        """Update same-faction ally estimate and refresh Est. Δ."""
        self.ally_players = max(0, int(count))
        self.recompute_est_deltas()

    def set_player_estimates(
        self, *, allies: int | None = None, opponents: int | None = None
    ) -> None:
        """Update ally and/or opponent estimates once, then recompute Est. Δ."""
        if allies is not None:
            self.ally_players = max(0, int(allies))
        if opponents is not None:
            self.opposing_players = max(0, int(opponents))
        self.recompute_est_deltas()

    def mission_inf_total_units(self) -> int:
        """Σ (level × count) — BGS-Tally style total INF points from missions."""
        return sum(level * count for level, count in self.mission_inf_counts.items())

    def note_bounty_award(self, system: str, faction: str, base_credits: float) -> float:
        """Record kill-time voucher face value. Returns amount noted (0 if ignored)."""
        if system != self.system or faction != self.faction or base_credits <= 0:
            return 0.0
        self.pending_bounty_base += base_credits
        return base_credits

    def add_mission(self, ts: str, system: str, faction: str, inf_str: str) -> Action | None:
        if system != self.system or faction != self.faction:
            return None
        level = mission_inf_level(inf_str)
        pts = mission_points(inf_str)
        self.bucket_counts["mission"] += 1
        self.mission_inf_counts[level] = self.mission_inf_counts.get(level, 0) + 1
        decay = 1.0 / (1.0 + 0.15 * math.log1p(self.bucket_counts["mission"]))
        pts *= decay
        delta = pts * population_factor(self.population) * self.competition() * SCALE_MISSION
        act = Action(ts, "mission", faction, system, float(level), pts, delta)
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
        """Record a bounty hand-in. Influence uses ``base_credits`` only."""
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
        delta = pts * population_factor(self.population) * self.competition() * SCALE_BOUNTY
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
        """Hand-in path: split cash vs pending base, then ``add_bounty``."""
        if system != self.system or faction != self.faction:
            return None
        base, _bonus, remaining = resolve_redeem_base_and_bonus(
            self.pending_bounty_base, cash_credits
        )
        self.pending_bounty_base = remaining
        if base <= 0 and cash_credits <= 0:
            return None
        use_base = base if base > 0 else cash_credits
        act = self.add_bounty(ts, system, faction, use_base, cash_credits=cash_credits)
        if act and turnin_system:
            self.last_turnin_system = turnin_system
        return act

    def add_combat_bond(
        self,
        ts: str,
        system: str,
        faction: str,
        credits: float,
        *,
        turnin_system: str = "",
    ) -> Action | None:
        """Record combat bond redemption for the tracked faction."""
        if system != self.system or faction != self.faction:
            return None
        if credits <= 0:
            return None
        pts = bond_points(credits)
        self.bucket_counts["bond"] += 1
        decay = 1.0 / (1.0 + 0.12 * math.log1p(self.bucket_counts["bond"]))
        pts *= decay
        delta = pts * population_factor(self.population) * self.competition() * SCALE_BOND
        act = Action(ts, "bond", faction, system, credits, pts, delta, cash_value=credits)
        self.actions.append(act)
        self.total_points += pts
        self.total_est_delta += delta
        self.total_bond_credits += credits
        if turnin_system:
            self.last_turnin_system = turnin_system
        return act

    def add_trade_profit(
        self,
        ts: str,
        system: str,
        faction: str,
        profit: float,
        *,
        turnin_system: str = "",
    ) -> Action | None:
        """Record market trade profit attributed to station minor faction."""
        if system != self.system or faction != self.faction:
            return None
        if profit <= 0:
            return None
        pts = trade_points(profit)
        self.bucket_counts["trade"] += 1
        decay = 1.0 / (1.0 + 0.10 * math.log1p(self.bucket_counts["trade"]))
        pts *= decay
        delta = pts * population_factor(self.population) * self.competition() * SCALE_TRADE
        act = Action(ts, "trade", faction, system, profit, pts, delta, cash_value=profit)
        self.actions.append(act)
        self.total_points += pts
        self.total_est_delta += delta
        self.total_trade_profit += profit
        if turnin_system:
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
        """Record cartographics sale (BaseValue / TotalEarnings). Not in Est. Δ yet."""
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
        self.bucket_counts = {
            "mission": 0,
            "bounty": 0,
            "bond": 0,
            "trade": 0,
            "exploration": 0,
        }
        self.mission_inf_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        self.total_points = 0.0
        self.total_est_delta = 0.0
        self.pending_bounty_base = 0.0
        self.total_bounty_base = 0.0
        self.total_bounty_cash = 0.0
        self.total_bounty_bonus = 0.0
        self.total_bond_credits = 0.0
        self.total_trade_profit = 0.0
        self.total_exploration_base = 0.0
        self.total_exploration_bonus = 0.0
        self.total_exploration_earnings = 0.0
        self.last_turnin_system = ""
