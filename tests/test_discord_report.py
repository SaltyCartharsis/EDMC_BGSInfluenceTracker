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
        total_bounty_base=50_000,
        total_exploration_base=10822,
        total_exploration_earnings=44343,
        total_est_delta=1.25,
        last_turnin_system="Sol",
        bucket_counts={"mission": 2, "bounty": 1, "exploration": 1},
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


def test_verbose_report_contains_key_fields_and_ansi() -> None:
    text = format_discord_report(_sample_tracker(), SessionState(current_system="Sol"))
    assert text.startswith("```ansi\n")
    assert text.rstrip().endswith("```")
    assert ESC in text
    assert "Mother Gaia" in text
    assert "Sol" in text
    assert "31.2%" in text
    assert "50,000 cr" in text
    assert "10,822 cr" in text
    assert "+1.25%" in text
    assert "Powerplay / BGS Session Report" in text


def test_compact_report() -> None:
    text = format_discord_report(
        _sample_tracker(), SessionState(), report_format="compact", wrap_codeblock=False
    )
    assert "Mother Gaia" in text
    assert "Sol" in text
    assert "31.2%" in text
    assert "BVs" in text
    assert "Expl" in text
    assert "Powerplay / BGS Session Report" not in text
    lines = text.splitlines()
    assert len(lines) == 3


def test_tally_report_uses_initials_and_two_content_lines_after_system() -> None:
    text = format_discord_report(
        _sample_tracker(), SessionState(), report_format="tally", wrap_codeblock=False
    )
    lines = text.splitlines()
    assert len(lines) == 3
    # strip ANSI for structure checks
    plain = "".join(ch if ord(ch) >= 32 else "" for ch in text)
    assert "MG" in plain
    assert "Mother Gaia" not in plain
    assert "31.2%" in plain
    assert "BVs" in plain
    assert "50.0k" in plain
    assert "Expl" in plain
    assert "INF" in plain
    assert "+1.25%" in plain


def test_verbose_shows_exploration_cash_footnote_when_bonus() -> None:
    tracker = TrackerState(
        system="X",
        faction="Y",
        total_exploration_base=1000,
        total_exploration_earnings=3000,
    )
    text = format_discord_report(tracker, SessionState(), report_format="verbose")
    assert "exploration cash incl. bonuses" in text
    assert "3,000 cr" in text


def test_without_codeblock_wrapper() -> None:
    tracker = TrackerState(system="A", faction="B")
    text = format_discord_report(tracker, SessionState(), wrap_codeblock=False)
    assert not text.startswith("```")
    assert ESC in text


def test_turnin_falls_back_to_session_then_tracked() -> None:
    tracker = TrackerState(system="Tracked", faction="F", last_turnin_system="")
    session = SessionState(current_system="Here")
    text = format_discord_report(tracker, session, report_format="verbose")
    assert "Here" in text

    tracker2 = TrackerState(system="OnlyTracked", faction="F", last_turnin_system="")
    text2 = format_discord_report(tracker2, SessionState(current_system=""))
    assert "OnlyTracked" in text2


def test_strip_ansi_removes_sgr() -> None:
    assert strip_ansi(f"{ESC}[1;32mhi{ESC}[0m") == "hi"


def test_format_example_report_uses_goofy_names_plain() -> None:
    for fmt in ("verbose", "compact", "tally"):
        text = format_example_report(fmt, plain=True)
        assert EXAMPLE_SYSTEM in text
        assert ESC not in text
        if fmt == "tally":
            assert "SHLF" in text  # Space Hamster Liberation Front
            assert EXAMPLE_FACTION not in text
        else:
            assert EXAMPLE_FACTION in text
