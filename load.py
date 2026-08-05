"""
EDMC plugin entrypoint for BGS Influence Tracker.

Follows EDMC plugin conventions (see PLUGINS.md): thin load.py hooks, unique
package imports (``bgsinf``) so we never collide with other plugins' modules
such as EDMCModernOverlay's ``overlay_client`` package.
"""

from __future__ import annotations

import csv
import logging
import os
import sys
import threading
import time
import tkinter as tk
import webbrowser
from contextlib import suppress
from pathlib import Path
from typing import Any, Optional

# Ensure this plugin directory is on sys.path (EDMC usually does this already).
_PLUGIN_DIR = Path(__file__).resolve().parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

# EDMC-provided modules
import myNotebook as nb  # type: ignore[import-not-found]
from config import appname, config  # type: ignore[import-not-found]

# Unique package — never top-level names like overlay_client / widgets.
from bgsinf.discord_report import (
    EXAMPLE_FACTION,
    EXAMPLE_SYSTEM,
    REPORT_FORMAT_LABELS,
    REPORT_FORMATS,
    format_discord_report,
    format_example_report,
    format_mission_inf_breakdown,
    normalize_report_format,
)
from bgsinf.edsm_client import apply_edsm_system_data
from bgsinf.edsm_client import fetch_edsm_system as _fetch_edsm_system
from bgsinf.influence_model import TrackerState
from bgsinf.journal_handlers import SessionState, process_journal_entry
from bgsinf.overlay import OverlayClient

plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")
__version__ = "1.2.2"
VERSION = __version__

# Pref keys (unique prefix)
_CFG_SYSTEM = f"{plugin_name}.system"
_CFG_FACTION = f"{plugin_name}.faction"
_CFG_DISCORD_FORMAT = f"{plugin_name}.discord_format"
_CFG_OPPOSING_PLAYERS = f"{plugin_name}.opposing_players"
_CFG_ALLY_PLAYERS = f"{plugin_name}.ally_players"
_CFG_INCLUDE_EST = f"{plugin_name}.include_est_delta"

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
tracker = TrackerState()
session = SessionState()
overlay = OverlayClient()
discord_format: str = "verbose"
include_est_delta: bool = True

status_label: Optional[tk.Label] = None
detail_label: Optional[tk.Label] = None
faction_var: Optional[tk.StringVar] = None
system_var: Optional[tk.StringVar] = None
discord_format_var: Optional[tk.StringVar] = None
opposing_players_var: Optional[tk.StringVar] = None
ally_players_var: Optional[tk.StringVar] = None
include_est_var: Optional[tk.BooleanVar] = None
faction_combo: Optional[tk.Widget] = None
prefs_frame: Optional[nb.Frame] = None
app_frame: Optional[tk.Frame] = None


def fetch_edsm_system(system: str) -> dict[str, Any]:
    """Return population + factions dict. Non-blocking caller should use thread."""
    return _fetch_edsm_system(system, user_agent=getattr(config, "user_agent", "EDMC-BGSInf/1.0"))


def open_inara(system: str) -> None:
    webbrowser.open(f"https://inara.cz/elite/starsystem/?search={system}")


def _load_prefs() -> None:
    """Restore tracker + report options from EDMC config."""
    global discord_format, include_est_delta
    try:
        sys_pref = (config.get_str(_CFG_SYSTEM) or "").strip()
        fac_pref = (config.get_str(_CFG_FACTION) or "").strip()
        fmt_pref = normalize_report_format(config.get_str(_CFG_DISCORD_FORMAT) or "verbose")
        if sys_pref:
            tracker.system = sys_pref
        if fac_pref:
            tracker.faction = fac_pref
        discord_format = fmt_pref
        try:
            opp = int(config.get_int(_CFG_OPPOSING_PLAYERS) or 0)
        except Exception:
            opp = 0
        try:
            allies = int(config.get_int(_CFG_ALLY_PLAYERS) or 0)
        except Exception:
            allies = 0
        tracker.set_player_estimates(allies=max(0, allies), opponents=max(0, opp))
        try:
            include_est_delta = bool(config.get_bool(_CFG_INCLUDE_EST))
        except Exception:
            # Older EDMC / missing key
            raw = config.get_str(_CFG_INCLUDE_EST)
            include_est_delta = True if raw in (None, "", "1", "True", "true") else bool(raw)
            if raw in ("0", "False", "false"):
                include_est_delta = False
    except Exception as e:
        logger.debug("Could not restore prefs: %s", e)


# ---------------------------------------------------------------------------
# Plugin lifecycle
# ---------------------------------------------------------------------------
def plugin_start3(plugin_dir: str) -> str:
    logger.info("%s %s started (dir=%s)", plugin_name, VERSION, plugin_dir)
    _load_prefs()
    return plugin_name


def plugin_stop() -> None:
    logger.info("%s stopped", plugin_name)


def plugin_app(parent: tk.Frame) -> tk.Frame:
    global status_label, detail_label, app_frame
    frame = tk.Frame(parent)
    app_frame = frame
    tk.Label(frame, text="BGS Inf:").grid(row=0, column=0, sticky="w")
    status_label = tk.Label(frame, text="—", foreground="#00cc88")
    status_label.grid(row=0, column=1, sticky="w")
    detail_label = tk.Label(frame, text="", foreground="#aaaaaa", font=("TkDefaultFont", 8))
    detail_label.grid(row=1, column=0, columnspan=2, sticky="w")
    tk.Button(frame, text="Copy Discord report", command=_copy_discord_report).grid(
        row=2, column=0, columnspan=2, sticky="w", pady=(2, 0)
    )
    _update_ui()
    return frame


def plugin_prefs(parent: nb.Notebook, cmdr: str, is_beta: bool) -> nb.Frame:
    """
    Settings tab shown when the user opens EDMC Settings.

    Lets the commander pick tracked system/faction and Discord report format.
    """
    global prefs_frame, faction_var, system_var, discord_format_var, faction_combo
    global opposing_players_var, ally_players_var, include_est_var
    frame = nb.Frame(parent)
    prefs_frame = frame
    row = 0

    # ---- Tracking ----
    nb.Label(frame, text="Tracking").grid(
        row=row, column=0, columnspan=2, sticky="w", padx=5, pady=(8, 2)
    )
    row += 1

    nb.Label(frame, text="System of interest").grid(row=row, column=0, sticky="w", padx=5, pady=2)
    system_var = tk.StringVar(value=config.get_str(_CFG_SYSTEM) or tracker.system or "")
    # myNotebook exposes EntryMenu (not Entry) — see EDMC myNotebook.py
    nb.EntryMenu(frame, textvariable=system_var, width=36).grid(
        row=row, column=1, sticky="w", padx=5
    )
    row += 1

    nb.Label(frame, text="Minor faction to track").grid(
        row=row, column=0, sticky="w", padx=5, pady=2
    )
    faction_var = tk.StringVar(value=config.get_str(_CFG_FACTION) or tracker.faction or "")
    # Combobox: journal/EDSM faction list when available; still typeable.
    try:
        from tkinter import ttk

        faction_combo = ttk.Combobox(frame, textvariable=faction_var, width=34)
        faction_combo.grid(row=row, column=1, sticky="w", padx=5)
        _refresh_faction_choices()
    except Exception:
        faction_combo = None
        nb.EntryMenu(frame, textvariable=faction_var, width=36).grid(
            row=row, column=1, sticky="w", padx=5
        )
    row += 1

    nb.Label(
        frame,
        text="Tip: jump into the system (or Refresh from EDSM) to populate the faction list.",
    ).grid(row=row, column=0, columnspan=2, sticky="w", padx=5, pady=(0, 6))
    row += 1

    # ---- Estimation options ----
    nb.Label(frame, text="Influence estimate").grid(
        row=row, column=0, columnspan=2, sticky="w", padx=5, pady=(8, 2)
    )
    row += 1

    nb.Label(frame, text="Est. same-faction allies active").grid(
        row=row, column=0, sticky="w", padx=5, pady=2
    )
    ally_players_var = tk.StringVar(value=str(max(0, tracker.ally_players)))
    nb.EntryMenu(frame, textvariable=ally_players_var, width=8).grid(
        row=row, column=1, sticky="w", padx=5
    )
    row += 1

    nb.Label(frame, text="Est. opposing faction players active").grid(
        row=row, column=0, sticky="w", padx=5, pady=2
    )
    opposing_players_var = tk.StringVar(value=str(max(0, tracker.opposing_players)))
    nb.EntryMenu(frame, textvariable=opposing_players_var, width=8).grid(
        row=row, column=1, sticky="w", padx=5
    )
    row += 1
    nb.Label(
        frame,
        text=(
            "Player-side multiplier ≈ (1 + allies) / (1 + opponents), "
            "assuming similar effort per CMDR (you are the leading 1). "
            "Allies boost faction-side Est. Δ; opponents dilute it. "
            "Combined with system contest (faction count / population)."
        ),
    ).grid(row=row, column=0, columnspan=2, sticky="w", padx=5, pady=(0, 4))
    row += 1

    include_est_var = tk.BooleanVar(value=include_est_delta)
    nb.Checkbutton(
        frame,
        text="Include estimated influence Δ (Est) in Discord reports",
        variable=include_est_var,
    ).grid(row=row, column=0, columnspan=2, sticky="w", padx=5, pady=2)
    row += 1

    # ---- Discord report format ----
    nb.Label(frame, text="Discord report format").grid(
        row=row, column=0, columnspan=2, sticky="w", padx=5, pady=(8, 2)
    )
    row += 1
    nb.Label(
        frame,
        text=(
            f"Examples use fictional names only: system “{EXAMPLE_SYSTEM}”, "
            f"faction “{EXAMPLE_FACTION}” (not in-game)."
        ),
    ).grid(row=row, column=0, columnspan=2, sticky="w", padx=5, pady=(0, 4))
    row += 1

    saved_fmt = normalize_report_format(config.get_str(_CFG_DISCORD_FORMAT) or discord_format)
    discord_format_var = tk.StringVar(value=saved_fmt)
    mono = ("TkFixedFont", 8)
    for fmt in REPORT_FORMATS:
        nb.Radiobutton(
            frame,
            text=REPORT_FORMAT_LABELS.get(fmt, fmt),
            variable=discord_format_var,
            value=fmt,
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=20, pady=(4, 0))
        row += 1
        example = format_example_report(fmt, plain=True)
        # Prefs theming: tk.Label for multi-line mono preview (nb.Label is fine too)
        example_lbl = tk.Label(
            frame,
            text=example,
            justify=tk.LEFT,
            anchor="nw",
            font=mono,
            foreground="#888888",
        )
        example_lbl.grid(row=row, column=0, columnspan=2, sticky="w", padx=40, pady=(0, 4))
        row += 1

    nb.Label(
        frame,
        text="Tally abbreviates the faction to initials (e.g. Space Hamster Liberation Front → SHLF).",
    ).grid(row=row, column=0, columnspan=2, sticky="w", padx=5, pady=(2, 8))
    row += 1

    # ---- Actions ----
    nb.Button(frame, text="Refresh from EDSM / Journal", command=_refresh_data).grid(
        row=row, column=0, columnspan=2, pady=2
    )
    row += 1
    nb.Button(
        frame,
        text="Open system on Inara",
        command=lambda: open_inara(system_var.get() if system_var else ""),
    ).grid(row=row, column=0, columnspan=2, pady=2)
    row += 1
    nb.Button(frame, text="Reset session totals", command=_reset_session).grid(
        row=row, column=0, columnspan=2, pady=2
    )
    row += 1
    nb.Button(frame, text="Export CSV…", command=_export_csv).grid(
        row=row, column=0, columnspan=2, pady=2
    )
    row += 1
    nb.Button(frame, text="Copy Discord report (ANSI)", command=_copy_discord_report).grid(
        row=row, column=0, columnspan=2, pady=2
    )
    row += 1

    nb.Label(
        frame, text=f"v{VERSION}  |  Overlay: {'OK' if overlay.available else 'not detected'}"
    ).grid(row=row, column=0, columnspan=2, pady=8)
    return frame


def prefs_changed(cmdr: str, is_beta: bool) -> None:
    global discord_format, include_est_delta
    if system_var:
        sys_val = system_var.get().strip()
        config.set(_CFG_SYSTEM, sys_val)
        tracker.system = sys_val
    if faction_var:
        fac_val = faction_var.get().strip()
        config.set(_CFG_FACTION, fac_val)
        tracker.faction = fac_val
    if discord_format_var:
        discord_format = normalize_report_format(discord_format_var.get())
        config.set(_CFG_DISCORD_FORMAT, discord_format)
    allies = tracker.ally_players
    opponents = tracker.opposing_players
    if ally_players_var is not None:
        try:
            allies = max(0, int(str(ally_players_var.get()).strip() or "0"))
        except ValueError:
            allies = 0
        config.set(_CFG_ALLY_PLAYERS, allies)
    if opposing_players_var is not None:
        try:
            opponents = max(0, int(str(opposing_players_var.get()).strip() or "0"))
        except ValueError:
            opponents = 0
        config.set(_CFG_OPPOSING_PLAYERS, opponents)
    if ally_players_var is not None or opposing_players_var is not None:
        tracker.set_player_estimates(allies=allies, opponents=opponents)
    if include_est_var is not None:
        include_est_delta = bool(include_est_var.get())
        try:
            config.set(_CFG_INCLUDE_EST, include_est_delta)
        except Exception:
            config.set(_CFG_INCLUDE_EST, "1" if include_est_delta else "0")
    _update_ui()


def journal_entry(
    cmdr: str,
    is_beta: bool,
    system: str,
    station: str,
    entry: dict[str, Any],
    state: dict[str, Any],
) -> Optional[str]:
    result = process_journal_entry(tracker, session, entry, system=system)
    for msg in result.notifications:
        _notify(msg)
    if result.ui_dirty:
        _refresh_faction_choices()
        _update_ui()
    return None


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------
def _refresh_faction_choices() -> None:
    """Update settings Combobox values from known minor factions."""
    if faction_combo is None:
        return
    names = list(session.available_factions)
    # Keep current selection visible even if not in the system list yet
    current = (faction_var.get() if faction_var else "") or tracker.faction
    if current and current not in names:
        names = [current] + names
    with suppress(Exception):
        faction_combo["values"] = names  # type: ignore[index]


def _update_ui() -> None:
    if not status_label:
        return
    pop_m = tracker.population / 1e6 if tracker.population else 0
    show_est = include_est_delta
    if include_est_var is not None:
        show_est = bool(include_est_var.get())
    if show_est:
        txt = (
            f"{tracker.faction or '?'} @ {tracker.system or '?'}  "
            f"Inf {tracker.current_influence * 100:.1f}%  "
            f"Est Δ {tracker.total_est_delta:+.2f}%  "
            f"(pop {pop_m:.2f}M)"
        )
    else:
        txt = (
            f"{tracker.faction or '?'} @ {tracker.system or '?'}  "
            f"Inf {tracker.current_influence * 100:.1f}%  "
            f"(pop {pop_m:.2f}M)"
        )
    status_label["text"] = txt
    if detail_label:
        inf_plain = format_mission_inf_breakdown(tracker, coloured=False)
        parts = [inf_plain] if inf_plain else []
        if tracker.total_bounty_base:
            parts.append(f"BVs {tracker.total_bounty_base / 1e3:.0f}k")
        if tracker.total_bond_credits:
            parts.append(f"CBs {tracker.total_bond_credits / 1e3:.0f}k")
        if tracker.total_trade_profit:
            parts.append(f"Trd {tracker.total_trade_profit / 1e3:.0f}k")
        if tracker.total_exploration_base:
            parts.append(f"Expl {tracker.total_exploration_base / 1e3:.0f}k")
        if show_est and abs(tracker.total_est_delta) > 1e-9:
            parts.append(f"Est {tracker.total_est_delta:+.2f}%")
        if tracker.ally_players > 0:
            parts.append(f"ally×{tracker.ally_players}")
        if tracker.opposing_players > 0:
            parts.append(f"opp×{tracker.opposing_players}")
        parts.append(f"[{normalize_report_format(discord_format)}]")
        detail_label["text"] = "  ".join(p for p in parts if p)

    if overlay.available and tracker.faction:
        inf_plain = format_mission_inf_breakdown(tracker, coloured=False)
        line2_bits = [b for b in (inf_plain,) if b]
        if show_est and abs(tracker.total_est_delta) > 1e-9:
            line2_bits.append(f"Est {tracker.total_est_delta:+.2f}%")
        line2 = "  ".join(line2_bits) if line2_bits else "—"
        overlay.send(
            "bgsinf",
            f"BGS {tracker.faction[:18]}\n{line2}",
            color="#00ff88",
            ttl=12,
            x=30,
            y=200,
        )


def _notify(msg: str) -> None:
    logger.info(msg)
    if overlay.available:
        overlay.send("bgsinf_evt", msg, color="#ffcc00", ttl=6, x=30, y=260)


def _refresh_data() -> None:
    sysname = (system_var.get() if system_var else tracker.system) or session.current_system
    if not sysname:
        return

    def worker() -> None:
        data = fetch_edsm_system(sysname)
        apply_edsm_system_data(tracker, sysname, data)
        # Populate faction dropdown from EDSM names when available
        factions = data.get("factions") or []
        names: list[str] = []
        for f in factions:
            if isinstance(f, dict):
                n = f.get("name") or f.get("Name")
                if n:
                    names.append(str(n))
        if names:
            session.available_factions = names
        _refresh_faction_choices()
        _update_ui()

    threading.Thread(target=worker, daemon=True).start()


def _reset_session() -> None:
    tracker.reset_session()
    _update_ui()


def _export_csv() -> None:
    if not tracker.actions:
        return
    path = Path.home() / f"EDMC_BGS_{tracker.system}_{int(time.time())}.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "timestamp",
                "kind",
                "faction",
                "system",
                "base_value",
                "cash_value",
                "bonus_value",
                "points",
                "est_delta_pct",
                "running_total_pct",
            ]
        )
        running = 0.0
        for a in tracker.actions:
            running += a.est_delta
            w.writerow(
                [
                    a.timestamp,
                    a.kind,
                    a.faction,
                    a.system,
                    a.raw_value,
                    a.cash_value,
                    a.bonus_value,
                    f"{a.points:.3f}",
                    f"{a.est_delta:.4f}",
                    f"{running:.4f}",
                ]
            )
    logger.info("Exported %s", path)
    if status_label:
        status_label["text"] = f"Exported → {path.name}"


def _copy_discord_report() -> None:
    """Copy an ANSI Discord code block for the current session to the clipboard."""
    # Prefer live settings if prefs open; else saved globals
    fmt = discord_format
    if discord_format_var is not None:
        fmt = normalize_report_format(discord_format_var.get())
    # Apply live ally/opponent boxes before generating report
    live_allies = tracker.ally_players
    live_opp = tracker.opposing_players
    if ally_players_var is not None:
        with suppress(ValueError):
            live_allies = max(0, int(str(ally_players_var.get()).strip() or "0"))
    if opposing_players_var is not None:
        with suppress(ValueError):
            live_opp = max(0, int(str(opposing_players_var.get()).strip() or "0"))
    if ally_players_var is not None or opposing_players_var is not None:
        tracker.set_player_estimates(allies=live_allies, opponents=live_opp)
    show_est = include_est_delta
    if include_est_var is not None:
        show_est = bool(include_est_var.get())
    text = format_discord_report(tracker, session, report_format=fmt, include_est_delta=show_est)
    widget = prefs_frame or app_frame
    try:
        if widget is not None:
            root = widget.winfo_toplevel()
            root.clipboard_clear()
            root.clipboard_append(text)
            root.update_idletasks()
        else:
            r = tk.Tk()
            r.withdraw()
            r.clipboard_clear()
            r.clipboard_append(text)
            r.update()
            r.destroy()
    except Exception as e:
        logger.warning("Clipboard copy failed: %s", e)
        if status_label:
            status_label["text"] = "Clipboard copy failed"
        return
    logger.info("Discord report copied (%s, %d chars)", fmt, len(text))
    if status_label:
        status_label["text"] = f"Discord report copied ({fmt})"
    _notify(f"Discord report copied ({fmt})")
