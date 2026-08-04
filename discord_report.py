"""
Discord ANSI session report for Powerplay / BGS activity.

Paste target is a Discord message using an ``ansi`` fenced code block.
Escape sequences use the real ESC character (U+001B) so the clipboard
contents render colours in Discord desktop clients.
"""

from __future__ import annotations

from influence_model import TrackerState
from journal_handlers import SessionState

ESC = "\u001b"


def _c(code: str, text: str) -> str:
    """Wrap *text* in ANSI SGR *code* and reset."""
    return f"{ESC}[{code}m{text}{ESC}[0m"


def format_credits(value: float) -> str:
    """Human-readable credits (e.g. 1,234,567 cr)."""
    return f"{value:,.0f} cr"


def format_discord_report(
    tracker: TrackerState,
    session: SessionState,
    *,
    wrap_codeblock: bool = True,
) -> str:
    """
    Build a Discord-ready ANSI report of the current session.

    Reports bounty **base** voucher value only (no Powerplay cash perk),
    exploration data **BaseValue** totals, and estimated BGS influence Δ.
    """
    turn_in = tracker.last_turnin_system or session.current_system or tracker.system or "—"
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
        (f"{_c('1;37', 'Bounty vouchers (base):')}  " f"{_c('0;32', format_credits(bounty_base))}"),
        (f"{_c('1;37', 'Exploration data (base):')} " f"{_c('0;32', format_credits(explor_base))}"),
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

    body = "\n".join(lines)
    if wrap_codeblock:
        return f"```ansi\n{body}\n```"
    return body
