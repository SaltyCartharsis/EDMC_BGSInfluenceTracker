"""
Pure journal event handlers for BGS influence tracking.

Shapes follow Frontier Journal Manual v32/v34 and EDMC's journal_entry hook:
https://hosting.zaonce.net/community/journal/v32/Journal_Manual-v32.pdf
https://github.com/EDCD/EDMarketConnector/blob/main/PLUGINS.md

Tracked for estimation / reports:
  - Missions (INF tiers), bounty base, combat bonds, trade profit
  - Exploration sales (report only)

No EDMC, Tk, or network imports — safe to unit-test outside the host.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .influence_model import Action, TrackerState

# Events that carry system population / minor-faction lists (manual §§4.8, 4.12, 11.1).
SYSTEM_EVENTS = frozenset({"FSDJump", "Location", "CarrierJump"})


@dataclass
class SessionState:
    """Plugin session fields updated from journal events (not persisted prefs)."""

    current_system: str = ""
    available_factions: list[str] = field(default_factory=list)
    station_faction: str = ""  # from Docked — used to attribute MarketSell profit


@dataclass
class ProcessResult:
    """Side-effect summary after processing one journal entry."""

    notifications: list[str] = field(default_factory=list)
    ui_dirty: bool = False
    actions: list[Action] = field(default_factory=list)


def process_journal_entry(
    tracker: TrackerState,
    session: SessionState,
    entry: dict[str, Any],
    *,
    system: str | None = None,
) -> ProcessResult:
    """Apply one journal entry to tracker/session."""
    result = ProcessResult()
    event = entry.get("event")
    ts = str(entry.get("timestamp") or "")

    if event in SYSTEM_EVENTS:
        _handle_system_event(tracker, session, entry, system=system, result=result)

    if event == "Docked":
        _handle_docked(session, entry, system=system, result=result)

    if event == "Bounty":
        _handle_bounty_award(tracker, session, entry, system=system, ts=ts, result=result)

    if event == "MissionCompleted":
        _handle_mission_completed(tracker, entry, ts=ts, result=result)

    if event == "RedeemVoucher":
        _handle_redeem_voucher(tracker, session, entry, ts=ts, result=result)

    if event == "MarketSell":
        _handle_market_sell(tracker, session, entry, ts=ts, result=result)

    if event in ("SellExplorationData", "MultiSellExplorationData"):
        _handle_sell_exploration(tracker, session, entry, ts=ts, result=result)

    return result


def _handle_system_event(
    tracker: TrackerState,
    session: SessionState,
    entry: dict[str, Any],
    *,
    system: str | None,
    result: ProcessResult,
) -> None:
    session.current_system = str(entry.get("StarSystem") or system or "")
    if "Population" in entry:
        tracker.population = int(entry["Population"])

    factions = entry.get("Factions") or []
    session.available_factions = [
        str(f["Name"]) for f in factions if isinstance(f, dict) and "Name" in f
    ]
    tracker.num_factions = max(len(session.available_factions), 1)
    for f in factions:
        if not isinstance(f, dict):
            continue
        if f.get("Name") == tracker.faction:
            tracker.current_influence = float(f.get("Influence") or 0.0)

    if not tracker.system and session.current_system:
        tracker.system = session.current_system

    result.ui_dirty = True


def _handle_docked(
    session: SessionState,
    entry: dict[str, Any],
    *,
    system: str | None,
    result: ProcessResult,
) -> None:
    """Remember station controlling faction for trade attribution."""
    if entry.get("StarSystem"):
        session.current_system = str(entry["StarSystem"])
    elif system:
        session.current_system = system
    sf = entry.get("StationFaction")
    if isinstance(sf, dict):
        session.station_faction = str(sf.get("Name") or "")
    elif isinstance(sf, str):
        session.station_faction = sf
    result.ui_dirty = True


def extract_bounty_rewards(entry: dict[str, Any]) -> list[tuple[str, float]]:
    """Parse kill-time ``Bounty`` face values (manual §5.1)."""
    out: list[tuple[str, float]] = []
    rewards = entry.get("Rewards") or []
    if rewards:
        for row in rewards:
            if not isinstance(row, dict):
                continue
            fac = row.get("Faction")
            if not fac:
                continue
            out.append((str(fac), float(row.get("Reward") or 0)))
        return out

    fac = entry.get("Faction")
    if fac is not None and "Reward" in entry:
        out.append((str(fac), float(entry.get("Reward") or 0)))
    return out


def _handle_bounty_award(
    tracker: TrackerState,
    session: SessionState,
    entry: dict[str, Any],
    *,
    system: str | None,
    ts: str,
    result: ProcessResult,
) -> None:
    here = session.current_system or (system or "")
    noted = 0.0
    for fac, reward in extract_bounty_rewards(entry):
        noted += tracker.note_bounty_award(here, fac, reward)
    if noted > 0:
        result.notifications.append(
            f"Voucher +{noted:,.0f} cr base (pending {tracker.pending_bounty_base:,.0f})"
        )
        result.ui_dirty = True


def _handle_mission_completed(
    tracker: TrackerState,
    entry: dict[str, Any],
    *,
    ts: str,
    result: ProcessResult,
) -> None:
    for fe in entry.get("FactionEffects") or []:
        if not isinstance(fe, dict):
            continue
        fac = fe.get("Faction")
        for inf in fe.get("Influence") or []:
            if not isinstance(inf, dict):
                continue
            inf_str = str(inf.get("Influence") or "")
            if fac != tracker.faction or not inf_str.startswith("+"):
                continue
            act = tracker.add_mission(ts, tracker.system, str(fac), inf_str)
            if act:
                result.actions.append(act)
                result.notifications.append(
                    f"Mission +{inf_str} (INF {int(act.raw_value)}) " f"→ est {act.est_delta:+.2f}%"
                )
                result.ui_dirty = True


def _voucher_type(entry: dict[str, Any]) -> str:
    return str(entry.get("Type") or "").lower().replace(" ", "")


def _handle_redeem_voucher(
    tracker: TrackerState,
    session: SessionState,
    entry: dict[str, Any],
    *,
    ts: str,
    result: ProcessResult,
) -> None:
    """Bounty and CombatBond hand-ins (manual §8.35)."""
    turnin = session.current_system or tracker.system
    vtype = _voucher_type(entry)

    if vtype == "bounty":
        factions = entry.get("Factions") or []
        if not factions and entry.get("Faction"):
            factions = [{"Faction": entry["Faction"], "Amount": entry.get("Amount", 0)}]
        for item in factions:
            if not isinstance(item, dict):
                continue
            fac = item.get("Faction")
            cash = float(item.get("Amount") or 0)
            if fac != tracker.faction or cash <= 0:
                continue
            # Always attempt redeem; base is pending face value and/or PP reverse
            act = tracker.redeem_bounty_cash(
                ts, tracker.system or turnin, str(fac), cash, turnin_system=turnin
            )
            if act:
                result.actions.append(act)
                if act.bonus_value > 0.5:
                    msg = (
                        f"Bounty base {act.raw_value:,.0f} + perk {act.bonus_value:,.0f} "
                        f"= {act.cash_value:,.0f} cr → est {act.est_delta:+.2f}%"
                    )
                else:
                    msg = f"Bounty base {act.raw_value:,.0f} cr " f"→ est {act.est_delta:+.2f}%"
                result.notifications.append(msg)
                result.ui_dirty = True
        return

    if vtype in ("combatbond", "combatbonds"):
        # Bonds: single Faction + Amount (manual)
        fac = entry.get("Faction")
        amount = float(entry.get("Amount") or 0)
        if not fac or amount <= 0:
            return
        if fac != tracker.faction:
            return
        act = tracker.add_combat_bond(ts, tracker.system, str(fac), amount, turnin_system=turnin)
        if act:
            result.actions.append(act)
            result.notifications.append(
                f"Combat bonds {amount:,.0f} cr → est {act.est_delta:+.2f}%"
            )
            result.ui_dirty = True


def _handle_market_sell(
    tracker: TrackerState,
    session: SessionState,
    entry: dict[str, Any],
    *,
    ts: str,
    result: ProcessResult,
) -> None:
    """
    Trade profit (manual §7.6): TotalSale − Count×AvgPricePaid.

    Attributed to the station's controlling minor faction from the last Docked event
    (same approach as BGS-Tally's station_faction attribution).
    """
    fac = session.station_faction
    if not fac or fac != tracker.faction:
        return
    total_sale = float(entry.get("TotalSale") or 0)
    count = float(entry.get("Count") or 0)
    avg_paid = float(entry.get("AvgPricePaid") or 0)
    profit = total_sale - count * avg_paid
    if profit <= 0:
        return
    turnin = session.current_system or tracker.system
    act = tracker.add_trade_profit(ts, tracker.system, fac, profit, turnin_system=turnin)
    if act:
        result.actions.append(act)
        result.notifications.append(f"Trade profit {profit:,.0f} cr → est {act.est_delta:+.2f}%")
        result.ui_dirty = True


def _handle_sell_exploration(
    tracker: TrackerState,
    session: SessionState,
    entry: dict[str, Any],
    *,
    ts: str,
    result: ProcessResult,
) -> None:
    base = float(entry.get("BaseValue") or 0)
    bonus = float(entry.get("Bonus") or 0)
    total = entry.get("TotalEarnings")
    total_f = float(total) if total is not None else None
    turnin = session.current_system or tracker.system
    act = tracker.add_exploration(ts, turnin, base_value=base, bonus=bonus, total_earnings=total_f)
    if act:
        result.actions.append(act)
        result.notifications.append(
            f"Exploration base {act.raw_value:,.0f} cr"
            + (f" (cash {act.cash_value:,.0f})" if act.cash_value > act.raw_value else "")
            + f" @ {turnin or '?'}"
        )
        result.ui_dirty = True
