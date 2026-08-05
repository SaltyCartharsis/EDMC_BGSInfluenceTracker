"""Unit tests for pure BGS influence estimation (influence_model.py)."""

from __future__ import annotations

import math

import pytest

from bgsinf.influence_model import (
    SCALE_BOND,
    SCALE_BOUNTY,
    SCALE_MISSION,
    SCALE_TRADE,
    Action,
    TrackerState,
    bond_points,
    bounty_points,
    competition_factor,
    mission_inf_level,
    mission_points,
    population_factor,
    resolve_redeem_base_and_bonus,
    trade_points,
)

# ---------------------------------------------------------------------------
# mission_points
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("inf_str", "expected_n"),
    [
        ("+", 1),
        ("++", 2),
        ("+++", 3),
        ("++++", 4),
        ("+++++", 5),
        ("++++++", 5),  # clamp at 5
        (" + + ", 2),  # spaces stripped before count
        ("", 1),  # empty → floor at 1
        ("   ", 1),
    ],
)
def test_mission_points_maps_plus_count(inf_str: str, expected_n: int) -> None:
    assert mission_points(inf_str) == pytest.approx(0.5 * math.log2(expected_n))


def test_mission_points_plus_vs_plusplus() -> None:
    assert mission_points("++") > mission_points("+")


# ---------------------------------------------------------------------------
# bounty_points
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "credits",
    [1.0, 1000.0, 1_000_000.0],
)
def test_bounty_points_formula(credits: float) -> None:
    assert bounty_points(credits) == pytest.approx(1.33 * math.log2(max(credits, 1.0)))


def test_bounty_points_zero_credits_uses_log2_floor() -> None:
    # _log2 floors at 1.0 → log2(1) = 0
    assert bounty_points(0.0) == pytest.approx(0.0)


def test_bounty_points_increases_with_credits() -> None:
    assert bounty_points(10_000) > bounty_points(1_000)


# ---------------------------------------------------------------------------
# population_factor
# ---------------------------------------------------------------------------


def test_population_factor_floors_at_1000() -> None:
    assert population_factor(0) == population_factor(1000)
    assert population_factor(500) == population_factor(1000)


def test_population_factor_decreases_with_population() -> None:
    assert population_factor(10_000) > population_factor(1_000_000)


def test_population_factor_minimum() -> None:
    # Very large pop should hit the 0.025 floor
    huge = 10**20
    assert population_factor(huge) == pytest.approx(0.025)


def test_population_factor_known_value() -> None:
    # 1.0 - log10(1000)/10.875 = 1.0 - 3/10.875
    expected = max(0.025, 1.0 - math.log10(1000) / 10.875)
    assert population_factor(1000) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# TrackerState — filtering
# ---------------------------------------------------------------------------


def _tracker(
    system: str = "Sol",
    faction: str = "Federation",
    population: int = 1_000_000,
) -> TrackerState:
    return TrackerState(system=system, faction=faction, population=population)


def test_add_mission_rejects_wrong_system() -> None:
    t = _tracker()
    assert t.add_mission("ts", "Other", "Federation", "++") is None
    assert t.actions == []
    assert t.bucket_counts["mission"] == 0


def test_add_mission_rejects_wrong_faction() -> None:
    t = _tracker()
    assert t.add_mission("ts", "Sol", "Empire", "++") is None
    assert t.total_points == 0.0


def test_add_bounty_rejects_mismatch() -> None:
    t = _tracker()
    assert t.add_bounty("ts", "Sol", "Empire", 5000) is None
    assert t.add_bounty("ts", "Other", "Federation", 5000) is None


# ---------------------------------------------------------------------------
# TrackerState — successful adds & totals
# ---------------------------------------------------------------------------


def test_add_mission_records_action_and_totals() -> None:
    t = _tracker()
    act = t.add_mission("2024-01-01T00:00:00Z", "Sol", "Federation", "++")
    assert act is not None
    assert isinstance(act, Action)
    assert act.kind == "mission"
    assert act.faction == "Federation"
    assert act.system == "Sol"
    assert act.raw_value == 2  # INF tier for "++"
    assert act.points > 0
    assert act.est_delta > 0
    assert t.bucket_counts["mission"] == 1
    assert t.mission_inf_counts[2] == 1
    assert t.mission_inf_total_units() == 2
    assert t.total_points == pytest.approx(act.points)
    assert t.total_est_delta == pytest.approx(act.est_delta)
    assert len(t.actions) == 1


def test_add_bounty_records_action_and_totals() -> None:
    t = _tracker()
    credits = 50_000.0
    act = t.add_bounty("ts", "Sol", "Federation", credits)
    assert act is not None
    assert act.kind == "bounty"
    assert act.raw_value == credits
    assert act.cash_value == credits
    assert act.bonus_value == 0.0
    assert t.bucket_counts["bounty"] == 1
    assert t.total_points == pytest.approx(act.points)
    assert t.total_est_delta == pytest.approx(act.est_delta)
    assert t.total_bounty_base == pytest.approx(credits)


def test_add_bounty_separates_base_cash_bonus() -> None:
    t = _tracker()
    act = t.add_bounty("ts", "Sol", "Federation", base_credits=50_000, cash_credits=100_000)
    assert act is not None
    assert act.raw_value == 50_000
    assert act.cash_value == 100_000
    assert act.bonus_value == 50_000
    # Influence points from base only
    assert act.points == pytest.approx(bounty_points(50_000) / (1.0 + 0.12 * math.log1p(1)))
    assert t.total_bounty_bonus == pytest.approx(50_000)


def test_mission_diminishing_returns() -> None:
    t = _tracker()
    first = t.add_mission("t1", "Sol", "Federation", "+++")
    second = t.add_mission("t2", "Sol", "Federation", "+++")
    assert first is not None and second is not None
    assert second.points < first.points
    assert second.est_delta < first.est_delta
    assert t.bucket_counts["mission"] == 2
    assert t.total_points == pytest.approx(first.points + second.points)


def test_bounty_diminishing_returns() -> None:
    t = _tracker()
    first = t.add_bounty("t1", "Sol", "Federation", 100_000)
    second = t.add_bounty("t2", "Sol", "Federation", 100_000)
    assert first is not None and second is not None
    assert second.points < first.points


def test_mission_est_delta_uses_population_and_scale() -> None:
    t = _tracker(population=1_000_000)
    act = t.add_mission("ts", "Sol", "Federation", "+")
    assert act is not None
    decay = 1.0 / (1.0 + 0.15 * math.log1p(1))
    pts = mission_points("+") * decay
    expected_delta = pts * population_factor(1_000_000) * t.competition() * SCALE_MISSION
    assert act.points == pytest.approx(pts)
    assert act.est_delta == pytest.approx(expected_delta)


def test_bounty_est_delta_uses_population_and_scale() -> None:
    t = _tracker(population=500_000)
    act = t.add_bounty("ts", "Sol", "Federation", 10_000)
    assert act is not None
    decay = 1.0 / (1.0 + 0.12 * math.log1p(1))
    pts = bounty_points(10_000) * decay
    expected_delta = pts * population_factor(500_000) * t.competition() * SCALE_BOUNTY
    assert act.points == pytest.approx(pts)
    assert act.est_delta == pytest.approx(expected_delta)


def test_competition_factor_dilutes_with_factions_and_pop() -> None:
    solo = competition_factor(1, 1000, 0)
    crowded = competition_factor(8, 50_000_000, 0)
    assert solo == pytest.approx(1.0)
    assert crowded < solo
    assert crowded >= 0.15


def test_opposing_players_halves_then_thirds_share() -> None:
    base = competition_factor(1, 1000, 0, 0)
    one = competition_factor(1, 1000, 1, 0)
    two = competition_factor(1, 1000, 2, 0)
    assert one == pytest.approx(base / 2)
    assert two == pytest.approx(base / 3)


def test_allies_boost_share_opponents_dilute() -> None:
    solo = competition_factor(1, 1000, 0, 0)
    one_ally = competition_factor(1, 1000, 0, 1)  # (1+1)/(1+0) = 2
    one_each = competition_factor(1, 1000, 1, 1)  # (1+1)/(1+1) = 1
    assert one_ally == pytest.approx(solo * 2)
    assert one_each == pytest.approx(solo)


def test_set_player_estimates_recomputes_est_delta() -> None:
    t = _tracker(population=1_000_000)
    t.add_mission("t", "Sol", "Federation", "+++")
    solo_est = t.total_est_delta
    t.set_opposing_players(1)
    assert t.total_est_delta == pytest.approx(solo_est / 2)
    t.set_ally_players(1)  # (1+1)/(1+1) = 1 × solo system share
    assert t.total_est_delta == pytest.approx(solo_est)
    t.set_player_estimates(allies=1, opponents=0)
    assert t.total_est_delta == pytest.approx(solo_est * 2)
    t.set_player_estimates(allies=0, opponents=0)
    assert t.total_est_delta == pytest.approx(solo_est)


def test_more_factions_reduces_mission_est_delta() -> None:
    a = _tracker(population=1_000_000)
    a.num_factions = 1
    b = _tracker(population=1_000_000)
    b.num_factions = 7
    act_a = a.add_mission("t", "Sol", "Federation", "+++")
    act_b = b.add_mission("t", "Sol", "Federation", "+++")
    assert act_a is not None and act_b is not None
    assert act_b.est_delta < act_a.est_delta


def test_combat_bond_and_trade_profit() -> None:
    t = _tracker(population=1_000_000)
    bond = t.add_combat_bond("t", "Sol", "Federation", 25_000)
    trade = t.add_trade_profit("t", "Sol", "Federation", 12_000)
    assert bond is not None and trade is not None
    assert t.total_bond_credits == 25_000
    assert t.total_trade_profit == 12_000
    assert bond.est_delta > 0 and trade.est_delta > 0
    decay_b = 1.0 / (1.0 + 0.12 * math.log1p(1))
    expected_bond = (
        bond_points(25_000) * decay_b * population_factor(1_000_000) * t.competition() * SCALE_BOND
    )
    assert bond.est_delta == pytest.approx(expected_bond)
    decay_t = 1.0 / (1.0 + 0.10 * math.log1p(1))
    expected_trade = (
        trade_points(12_000)
        * decay_t
        * population_factor(1_000_000)
        * t.competition()
        * SCALE_TRADE
    )
    assert trade.est_delta == pytest.approx(expected_trade)


def test_mission_inf_level() -> None:
    assert mission_inf_level("+") == 1
    assert mission_inf_level("+++++") == 5
    assert mission_inf_level("++++++") == 5


# ---------------------------------------------------------------------------
# reset_session
# ---------------------------------------------------------------------------


def test_reset_session_clears_actions_keeps_context() -> None:
    t = _tracker()
    t.current_influence = 0.42
    t.add_mission("ts", "Sol", "Federation", "++")
    t.add_bounty("ts", "Sol", "Federation", 1000)
    t.note_bounty_award("Sol", "Federation", 5000)
    assert t.actions
    assert t.total_points > 0
    assert t.pending_bounty_base > 0

    t.reset_session()

    assert t.actions == []
    assert t.bucket_counts == {
        "mission": 0,
        "bounty": 0,
        "bond": 0,
        "trade": 0,
        "exploration": 0,
    }
    assert t.mission_inf_total_units() == 0
    assert t.total_points == 0.0
    assert t.total_est_delta == 0.0
    assert t.pending_bounty_base == 0.0
    assert t.total_bounty_base == 0.0
    assert t.total_bounty_cash == 0.0
    assert t.total_bounty_bonus == 0.0
    assert t.total_bond_credits == 0.0
    assert t.total_trade_profit == 0.0
    assert t.total_exploration_base == 0.0
    assert t.last_turnin_system == ""
    # context preserved
    assert t.system == "Sol"
    assert t.faction == "Federation"
    assert t.population == 1_000_000
    assert t.current_influence == pytest.approx(0.42)


# ---------------------------------------------------------------------------
# Base vs Powerplay cash split
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pending", "cash", "base", "bonus", "remaining"),
    [
        (0, 1000, 0, 1000, 0),  # no kill-time base → never treat cash as base
        (50_000, 100_000, 50_000, 50_000, 0),  # ALD-style 100% cash bonus
        (80_000, 50_000, 50_000, 0, 30_000),  # partial redeem, no surplus
        (50_000, 50_000, 50_000, 0, 0),  # exact full redeem
        (10_000, 0, 0, 0, 10_000),
    ],
)
def test_resolve_redeem_base_and_bonus(
    pending: float, cash: float, base: float, bonus: float, remaining: float
) -> None:
    b, bo, rem = resolve_redeem_base_and_bonus(pending, cash)
    assert b == pytest.approx(base)
    assert bo == pytest.approx(bonus)
    assert rem == pytest.approx(remaining)


def test_note_bounty_award_and_redeem_with_perk() -> None:
    t = _tracker()
    assert t.note_bounty_award("Sol", "Federation", 50_000) == 50_000
    assert t.pending_bounty_base == 50_000
    act = t.redeem_bounty_cash("ts", "Sol", "Federation", 100_000)
    assert act is not None
    assert act.raw_value == 50_000  # base face value, not PP cash
    assert act.cash_value == 100_000
    assert act.bonus_value == 50_000
    assert t.total_bounty_base == 50_000
    assert t.total_bounty_cash == 100_000
    assert t.pending_bounty_base == 0.0


def test_redeem_without_pending_base_does_not_use_cash_as_base() -> None:
    """Powerplay cash must not become BVs when kill-time face value was not stacked."""
    t = _tracker()
    act = t.redeem_bounty_cash("ts", "Sol", "Federation", 100_000)
    assert act is None
    assert t.total_bounty_base == 0.0
    assert t.total_bounty_cash == 0.0
    assert t.bucket_counts["bounty"] == 0


def test_note_bounty_award_wrong_system_ignored() -> None:
    t = _tracker()
    assert t.note_bounty_award("Other", "Federation", 50_000) == 0
    assert t.pending_bounty_base == 0


def test_note_bounty_award_empty_system_still_stacks() -> None:
    """Location briefly unknown must not drop face-value vouchers."""
    t = _tracker()
    assert t.note_bounty_award("", "Federation", 12_000) == 12_000
    assert t.pending_bounty_base == 12_000


def test_reset_session_allows_fresh_decay() -> None:
    t = _tracker()
    t.add_mission("t1", "Sol", "Federation", "++")
    t.add_mission("t2", "Sol", "Federation", "++")
    t.reset_session()
    again = t.add_mission("t3", "Sol", "Federation", "++")
    first_after = t.add_mission("t4", "Sol", "Federation", "++")
    assert again is not None and first_after is not None
    # After reset, first add uses count=1 decay again (higher than second)
    assert again.points > first_after.points
