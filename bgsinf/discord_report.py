"""
Discord ANSI session report for Powerplay / BGS activity.

Mission INF reporting follows BGS-Tally style:
  INF +12 (1×2 2×1 3×1)  — total units and per-tier counts (arabic levels 1–5).
"""

from __future__ import annotations

import re
from typing import Final, Literal

from .influence_model import TrackerState
from .journal_handlers import SessionState

ESC = "\u001b"

ReportFormat = Literal["verbose", "compact", "tally"]
REPORT_FORMATS: Final[tuple[str, ...]] = ("verbose", "compact", "tally")

REPORT_FORMAT_LABELS: Final[dict[str, str]] = {
    "verbose": "Verbose — full multi-line report",
    "compact": "Compact — shorter labels, full faction name",
    "tally": "Tally — system / initials+INF / activity line (BGS-Tally style)",
}

EXAMPLE_SYSTEM: Final[str] = "Wobblegong Folly"
EXAMPLE_FACTION: Final[str] = "Space Hamster Liberation Front"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Optional roman numerals for display (1–5)
_ROMAN: Final[dict[int, str]] = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}


def _c(code: str, text: str) -> str:
    return f"{ESC}[{code}m{text}{ESC}[0m"


def format_credits(value: float) -> str:
    return f"{value:,.0f} cr"


def human_amount(value: float) -> str:
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1_000_000_000:
        return f"{sign}{v / 1e9:.1f}B"
    if v >= 1_000_000:
        return f"{sign}{v / 1e6:.1f}M"
    if v >= 1_000:
        return f"{sign}{v / 1e3:.1f}k"
    return f"{sign}{v:.0f}"


def faction_initials(name: str) -> str:
    cleaned = name.replace("-", " ").replace("'", " ")
    parts = [p for p in cleaned.split() if p]
    if not parts:
        return "?"
    letters: list[str] = []
    for p in parts:
        for ch in p:
            if ch.isalnum():
                letters.append(ch.upper())
                break
    return "".join(letters) if letters else "?"


def normalize_report_format(value: str | None) -> ReportFormat:
    v = (value or "verbose").strip().lower()
    if v in REPORT_FORMATS:
        return v  # type: ignore[return-value]
    return "verbose"


def format_mission_inf_breakdown(
    tracker: TrackerState,
    *,
    use_roman: bool = False,
    coloured: bool = True,
) -> str:
    """
    BGS-Tally-style mission INF string.

    Example: ``INF +12 (1×2 2×1 3×1)`` or with roman ``INF +12 (I×2 II×1 III×1)``.
    Total is Σ(level × count). Empty string if no mission INF recorded.
    """
    total = tracker.mission_inf_total_units()
    if total == 0:
        return ""
    parts: list[str] = []
    for level in range(1, 6):
        count = int(tracker.mission_inf_counts.get(level, 0))
        if count <= 0:
            continue
        label = _ROMAN[level] if use_roman else str(level)
        if coloured:
            parts.append(f"{_c('0;37', label)}×{_c('0;32', str(count))}")
        else:
            parts.append(f"{label}×{count}")
    detail = " ".join(parts)
    total_s = f"+{total}" if total > 0 else str(total)
    if coloured:
        return f"{_c('0;34', 'INF')} {_c('0;32', total_s)} ({detail})"
    return f"INF {total_s} ({detail})"


def _turn_in(tracker: TrackerState, session: SessionState) -> str:
    return tracker.last_turnin_system or session.current_system or tracker.system or "—"


def _activity_tokens(
    tracker: TrackerState,
    *,
    short: bool,
    include_est_delta: bool = True,
) -> list[str]:
    """Coloured activity tokens — only non-zero contributions."""
    tokens: list[str] = []

    inf_tok = format_mission_inf_breakdown(tracker, use_roman=False, coloured=True)
    if inf_tok:
        tokens.append(inf_tok)

    if tracker.total_bounty_base > 0:
        label = "BVs" if short else "Bounty"
        amt = (
            human_amount(tracker.total_bounty_base)
            if short
            else format_credits(tracker.total_bounty_base)
        )
        tokens.append(f"{_c('1;31', label)} {_c('0;32', amt)}")

    if tracker.total_bond_credits > 0:
        label = "CBs" if short else "Combat bonds"
        amt = (
            human_amount(tracker.total_bond_credits)
            if short
            else format_credits(tracker.total_bond_credits)
        )
        tokens.append(f"{_c('1;31', label)} {_c('0;32', amt)}")

    if tracker.total_trade_profit > 0:
        label = "TrdProfit" if short else "Trade profit"
        amt = (
            human_amount(tracker.total_trade_profit)
            if short
            else format_credits(tracker.total_trade_profit)
        )
        tokens.append(f"{_c('0;36', label)} {_c('0;32', amt)}")

    if tracker.total_exploration_base > 0:
        label = "Expl" if short else "Exploration"
        amt = (
            human_amount(tracker.total_exploration_base)
            if short
            else format_credits(tracker.total_exploration_base)
        )
        tokens.append(f"{_c('0;36', label)} {_c('0;32', amt)}")

    if include_est_delta and abs(tracker.total_est_delta) > 1e-9:
        dcode = "1;32" if tracker.total_est_delta >= 0 else "1;31"
        tokens.append(f"{_c('1;33', 'Est')} {_c(dcode, f'{tracker.total_est_delta:+.2f}%')}")

    if not tokens:
        tokens.append(_c("0;90", "no session activity yet"))
    return tokens


def _format_verbose(
    tracker: TrackerState,
    session: SessionState,
    *,
    include_est_delta: bool = True,
) -> str:
    turn_in = _turn_in(tracker, session)
    tracked_system = tracker.system or "—"
    faction = tracker.faction or "—"
    inf_pct = tracker.current_influence * 100.0

    lines = [
        _c("1;36", "══ Powerplay / BGS Session Report ══"),
        "",
        f"{_c('1;37', 'Turn-in system:')}  {_c('0;36', turn_in)}",
        f"{_c('1;37', 'Tracked system:')}  {_c('0;36', tracked_system)}",
        f"{_c('1;37', 'Faction:')}         {_c('0;33', faction)}",
        f"{_c('1;37', 'Faction INF:')}     {_c('0;32', f'{inf_pct:.1f}%')}",
        "",
        _c("1;37", "── Session totals ──"),
    ]
    inf_line = format_mission_inf_breakdown(tracker, coloured=True)
    if inf_line:
        lines.append(f"{_c('1;37', 'Mission INF:')}         {inf_line}")
    if tracker.total_bounty_base > 0:
        lines.append(
            f"{_c('1;37', 'Bounty vouchers (base):')}  "
            f"{_c('0;32', format_credits(tracker.total_bounty_base))}"
        )
    if tracker.total_bond_credits > 0:
        lines.append(
            f"{_c('1;37', 'Combat bonds:')}            "
            f"{_c('0;32', format_credits(tracker.total_bond_credits))}"
        )
    if tracker.total_trade_profit > 0:
        lines.append(
            f"{_c('1;37', 'Trade profit:')}            "
            f"{_c('0;32', format_credits(tracker.total_trade_profit))}"
        )
    if tracker.total_exploration_base > 0:
        lines.append(
            f"{_c('1;37', 'Exploration data (base):')} "
            f"{_c('0;32', format_credits(tracker.total_exploration_base))}"
        )
        if tracker.total_exploration_earnings > tracker.total_exploration_base + 0.5:
            lines.append(
                f"{_c('0;90', '  (exploration cash incl. bonuses:')} "
                f"{_c('0;90', format_credits(tracker.total_exploration_earnings) + ')')}"
            )
    if include_est_delta and abs(tracker.total_est_delta) > 1e-9:
        est_delta = tracker.total_est_delta
        comp = tracker.competition()
        delta_code = "1;32" if est_delta >= 0 else "1;31"
        lines.append(
            f"{_c('1;37', 'Est. influence Δ:')}      "
            f"{_c(delta_code, f'{est_delta:+.2f}%')}"
            f"  {_c('0;90', f'(competition×{comp:.2f})')}"
        )
    # Drop trailing section header if no totals at all
    if lines[-1] == _c("1;37", "── Session totals ──"):
        lines.pop()
        if lines and lines[-1] == "":
            lines.pop()
    return "\n".join(lines)


def _format_compact(
    tracker: TrackerState,
    session: SessionState,
    *,
    include_est_delta: bool = True,
) -> str:
    turn_in = _turn_in(tracker, session)
    system = tracker.system or turn_in
    faction = tracker.faction or "—"
    inf_pct = tracker.current_influence * 100.0
    activity = "  ".join(_activity_tokens(tracker, short=True, include_est_delta=include_est_delta))
    return "\n".join(
        [
            f"{_c('1;37', system)}  ·  {_c('1;33', faction)}",
            f"{_c('0;37', 'INF%')} {_c('0;32', f'{inf_pct:.1f}%')}  "
            f"{_c('0;37', 'turn-in')} {_c('0;36', turn_in)}",
            activity,
        ]
    )


def _format_tally(
    tracker: TrackerState,
    session: SessionState,
    *,
    include_est_delta: bool = True,
) -> str:
    turn_in = _turn_in(tracker, session)
    system = tracker.system or turn_in
    faction = tracker.faction or "—"
    initials = faction_initials(faction)
    inf_pct = tracker.current_influence * 100.0
    activity = " ".join(_activity_tokens(tracker, short=True, include_est_delta=include_est_delta))
    return "\n".join(
        [
            _c("1;37", system),
            f"{_c('1;33', initials)}  {_c('0;32', f'{inf_pct:.1f}%')}",
            activity,
        ]
    )


def format_discord_report(
    tracker: TrackerState,
    session: SessionState,
    *,
    report_format: str = "verbose",
    wrap_codeblock: bool = True,
    include_est_delta: bool = True,
) -> str:
    fmt = normalize_report_format(report_format)
    if fmt == "compact":
        body = _format_compact(tracker, session, include_est_delta=include_est_delta)
    elif fmt == "tally":
        body = _format_tally(tracker, session, include_est_delta=include_est_delta)
    else:
        body = _format_verbose(tracker, session, include_est_delta=include_est_delta)

    if wrap_codeblock:
        return f"```ansi\n{body}\n```"
    return body


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def example_sample_state() -> tuple[TrackerState, SessionState]:
    tracker = TrackerState(
        system=EXAMPLE_SYSTEM,
        faction=EXAMPLE_FACTION,
        current_influence=0.337,
        population=2_500_000,
        num_factions=4,
        total_bounty_base=125_000,
        total_bond_credits=80_000,
        total_trade_profit=55_000,
        total_exploration_base=42_000,
        total_exploration_earnings=42_000,
        total_est_delta=1.85,
        last_turnin_system=EXAMPLE_SYSTEM,
        mission_inf_counts={1: 2, 2: 1, 3: 1, 4: 0, 5: 0},
        bucket_counts={
            "mission": 4,
            "bounty": 2,
            "bond": 1,
            "trade": 3,
            "exploration": 1,
        },
    )
    session = SessionState(current_system=EXAMPLE_SYSTEM)
    return tracker, session


def format_example_report(
    report_format: str,
    *,
    plain: bool = True,
    include_est_delta: bool = True,
) -> str:
    tracker, session = example_sample_state()
    text = format_discord_report(
        tracker,
        session,
        report_format=report_format,
        wrap_codeblock=False,
        include_est_delta=include_est_delta,
    )
    return strip_ansi(text) if plain else text
