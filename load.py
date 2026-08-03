# load.py  – top section only
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Make sure the plugin directory is on sys.path (EDMC already does this,
# but being explicit never hurts and helps when running tests outside EDMC)
# ---------------------------------------------------------------------------
_PLUGIN_DIR = Path(__file__).resolve().parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

# EDMC-provided modules
from config import config, appname
import myNotebook as nb

# Our own modules – plain imports (EDMC added the folder to sys.path)
from influence_model import TrackerState, Action

# Overlay is optional
try:
    from overlay_client import OverlayClient
except Exception as e:
    OverlayClient = None          # type: ignore
    _overlay_import_error = e
else:
    _overlay_import_error = None

# ---------------------------------------------------------------------------
plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")
__version__ = "1.0.0"
VERSION = __version__

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
tracker = TrackerState()
overlay = OverlayClient()
status_label: Optional[tk.Label] = None
detail_label: Optional[tk.Label] = None
faction_var: Optional[tk.StringVar] = None
system_var: Optional[tk.StringVar] = None
available_factions: List[str] = []
current_system: str = ""
prefs_frame: Optional[nb.Frame] = None

# ---------------------------------------------------------------------------
# EDSM helpers (Inara has no public read API for this data)
# ---------------------------------------------------------------------------
def fetch_edsm_system(system: str) -> Dict[str, Any]:
    """Return population + factions dict. Non-blocking caller should use thread."""
    try:
        r = requests.get(
            "https://www.edsm.net/api-system-v1/factions",
            params={"systemName": system},
            timeout=8,
            headers={"User-Agent": config.user_agent},
        )
        r.raise_for_status()
        data = r.json()
        pop_r = requests.get(
            "https://www.edsm.net/api-v1/system",
            params={"systemName": system, "showInformation": 1},
            timeout=8,
            headers={"User-Agent": config.user_agent},
        )
        pop = 0
        if pop_r.ok:
            info = pop_r.json().get("information") or {}
            pop = int(info.get("population") or 0)
        return {"population": pop, "factions": data.get("factions") or []}
    except Exception as e:
        logger.warning("EDSM fetch failed: %s", e)
        return {"population": 0, "factions": []}

def open_inara(system: str):
    import webbrowser
    webbrowser.open(f"https://inara.cz/elite/starsystem/?search={system}")

# ---------------------------------------------------------------------------
# Plugin lifecycle
# ---------------------------------------------------------------------------
def plugin_start3(plugin_dir: str) -> str:
    logger.info("%s %s started", plugin_name, VERSION)
    return plugin_name

def plugin_stop():
    logger.info("%s stopped", plugin_name)

def plugin_app(parent: tk.Frame):
    global status_label, detail_label
    frame = tk.Frame(parent)
    tk.Label(frame, text="BGS Inf:").grid(row=0, column=0, sticky="w")
    status_label = tk.Label(frame, text="—", foreground="#00cc88")
    status_label.grid(row=0, column=1, sticky="w")
    detail_label = tk.Label(frame, text="", foreground="#aaaaaa", font=("TkDefaultFont", 8))
    detail_label.grid(row=1, column=0, columnspan=2, sticky="w")
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

    nb.Button(frame, text="Refresh from EDSM / Journal", command=_refresh_data).grid(row=2, column=0, columnspan=2, pady=4)
    nb.Button(frame, text="Open system on Inara", command=lambda: open_inara(system_var.get())).grid(row=3, column=0, columnspan=2, pady=2)
    nb.Button(frame, text="Reset session totals", command=_reset_session).grid(row=4, column=0, columnspan=2, pady=2)
    nb.Button(frame, text="Export CSV…", command=_export_csv).grid(row=5, column=0, columnspan=2, pady=4)

    nb.Label(frame, text=f"v{VERSION}  |  Overlay: {'OK' if overlay.available else 'not detected'}").grid(row=6, column=0, columnspan=2, pady=8)
    return frame

def prefs_changed(cmdr: str, is_beta: bool):
    if system_var:
        config.set(f"{plugin_name}.system", system_var.get().strip())
        tracker.system = system_var.get().strip()
    if faction_var:
        config.set(f"{plugin_name}.faction", faction_var.get().strip())
        tracker.faction = faction_var.get().strip()
    _update_ui()

# ---------------------------------------------------------------------------
# Journal handler
# ---------------------------------------------------------------------------
def journal_entry(cmdr: str, is_beta: bool, system: str, station: str,
                  entry: Dict[str, Any], state: Dict[str, Any]) -> Optional[str]:
    global current_system, available_factions

    event = entry.get("event")
    ts = entry.get("timestamp", "")

    # ---- system / faction list update ----
    if event in ("FSDJump", "Location", "CarrierJump"):
        current_system = entry.get("StarSystem") or system or ""
        if "Population" in entry:
            tracker.population = int(entry["Population"])
        factions = entry.get("Factions") or []
        available_factions = [f["Name"] for f in factions]
        for f in factions:
            if f["Name"] == tracker.faction:
                tracker.current_influence = float(f.get("Influence") or 0.0)
        if not tracker.system:
            tracker.system = current_system
        _update_ui()

    # ---- mission influence ----
    if event == "MissionCompleted":
        for fe in entry.get("FactionEffects") or []:
            fac = fe.get("Faction")
            for inf in fe.get("Influence") or []:
                # Influence entries contain SystemAddress + Trend + Influence string
                inf_str = inf.get("Influence", "")
                # We only care about positive influence for the tracked faction
                if fac == tracker.faction and inf_str.startswith("+"):
                    # System match is soft – many missions affect the origin system
                    act = tracker.add_mission(ts, tracker.system, fac, inf_str)
                    if act:
                        _notify(f"Mission +{inf_str} → est {act.est_delta:+.2f}%")
                        _update_ui()

    # ---- bounty vouchers ----
    if event == "RedeemVoucher" and entry.get("Type") == "bounty":
        # modern journals use Factions array; older use single Faction
        factions = entry.get("Factions") or []
        if not factions and entry.get("Faction"):
            factions = [{"Faction": entry["Faction"], "Amount": entry.get("Amount", 0)}]
        for item in factions:
            fac = item.get("Faction")
            amount = float(item.get("Amount") or 0)
            if fac == tracker.faction and amount > 0:
                act = tracker.add_bounty(ts, tracker.system, fac, amount)
                if act:
                    _notify(f"Bounty {amount:,.0f} cr → est {act.est_delta:+.2f}%")
                    _update_ui()

    return None

# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------
def _update_ui():
    if not status_label:
        return
    pop_m = tracker.population / 1e6 if tracker.population else 0
    txt = (f"{tracker.faction or '?'} @ {tracker.system or '?'}  "
           f"Inf {tracker.current_influence*100:.1f}%  "
           f"Est Δ {tracker.total_est_delta:+.2f}%  "
           f"(pop {pop_m:.2f}M)")
    status_label["text"] = txt
    if detail_label:
        detail_label["text"] = (f"Missions: {tracker.bucket_counts['mission']}  "
                                f"Bounties: {tracker.bucket_counts['bounty']}  "
                                f"Σ points {tracker.total_points:.1f}")

    if overlay.available:
        overlay.send(
            "bgsinf",
            f"BGS {tracker.faction[:18]}\n"
            f"Δ {tracker.total_est_delta:+.2f}%  "
            f"({tracker.bucket_counts['mission']}M/{tracker.bucket_counts['bounty']}B)",
            color="#00ff88", ttl=12, x=30, y=200
        )

def _notify(msg: str):
    logger.info(msg)
    if overlay.available:
        overlay.send("bgsinf_evt", msg, color="#ffcc00", ttl=6, x=30, y=260)

def _refresh_data():
    sysname = (system_var.get() if system_var else tracker.system) or current_system
    if not sysname:
        return
    def worker():
        data = fetch_edsm_system(sysname)
        tracker.system = sysname
        tracker.population = data["population"] or tracker.population
        for f in data["factions"]:
            if f.get("name") == tracker.faction:
                tracker.current_influence = float(f.get("influence") or 0)
        _update_ui()
    threading.Thread(target=worker, daemon=True).start()

def _reset_session():
    tracker.reset_session()
    _update_ui()

def _export_csv():
    if not tracker.actions:
        return
    path = Path.home() / f"EDMC_BGS_{tracker.system}_{int(time.time())}.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "kind", "faction", "system", "raw_value",
                    "points", "est_delta_pct", "running_total_pct"])
        running = 0.0
        for a in tracker.actions:
            running += a.est_delta
            w.writerow([a.timestamp, a.kind, a.faction, a.system,
                        a.raw_value, f"{a.points:.3f}", f"{a.est_delta:.4f}",
                        f"{running:.4f}"])
    logger.info("Exported %s", path)
    if status_label:
        status_label["text"] = f"Exported → {path.name}"