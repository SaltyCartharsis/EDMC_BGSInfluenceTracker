"""Tests for Discord ANSI session report formats."""

from __future__ import annotations

from bgsinf.discord_report import (
    ESC,
    EXAMPLE_FACTION,
    EXAMPLE_SYSTEM,
    faction_initials,
    format_credits,
    format_discord_report,
    format_example_report,
    format_mission_inf_breakdown,
    human_amount,
    normalize_report_format,
    strip_ansi,
)
from bgsinf.influence_model import TrackerState
from bgsinf.journal_handlers import SessionState


def _sample_tracker() -> TrackerState:
    return TrackerState(
        system="Sol",
        faction="Mother Gaia",
        current_influence=0.312,
        population=1_000_000,
        num_factions=3,
        total_bounty_base=50_000,
        total_bond_credits=20_000,
        total_trade_profit=15_000,
        total_exploration_base=10822,
        total_exploration_earnings=44343,
        total_est_delta=1.25,
        last_turnin_system="Sol",
        mission_inf_counts={1: 2, 2: 1, 3: 1, 4: 0, 5: 0},
        bucket_counts={
            "mission": 4,
            "bounty": 1,
            "bond": 1,
            "trade": 2,
            "exploration": 1,
        },
    )


def test_format_credits() -> None:
    assert format_credits(1_250_000) == "1,250,000 cr"


def test_human_amount() -> None:
    assert human_amount(500) == "500"
    assert human_amount(50_000) == "50.0k"
    assert human_amount(1_500_000) == "1.5M"


def test_faction_initials() -> None:
    assert faction_initials("Mother Gaia") == "MG"
    assert faction_initials("Sol Workers' Party") == "SWP"
    assert faction_initials("Anti-Xeno Initiative") == "AXI"
    assert faction_initials("") == "?"


def test_normalize_report_format() -> None:
    assert normalize_report_format("verbose") == "verbose"
    assert normalize_report_format("TALLY") == "tally"
    assert normalize_report_format("nope") == "verbose"
    assert normalize_report_format(None) == "verbose"


def test_mission_inf_breakdown_tally_style() -> None:
    t = _sample_tracker()
    # total units = 1*2 + 2*1 + 3*1 = 7
    plain = format_mission_inf_breakdown(t, coloured=False)
    assert plain == "INF +7 (1×2 2×1 3×1)"
    coloured = format_mission_inf_breakdown(t, coloured=True)
    assert "INF" in coloured
    assert ESC in coloured


def test_verbose_report_contains_key_fields_and_ansi() -> None:
    text = format_discord_report(_sample_tracker(), SessionState(current_system="Sol"))
    assert text.startswith("```ansi\n")
    assert text.rstrip().endswith("```")
    assert ESC in text
    assert "Mother Gaia" in text
    assert "Sol" in text
    assert "31.2%" in text
    assert "50,000 cr" in text
    assert "Combat bonds" in text or "bonds" in text.lower()
    assert "+1.25%" in text
    assert "Powerplay / BGS Session Report" in text
    plain = strip_ansi(text)
    assert "INF +7" in plain
    assert "1×2" in plain


def test_compact_and_tally_use_inf_breakdown_not_mission_count() -> None:
    t = _sample_tracker()
    for fmt in ("compact", "tally"):
        plain = strip_ansi(
            format_discord_report(t, SessionState(), report_format=fmt, wrap_codeblock=False)
        )
        assert "INF +7" in plain
        assert "1×2" in plain
        assert "Ms " not in plain  # no bare mission-count token
        assert "BVs" in plain
        assert "CBs" in plain
        assert "TrdProfit" in plain
        assert "Est" in plain


def test_tally_report_uses_initials() -> None:
    text = format_discord_report(
        _sample_tracker(), SessionState(), report_format="tally", wrap_codeblock=False
    )
    plain = strip_ansi(text)
    lines = plain.splitlines()
    assert len(lines) == 3
    assert "MG" in plain
    assert "Mother Gaia" not in plain


def test_format_example_report_uses_goofy_names_plain() -> None:
    for fmt in ("verbose", "compact", "tally"):
        text = format_example_report(fmt, plain=True)
        assert EXAMPLE_SYSTEM in text
        assert ESC not in text
        assert "INF +" in text
        if fmt == "tally":
            assert "SHLF" in text
            assert EXAMPLE_FACTION not in text
        else:
            assert EXAMPLE_FACTION in text


def test_strip_ansi_removes_sgr() -> None:
    assert strip_ansi(f"{ESC}[1;32mhi{ESC}[0m") == "hi"


def test_report_omits_zero_activity_lines() -> None:
    t = TrackerState(
        system="Sol",
        faction="Mother Gaia",
        current_influence=0.2,
        mission_inf_counts={1: 1, 2: 0, 3: 0, 4: 0, 5: 0},
        total_bounty_base=10_000,
        total_bond_credits=0,
        total_trade_profit=0,
        total_exploration_base=0,
        total_est_delta=0.5,
    )
    plain = strip_ansi(
        format_discord_report(t, SessionState(), report_format="verbose", wrap_codeblock=False)
    )
    assert "Bounty vouchers" in plain
    assert "Combat bonds" not in plain
    assert "Trade profit" not in plain
    assert "Exploration data" not in plain
    assert "Est. influence" in plain


def test_report_can_omit_est_delta() -> None:
    t = _sample_tracker()
    plain = strip_ansi(
        format_discord_report(
            t,
            SessionState(),
            report_format="tally",
            wrap_codeblock=False,
            include_est_delta=False,
        )
    )
    assert "Est" not in plain
    assert "INF +7" in plain
