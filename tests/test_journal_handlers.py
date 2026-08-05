"""Unit tests for pure journal handlers (no EDMC host)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bgsinf.influence_model import TrackerState
from bgsinf.journal_handlers import SessionState, process_journal_entry

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "journal"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _tracker(
    system: str = "Sol",
    faction: str = "Mother Gaia",
    population: int = 1_000_000,
) -> TrackerState:
    return TrackerState(system=system, faction=faction, population=population)


# ---------------------------------------------------------------------------
# System events: FSDJump / Location / CarrierJump
# ---------------------------------------------------------------------------


def test_fsd_jump_updates_session_and_influence() -> None:
    tracker = _tracker(system="", faction="Mother Gaia", population=0)
    session = SessionState()
    entry = _load("fsd_jump.json")

    result = process_journal_entry(tracker, session, entry, system="Somewhere")

    assert result.ui_dirty is True
    assert result.notifications == []
    assert session.current_system == "Sol"
    assert session.available_factions == ["Mother Gaia", "Sol Workers' Party"]
    assert tracker.population == 22780871705
    assert tracker.current_influence == pytest.approx(0.312)
    # Empty tracker.system is filled from jump destination
    assert tracker.system == "Sol"


def test_location_same_as_system_event() -> None:
    tracker = _tracker(system="Sol", faction="Mother Gaia")
    session = SessionState(current_system="Old")
    result = process_journal_entry(tracker, session, _load("location.json"))

    assert result.ui_dirty is True
    assert session.current_system == "Sol"
    assert tracker.current_influence == pytest.approx(0.312)
    assert tracker.system == "Sol"  # already set; not overwritten


def test_carrier_jump_zero_population() -> None:
    tracker = _tracker(system="Sol", faction="Mother Gaia", population=99)
    session = SessionState()
    result = process_journal_entry(tracker, session, _load("carrier_jump.json"))

    assert result.ui_dirty is True
    assert session.current_system == "Hermitage"
    assert tracker.population == 0
    assert session.available_factions == []


def test_system_event_uses_edmc_system_fallback() -> None:
    tracker = _tracker(system="", faction="X")
    session = SessionState()
    entry = {"timestamp": "t", "event": "FSDJump"}  # no StarSystem
    process_journal_entry(tracker, session, entry, system="Fallback Sys")
    assert session.current_system == "Fallback Sys"
    assert tracker.system == "Fallback Sys"


def test_system_event_ignores_unrelated_faction_influence() -> None:
    tracker = _tracker(faction="Not Present")
    session = SessionState()
    process_journal_entry(tracker, session, _load("fsd_jump.json"))
    assert tracker.current_influence == 0.0
    assert session.available_factions  # still listed


# ---------------------------------------------------------------------------
# MissionCompleted
# ---------------------------------------------------------------------------


def test_mission_completed_tracked_faction() -> None:
    tracker = _tracker(system="Sol", faction="Mother Gaia", population=1_000_000)
    session = SessionState(current_system="Sol")
    result = process_journal_entry(tracker, session, _load("mission_completed.json"))

    assert result.ui_dirty is True
    assert len(result.actions) == 1
    assert result.actions[0].kind == "mission"
    assert result.actions[0].raw_value == 2  # "++" → INF tier 2
    assert tracker.bucket_counts["mission"] == 1
    assert tracker.mission_inf_counts[2] == 1
    assert tracker.mission_inf_total_units() == 2
    assert tracker.total_est_delta > 0
    assert any(n.startswith("Mission ++") for n in result.notifications)


def test_mission_completed_wrong_faction_ignored() -> None:
    tracker = _tracker(faction="Someone Else")
    session = SessionState()
    result = process_journal_entry(tracker, session, _load("mission_completed.json"))
    assert result.actions == []
    assert result.notifications == []
    assert result.ui_dirty is False
    assert tracker.bucket_counts["mission"] == 0


def test_mission_completed_manual_example_target_faction() -> None:
    """Journal Manual §8.22 example: influence on Tougeir Blue Clan, not issuer."""
    tracker = _tracker(system="Tougeir", faction="Tougeir Blue Clan", population=50_000)
    session = SessionState()
    result = process_journal_entry(tracker, session, _load("mission_completed_manual.json"))

    assert len(result.actions) == 1
    assert result.actions[0].raw_value == len("++++")
    assert "++++" in result.notifications[0]


def test_mission_completed_skips_empty_influence_arrays() -> None:
    tracker = _tracker(faction="Inara Nexus")
    session = SessionState()
    result = process_journal_entry(tracker, session, _load("mission_completed_manual.json"))
    # Inara Nexus has empty Influence[] in the manual example
    assert result.actions == []


def test_mission_negative_influence_ignored() -> None:
    tracker = _tracker(faction="Mother Gaia")
    session = SessionState()
    entry = {
        "timestamp": "t",
        "event": "MissionCompleted",
        "FactionEffects": [
            {
                "Faction": "Mother Gaia",
                "Influence": [{"Influence": "-", "Trend": "DownBad"}],
            }
        ],
    }
    result = process_journal_entry(tracker, session, entry)
    assert result.actions == []


# ---------------------------------------------------------------------------
# RedeemVoucher
# ---------------------------------------------------------------------------


def test_redeem_voucher_modern_factions_array() -> None:
    tracker = _tracker(faction="Mother Gaia", population=1_000_000)
    session = SessionState()
    result = process_journal_entry(tracker, session, _load("redeem_voucher.json"))

    assert len(result.actions) == 1
    assert result.actions[0].kind == "bounty"
    # No pending kills → cash treated as base (cannot detect perk)
    assert result.actions[0].raw_value == 125000
    assert result.actions[0].cash_value == 125000
    assert result.actions[0].bonus_value == 0
    assert tracker.bucket_counts["bounty"] == 1
    assert "125,000" in result.notifications[0]


def test_redeem_voucher_ignores_other_factions_in_array() -> None:
    tracker = _tracker(faction="Mother Gaia")
    session = SessionState()
    process_journal_entry(tracker, session, _load("redeem_voucher.json"))
    # Only Mother Gaia row, not "Other Faction"
    assert tracker.bucket_counts["bounty"] == 1


def test_redeem_voucher_legacy_single_faction() -> None:
    tracker = _tracker(faction="Mother Gaia", population=500_000)
    session = SessionState()
    result = process_journal_entry(tracker, session, _load("redeem_voucher_legacy.json"))
    assert len(result.actions) == 1
    assert result.actions[0].raw_value == 50000


def test_redeem_voucher_type_case_insensitive() -> None:
    tracker = _tracker(faction="Mother Gaia")
    session = SessionState()
    entry = {
        "timestamp": "t",
        "event": "RedeemVoucher",
        "Type": "Bounty",  # manual capitalisation
        "Factions": [{"Faction": "Mother Gaia", "Amount": 1000}],
    }
    result = process_journal_entry(tracker, session, entry)
    assert len(result.actions) == 1


def test_combat_bond_is_counted_as_bond_not_bounty() -> None:
    tracker = _tracker(faction="Mother Gaia")
    session = SessionState()
    result = process_journal_entry(tracker, session, _load("redeem_voucher_bond.json"))
    assert len(result.actions) == 1
    assert result.actions[0].kind == "bond"
    assert tracker.bucket_counts["bounty"] == 0
    assert tracker.bucket_counts["bond"] == 1
    assert tracker.total_bond_credits == 99999


def test_bounty_wrong_faction_ignored() -> None:
    tracker = _tracker(faction="Not You")
    session = SessionState()
    result = process_journal_entry(tracker, session, _load("redeem_voucher.json"))
    assert result.actions == []


# ---------------------------------------------------------------------------
# Bounty kill awards (base face value) + redeem with Powerplay cash
# ---------------------------------------------------------------------------


def test_bounty_kill_notes_pending_base() -> None:
    tracker = _tracker(system="Sol", faction="Mother Gaia")
    session = SessionState(current_system="Sol")
    result = process_journal_entry(tracker, session, _load("bounty_kill.json"))
    assert tracker.pending_bounty_base == 50_000
    assert result.actions == []  # influence counted at redeem
    assert any("50,000" in n for n in result.notifications)


def test_bounty_kill_multi_only_tracked_faction() -> None:
    tracker = _tracker(system="Sol", faction="Mother Gaia")
    session = SessionState(current_system="Sol")
    process_journal_entry(tracker, session, _load("bounty_kill_multi.json"))
    assert tracker.pending_bounty_base == 10_000


def test_bounty_skimmer_form() -> None:
    tracker = _tracker(system="Sol", faction="Mother Gaia")
    session = SessionState(current_system="Sol")
    process_journal_entry(tracker, session, _load("bounty_skimmer.json"))
    assert tracker.pending_bounty_base == 1000


def test_bounty_kill_wrong_system_ignored() -> None:
    tracker = _tracker(system="Sol", faction="Mother Gaia")
    session = SessionState(current_system="Other")
    process_journal_entry(tracker, session, _load("bounty_kill.json"))
    assert tracker.pending_bounty_base == 0


def test_redeem_with_powerplay_perk_splits_base_and_bonus() -> None:
    """Kill base 50k, redeem cash 100k (e.g. ALD 100% payout) → base for BGS."""
    tracker = _tracker(system="Sol", faction="Mother Gaia", population=1_000_000)
    session = SessionState(current_system="Sol")
    process_journal_entry(tracker, session, _load("bounty_kill.json"))
    result = process_journal_entry(tracker, session, _load("redeem_voucher_with_perk.json"))
    assert len(result.actions) == 1
    act = result.actions[0]
    assert act.raw_value == 50_000
    assert act.cash_value == 100_000
    assert act.bonus_value == 50_000
    assert tracker.total_bounty_base == 50_000
    assert tracker.total_bounty_bonus == 50_000
    assert tracker.pending_bounty_base == 0
    assert tracker.last_turnin_system == "Sol"
    assert "perk" in result.notifications[0].lower() or "+" in result.notifications[0]


# ---------------------------------------------------------------------------
# Exploration data (SellExplorationData / MultiSellExplorationData)
# ---------------------------------------------------------------------------


def test_sell_exploration_data_tracks_base_and_turnin() -> None:
    tracker = _tracker(system="Sol", faction="Mother Gaia")
    session = SessionState(current_system="Sol")
    result = process_journal_entry(tracker, session, _load("sell_exploration_data.json"))
    assert len(result.actions) == 1
    act = result.actions[0]
    assert act.kind == "exploration"
    assert act.raw_value == 10822  # BaseValue — report default
    assert act.cash_value == 44343  # TotalEarnings (incl. rank/PP cash)
    assert tracker.total_exploration_base == 10822
    assert tracker.total_exploration_earnings == 44343
    assert tracker.last_turnin_system == "Sol"
    assert tracker.bucket_counts["exploration"] == 1
    assert tracker.total_est_delta == 0  # not in influence estimate yet


def test_multi_sell_exploration_data() -> None:
    tracker = _tracker(system="Somewhere", faction="F")
    session = SessionState(current_system="Cartographics Hub")
    result = process_journal_entry(tracker, session, _load("multi_sell_exploration_data.json"))
    assert result.actions[0].raw_value == 2_938_186
    assert tracker.last_turnin_system == "Cartographics Hub"


def test_combat_bond_redeem() -> None:
    tracker = _tracker(system="Sol", faction="Mother Gaia", population=1_000_000)
    session = SessionState(current_system="Sol")
    result = process_journal_entry(
        tracker,
        session,
        {
            "timestamp": "t",
            "event": "RedeemVoucher",
            "Type": "CombatBond",
            "Faction": "Mother Gaia",
            "Amount": 40_000,
        },
    )
    assert len(result.actions) == 1
    assert result.actions[0].kind == "bond"
    assert tracker.total_bond_credits == 40_000
    assert tracker.total_est_delta > 0


def test_market_sell_trade_profit_for_station_faction() -> None:
    tracker = _tracker(system="Sol", faction="Mother Gaia", population=1_000_000)
    session = SessionState(current_system="Sol", station_faction="Mother Gaia")
    result = process_journal_entry(
        tracker,
        session,
        {
            "timestamp": "t",
            "event": "MarketSell",
            "Type": "gold",
            "Count": 10,
            "SellPrice": 1000,
            "TotalSale": 10_000,
            "AvgPricePaid": 400,
        },
    )
    assert len(result.actions) == 1
    assert result.actions[0].kind == "trade"
    assert result.actions[0].raw_value == 6000
    assert tracker.total_trade_profit == 6000


def test_market_sell_wrong_station_faction_ignored() -> None:
    tracker = _tracker(system="Sol", faction="Mother Gaia")
    session = SessionState(current_system="Sol", station_faction="Other")
    result = process_journal_entry(
        tracker,
        session,
        {
            "timestamp": "t",
            "event": "MarketSell",
            "Count": 1,
            "TotalSale": 1000,
            "AvgPricePaid": 0,
        },
    )
    assert result.actions == []


def test_docked_sets_station_faction() -> None:
    tracker = _tracker()
    session = SessionState()
    process_journal_entry(
        tracker,
        session,
        {
            "timestamp": "t",
            "event": "Docked",
            "StarSystem": "Sol",
            "StationFaction": {"Name": "Mother Gaia"},
        },
    )
    assert session.station_faction == "Mother Gaia"
    assert session.current_system == "Sol"


def test_system_event_sets_num_factions() -> None:
    tracker = _tracker(system="", faction="Mother Gaia")
    session = SessionState()
    process_journal_entry(tracker, session, _load("fsd_jump.json"))
    assert tracker.num_factions == 2


# ---------------------------------------------------------------------------
# Unrelated / no-op events
# ---------------------------------------------------------------------------


def test_unrelated_event_noop() -> None:
    tracker = _tracker()
    session = SessionState(current_system="Sol", available_factions=["A"])
    result = process_journal_entry(
        tracker,
        session,
        {"timestamp": "t", "event": "FSDTarget", "Starsystem": "Elsewhere"},
    )
    assert result.ui_dirty is False
    assert result.notifications == []
    assert session.current_system == "Sol"


def test_malformed_nested_entries_are_skipped() -> None:
    """Defensive: non-dict rows in Factions / FactionEffects / Influence."""
    tracker = _tracker(faction="Mother Gaia")
    session = SessionState()
    process_journal_entry(
        tracker,
        session,
        {
            "timestamp": "t",
            "event": "FSDJump",
            "StarSystem": "Sol",
            "Factions": ["not-a-dict", {"Name": "Mother Gaia", "Influence": 0.5}],
        },
    )
    assert session.available_factions == ["Mother Gaia"]
    assert tracker.current_influence == pytest.approx(0.5)

    result = process_journal_entry(
        tracker,
        session,
        {
            "timestamp": "t",
            "event": "MissionCompleted",
            "FactionEffects": [
                "bad",
                {"Faction": "Mother Gaia", "Influence": ["bad", {"Influence": "+"}]},
            ],
        },
    )
    assert len(result.actions) == 1

    result = process_journal_entry(
        tracker,
        session,
        {
            "timestamp": "t",
            "event": "RedeemVoucher",
            "Type": "bounty",
            "Factions": ["bad", {"Faction": "Mother Gaia", "Amount": 100}],
        },
    )
    assert len(result.actions) == 1
