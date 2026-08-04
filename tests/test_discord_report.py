"""Tests for Discord ANSI session report."""

from __future__ import annotations

from discord_report import ESC, format_credits, format_discord_report
from influence_model import TrackerState
from journal_handlers import SessionState


def test_format_credits() -> None:
    assert format_credits(1_250_000) == "1,250,000 cr"


def test_discord_report_contains_key_fields_and_ansi() -> None:
    tracker = TrackerState(
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
    session = SessionState(current_system="Sol")
    text = format_discord_report(tracker, session)

    assert text.startswith("```ansi\n")
    assert text.rstrip().endswith("```")
    assert ESC in text
    assert "Mother Gaia" in text
    assert "Sol" in text
    assert "31.2%" in text
    assert "50,000 cr" in text  # bounty base
    assert "10,822 cr" in text  # exploration base
    assert "+1.25%" in text
    # bounty bonus cash must NOT be the headline (we only report base)
    assert "Powerplay / BGS Session Report" in text


def test_discord_report_shows_exploration_cash_footnote_when_bonus() -> None:
    tracker = TrackerState(
        system="X",
        faction="Y",
        total_exploration_base=1000,
        total_exploration_earnings=3000,
    )
    text = format_discord_report(tracker, SessionState())
    assert "exploration cash incl. bonuses" in text
    assert "3,000 cr" in text


def test_discord_report_without_codeblock_wrapper() -> None:
    tracker = TrackerState(system="A", faction="B")
    text = format_discord_report(tracker, SessionState(), wrap_codeblock=False)
    assert not text.startswith("```")
    assert ESC in text


def test_turnin_falls_back_to_session_then_tracked() -> None:
    tracker = TrackerState(system="Tracked", faction="F", last_turnin_system="")
    session = SessionState(current_system="Here")
    text = format_discord_report(tracker, session)
    assert "Here" in text

    tracker2 = TrackerState(system="OnlyTracked", faction="F", last_turnin_system="")
    text2 = format_discord_report(tracker2, SessionState(current_system=""))
    assert "OnlyTracked" in text2
