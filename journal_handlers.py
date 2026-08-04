"""
Pure journal event handlers for BGS influence tracking.

Shapes follow Frontier Journal Manual v32/v34 and EDMC's journal_entry hook:
https://hosting.zaonce.net/community/journal/v32/Journal_Manual-v32.pdf
https://github.com/EDCD/EDMarketConnector/blob/main/PLUGINS.md

Bounty base vs Powerplay cash:
  - ``Bounty`` (kill): face-value rewards → pending base stack
  - ``RedeemVoucher`` type bounty: cash paid (Amount / Factions[].Amount);
    official docs do **not** list a separate Powerplay bonus field. We derive
    bonus as cash − pending base when kills were tracked this session.

No EDMC, Tk, or network imports — safe to unit-test outside the host.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from influence_model import Action, TrackerState

# Events that carry system population / minor-faction lists (manual §§4.8, 4.12, 11.1).
SYSTEM_EVENTS = frozenset({"FSDJump", "Location", "CarrierJump"})


@dataclass
class SessionState:
    """Plugin session fields updated from journal events (not persisted prefs)."""

    current_system: str = ""
    available_factions: list[str] = field(default_factory=list)


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
    """
    Apply one journal entry to tracker/session.

    Args:
        tracker: Mutable influence session (system/faction of interest already set).
        session: Mutable current location / faction list from the game.
        entry: Raw journal event dict (must include ``event``).
        system: EDMC's best-known system name (may be empty); used as fallback.

    Returns:
        ProcessResult with notification strings and whether the UI should refresh.
    """
    result = ProcessResult()
    event = entry.get("event")
    ts = str(entry.get("timestamp") or "")

    if event in SYSTEM_EVENTS:
        _handle_system_event(tracker, session, entry, system=system, result=result)

    if event == "Bounty":
        _handle_bounty_award(tracker, session, entry, system=system, ts=ts, result=result)

    if event == "MissionCompleted":
        _handle_mission_completed(tracker, entry, ts=ts, result=result)

    if event == "RedeemVoucher" and _is_bounty_voucher(entry):
        _handle_redeem_voucher(tracker, session, entry, ts=ts, result=result)

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
    for f in factions:
        if not isinstance(f, dict):
            continue
        if f.get("Name") == tracker.faction:
            tracker.current_influence = float(f.get("Influence") or 0.0)

    if not tracker.system and session.current_system:
        tracker.system = session.current_system

    result.ui_dirty = True


def extract_bounty_rewards(entry: dict[str, Any]) -> list[tuple[str, float]]:
    """
    Parse kill-time ``Bounty`` face values (manual §5.1).

    Normal ships: ``Rewards: [{Faction, Reward}, ...]`` + ``TotalReward``.
    Skimmers: single ``Faction`` + ``Reward``.
    """
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

    # Skimmer / simplified form
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
    # Bounty events do not include StarSystem; use session / EDMC system.
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
    # Manual §8.22: FactionEffects[].Influence[] with Influence string ("+", "++", …).
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
            # System match is soft: missions often credit the tracked system of interest.
            act = tracker.add_mission(ts, tracker.system, str(fac), inf_str)
            if act:
                result.actions.append(act)
                result.notifications.append(f"Mission +{inf_str} → est {act.est_delta:+.2f}%")
                result.ui_dirty = True


def _is_bounty_voucher(entry: dict[str, Any]) -> bool:
    # Manual §8.35 lists Type as Bounty; in-game examples often use "bounty".
    return str(entry.get("Type") or "").lower() == "bounty"


def _handle_redeem_voucher(
    tracker: TrackerState,
    session: SessionState,
    entry: dict[str, Any],
    *,
    ts: str,
    result: ProcessResult,
) -> None:
    # Modern journals: Factions[{Faction, Amount}]; older: single Faction + Amount.
    # Amount is "Net amount received, after any broker fee" — cash, not a separate
    # base/bonus split for Powerplay perks (manual §8.35).
    turnin = session.current_system or tracker.system
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
        act = tracker.redeem_bounty_cash(ts, tracker.system, str(fac), cash, turnin_system=turnin)
        if act:
            result.actions.append(act)
            if act.bonus_value > 0:
                msg = (
                    f"Bounty base {act.raw_value:,.0f} + perk {act.bonus_value:,.0f} "
                    f"= {act.cash_value:,.0f} cr → est {act.est_delta:+.2f}% (base)"
                )
            else:
                msg = f"Bounty base {act.raw_value:,.0f} cr → est {act.est_delta:+.2f}% (base)"
            result.notifications.append(msg)
            result.ui_dirty = True


def _handle_sell_exploration(
    tracker: TrackerState,
    session: SessionState,
    entry: dict[str, Any],
    *,
    ts: str,
    result: ProcessResult,
) -> None:
    """
    Cartographics hand-in (manual §§6.11 / 6.17).

    Unlike bounty RedeemVoucher, exploration events document BaseValue, Bonus,
    and TotalEarnings (Total may include Powerplay rank multipliers e.g. LYR).
    """
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
