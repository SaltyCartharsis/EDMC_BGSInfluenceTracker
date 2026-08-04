"""
Discord ANSI session report for Powerplay / BGS activity.

Paste target is a Discord message using an ``ansi`` fenced code block.
Escape sequences use the real ESC character (U+001B) so the clipboard
contents render colours in Discord desktop clients.

Report formats (user-selectable in plugin settings):
  - verbose  — multi-line labeled report (default)
  - compact  — shorter labeled block, full faction name
  - tally    — BGS-Tally style: system, initials+INF, activity line
"""

from __future__ import annotations

import re
from typing import Final, Literal

from .influence_model import TrackerState
from .journal_handlers import SessionState

ESC = "\u001b"

ReportFormat = Literal["verbose", "compact", "tally"]
REPORT_FORMATS: Final[tuple[str, ...]] = ("verbose", "compact", "tally")

# UI labels for settings radios
REPORT_FORMAT_LABELS: Final[dict[str, str]] = {
    "verbose": "Verbose — full multi-line report",
    "compact": "Compact — shorter labels, full faction name",
    "tally": "Tally — system / initials+INF / activity line (BGS-Tally style)",
}

# Obviously fictional names for settings-page previews (not real game content).
EXAMPLE_SYSTEM: Final[str] = "Wobblegong Folly"
EXAMPLE_FACTION: Final[str] = "Space Hamster Liberation Front"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _c(code: str, text: str) -> str:
    """Wrap *text* in ANSI SGR *code* and reset."""
    return f"{ESC}[{code}m{text}{ESC}[0m"


def format_credits(value: float) -> str:
    """Human-readable credits (e.g. 1,234,567 cr)."""
    return f"{value:,.0f} cr"


def human_amount(value: float) -> str:
    """Compact credit amount for tally lines (50.0k, 1.2M, …)."""
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
    """
    Abbreviate a minor faction name to the first letter of each word.

    Examples:
      ``Mother Gaia`` → ``MG``
      ``Sol Workers' Party`` → ``SWP``
      ``Anti-Xeno Initiative`` → ``AXI`` (hyphen splits)
    """
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


def _turn_in(tracker: TrackerState, session: SessionState) -> str:
    return tracker.last_turnin_system or session.current_system or tracker.system or "—"


def _activity_tokens(tracker: TrackerState, *, short: bool) -> list[str]:
    """Build coloured activity tokens (only non-zero / meaningful items)."""
    tokens: list[str] = []
    bounty = tracker.total_bounty_base
    explor = tracker.total_exploration_base
    est = tracker.total_est_delta
    missions = tracker.bucket_counts.get("mission", 0)
    b_hands = tracker.bucket_counts.get("bounty", 0)
    explor_n = tracker.bucket_counts.get("exploration", 0)

    if bounty > 0:
        label = "BVs" if short else "Bounty"
        amt = human_amount(bounty) if short else format_credits(bounty)
        tokens.append(f"{_c('1;31', label)} {_c('0;32', amt)}")
    if explor > 0:
        label = "Expl" if short else "Exploration"
        amt = human_amount(explor) if short else format_credits(explor)
        tokens.append(f"{_c('0;36', label)} {_c('0;32', amt)}")
    if abs(est) > 1e-9:
        dcode = "1;32" if est >= 0 else "1;31"
        tokens.append(f"{_c('1;33', 'INF')} {_c(dcode, f'{est:+.2f}%')}")
    if missions:
        tokens.append(f"{_c('0;35', 'Ms')} {_c('0;37', str(missions))}")
    if b_hands and short:
        tokens.append(f"{_c('0;35', 'B')} {_c('0;37', str(b_hands))}")
    if explor_n and short:
        tokens.append(f"{_c('0;35', 'Cart')} {_c('0;37', str(explor_n))}")
    if not tokens:
        tokens.append(_c("0;90", "no session activity yet"))
    return tokens


def _format_verbose(tracker: TrackerState, session: SessionState) -> str:
    turn_in = _turn_in(tracker, session)
    tracked_system = tracker.system or "—"
    faction = tracker.faction or "—"
    inf_pct = tracker.current_influence * 100.0
    est_delta = tracker.total_est_delta
    bounty_base = tracker.total_bounty_base
    explor_base = tracker.total_exploration_base
    explor_total = tracker.total_exploration_earnings

    lines = [
        _c("1;36", "══ Powerplay / BGS Session Report ══"),
        "",
        f"{_c('1;37', 'Turn-in system:')}  {_c('0;36', turn_in)}",
        f"{_c('1;37', 'Tracked system:')}  {_c('0;36', tracked_system)}",
        f"{_c('1;37', 'Faction:')}         {_c('0;33', faction)}",
        f"{_c('1;37', 'Faction INF:')}     {_c('0;32', f'{inf_pct:.1f}%')}",
        "",
        _c("1;37", "── Session totals ──"),
        f"{_c('1;37', 'Bounty vouchers (base):')}  {_c('0;32', format_credits(bounty_base))}",
        f"{_c('1;37', 'Exploration data (base):')} {_c('0;32', format_credits(explor_base))}",
    ]
    if explor_total > explor_base + 0.5:
        lines.append(
            f"{_c('0;90', '  (exploration cash incl. bonuses:')} "
            f"{_c('0;90', format_credits(explor_total) + ')')}"
        )
    actions_summary = (
        f"{tracker.bucket_counts.get('mission', 0)} missions, "
        f"{tracker.bucket_counts.get('bounty', 0)} bounty hand-ins, "
        f"{tracker.bucket_counts.get('exploration', 0)} cartographics"
    )
    delta_code = "1;32" if est_delta >= 0 else "1;31"
    lines.extend(
        [
            f"{_c('1;37', 'Est. influence Δ:')}      {_c(delta_code, f'{est_delta:+.2f}%')}",
            f"{_c('1;37', 'Actions:')}              {_c('0;37', actions_summary)}",
        ]
    )
    return "\n".join(lines)


def _format_compact(tracker: TrackerState, session: SessionState) -> str:
    turn_in = _turn_in(tracker, session)
    system = tracker.system or turn_in
    faction = tracker.faction or "—"
    inf_pct = tracker.current_influence * 100.0
    activity = "  ".join(_activity_tokens(tracker, short=True))
    lines = [
        f"{_c('1;37', system)}  ·  {_c('1;33', faction)}",
        f"{_c('0;37', 'INF')} {_c('0;32', f'{inf_pct:.1f}%')}  "
        f"{_c('0;37', 'turn-in')} {_c('0;36', turn_in)}",
        activity,
    ]
    return "\n".join(lines)


def _format_tally(tracker: TrackerState, session: SessionState) -> str:
    """
    Most succinct, BGS-Tally inspired:

    Line 1: system
    Line 2: faction initials + current influence
    Line 3: session activity (BVs / Expl / est INF Δ / counts)
    """
    turn_in = _turn_in(tracker, session)
    system = tracker.system or turn_in
    faction = tracker.faction or "—"
    initials = faction_initials(faction)
    inf_pct = tracker.current_influence * 100.0
    activity = " ".join(_activity_tokens(tracker, short=True))
    lines = [
        _c("1;37", system),
        f"{_c('1;33', initials)}  {_c('0;32', f'{inf_pct:.1f}%')}",
        activity,
    ]
    return "\n".join(lines)


def format_discord_report(
    tracker: TrackerState,
    session: SessionState,
    *,
    report_format: str = "verbose",
    wrap_codeblock: bool = True,
) -> str:
    """
    Build a Discord-ready ANSI report of the current session.

    Reports bounty **base** voucher value only (no Powerplay cash perk),
    exploration data **BaseValue** totals, and estimated BGS influence Δ.
    """
    fmt = normalize_report_format(report_format)
    if fmt == "compact":
        body = _format_compact(tracker, session)
    elif fmt == "tally":
        body = _format_tally(tracker, session)
    else:
        body = _format_verbose(tracker, session)

    if wrap_codeblock:
        return f"```ansi\n{body}\n```"
    return body


def strip_ansi(text: str) -> str:
    """Remove ANSI SGR sequences for plain-text previews (e.g. settings UI)."""
    return _ANSI_RE.sub("", text)


def example_sample_state() -> tuple[TrackerState, SessionState]:
    """Fictional sample session used for format previews in settings."""
    tracker = TrackerState(
        system=EXAMPLE_SYSTEM,
        faction=EXAMPLE_FACTION,
        current_influence=0.337,
        total_bounty_base=125_000,
        total_exploration_base=42_000,
        total_exploration_earnings=42_000,
        total_est_delta=2.15,
        last_turnin_system=EXAMPLE_SYSTEM,
        bucket_counts={"mission": 3, "bounty": 2, "exploration": 1},
    )
    session = SessionState(current_system=EXAMPLE_SYSTEM)
    return tracker, session


def format_example_report(report_format: str, *, plain: bool = True) -> str:
    """
    Build an example report for the given format (goofy fictional system/faction).

    When *plain* is True, ANSI codes are stripped for display in tk Labels.
    """
    tracker, session = example_sample_state()
    text = format_discord_report(
        tracker,
        session,
        report_format=report_format,
        wrap_codeblock=False,
    )
    return strip_ansi(text) if plain else text
