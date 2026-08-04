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
from bgsinf.discord_report import format_discord_report
from bgsinf.edsm_client import apply_edsm_system_data
from bgsinf.edsm_client import fetch_edsm_system as _fetch_edsm_system
from bgsinf.influence_model import TrackerState
from bgsinf.journal_handlers import SessionState, process_journal_entry
from bgsinf.overlay import OverlayClient

plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")
__version__ = "1.0.1"
VERSION = __version__

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
tracker = TrackerState()
session = SessionState()
overlay = OverlayClient()
status_label: Optional[tk.Label] = None
detail_label: Optional[tk.Label] = None
faction_var: Optional[tk.StringVar] = None
system_var: Optional[tk.StringVar] = None
prefs_frame: Optional[nb.Frame] = None
app_frame: Optional[tk.Frame] = None


def fetch_edsm_system(system: str) -> dict[str, Any]:
    """Return population + factions dict. Non-blocking caller should use thread."""
    return _fetch_edsm_system(system, user_agent=getattr(config, "user_agent", "EDMC-BGSInf/1.0"))


def open_inara(system: str) -> None:
    webbrowser.open(f"https://inara.cz/elite/starsystem/?search={system}")


# ---------------------------------------------------------------------------
# Plugin lifecycle
# ---------------------------------------------------------------------------
def plugin_start3(plugin_dir: str) -> str:
    logger.info("%s %s started (dir=%s)", plugin_name, VERSION, plugin_dir)
    # Restore prefs into tracker if previously saved
    try:
        sys_pref = (config.get_str(f"{plugin_name}.system") or "").strip()
        fac_pref = (config.get_str(f"{plugin_name}.faction") or "").strip()
        if sys_pref:
            tracker.system = sys_pref
        if fac_pref:
            tracker.faction = fac_pref
    except Exception as e:
        logger.debug("Could not restore prefs: %s", e)
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
    global prefs_frame, faction_var, system_var
    frame = nb.Frame(parent)
    prefs_frame = frame

    nb.Label(frame, text="System of interest").grid(row=0, column=0, sticky="w", padx=5, pady=2)
    system_var = tk.StringVar(value=config.get_str(f"{plugin_name}.system") or "")
    nb.Entry(frame, textvariable=system_var, width=32).grid(row=0, column=1, sticky="w")

    nb.Label(frame, text="Track faction").grid(row=1, column=0, sticky="w", padx=5, pady=2)
    faction_var = tk.StringVar(value=config.get_str(f"{plugin_name}.faction") or "")
    nb.Entry(frame, textvariable=faction_var, width=32).grid(row=1, column=1, sticky="w")

    nb.Button(frame, text="Refresh from EDSM / Journal", command=_refresh_data).grid(
        row=2, column=0, columnspan=2, pady=4
    )
    nb.Button(
        frame, text="Open system on Inara", command=lambda: open_inara(system_var.get())
    ).grid(row=3, column=0, columnspan=2, pady=2)
    nb.Button(frame, text="Reset session totals", command=_reset_session).grid(
        row=4, column=0, columnspan=2, pady=2
    )
    nb.Button(frame, text="Export CSV…", command=_export_csv).grid(
        row=5, column=0, columnspan=2, pady=4
    )
    nb.Button(
        frame,
        text="Copy Discord report (ANSI)",
        command=_copy_discord_report,
    ).grid(row=6, column=0, columnspan=2, pady=4)

    nb.Label(
        frame, text=f"v{VERSION}  |  Overlay: {'OK' if overlay.available else 'not detected'}"
    ).grid(row=7, column=0, columnspan=2, pady=8)
    return frame


def prefs_changed(cmdr: str, is_beta: bool) -> None:
    if system_var:
        config.set(f"{plugin_name}.system", system_var.get().strip())
        tracker.system = system_var.get().strip()
    if faction_var:
        config.set(f"{plugin_name}.faction", faction_var.get().strip())
        tracker.faction = faction_var.get().strip()
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
        _update_ui()
    return None


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------
def _update_ui() -> None:
    if not status_label:
        return
    pop_m = tracker.population / 1e6 if tracker.population else 0
    txt = (
        f"{tracker.faction or '?'} @ {tracker.system or '?'}  "
        f"Inf {tracker.current_influence * 100:.1f}%  "
        f"Est Δ {tracker.total_est_delta:+.2f}%  "
        f"(pop {pop_m:.2f}M)"
    )
    status_label["text"] = txt
    if detail_label:
        bounty_extra = ""
        if tracker.total_bounty_base or tracker.total_bounty_bonus:
            bounty_extra = (
                f"  base {tracker.total_bounty_base / 1e3:.0f}k"
                f" +perk {tracker.total_bounty_bonus / 1e3:.0f}k"
            )
            if tracker.pending_bounty_base:
                bounty_extra += f"  pend {tracker.pending_bounty_base / 1e3:.0f}k"
        explor = tracker.bucket_counts.get("exploration", 0)
        explor_extra = ""
        if tracker.total_exploration_base:
            explor_extra = f"  exp {tracker.total_exploration_base / 1e3:.0f}k"
        detail_label["text"] = (
            f"Missions: {tracker.bucket_counts['mission']}  "
            f"Bounties: {tracker.bucket_counts['bounty']}  "
            f"Expl: {explor}  "
            f"Σ points {tracker.total_points:.1f}"
            f"{bounty_extra}{explor_extra}"
        )

    if overlay.available and tracker.faction:
        overlay.send(
            "bgsinf",
            f"BGS {tracker.faction[:18]}\n"
            f"Δ {tracker.total_est_delta:+.2f}%  "
            f"({tracker.bucket_counts['mission']}M/{tracker.bucket_counts['bounty']}B)",
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
    text = format_discord_report(tracker, session)
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
    logger.info("Discord report copied to clipboard (%d chars)", len(text))
    if status_label:
        status_label["text"] = "Discord report copied"
    _notify("Discord report copied to clipboard")
