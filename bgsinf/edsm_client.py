"""
EDSM HTTP helpers for system population and factions.

No EDMC imports — pass ``user_agent`` from the host (``config.user_agent``).
Never call live EDSM from unit tests; mock ``requests.get`` instead.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import requests

from .influence_model import TrackerState

logger = logging.getLogger(__name__)

EDSM_FACTIONS_URL = "https://www.edsm.net/api-system-v1/factions"
EDSM_SYSTEM_URL = "https://www.edsm.net/api-v1/system"
DEFAULT_TIMEOUT_S = 8.0

EMPTY_SYSTEM: dict[str, Any] = {"population": 0, "factions": []}

HttpGet = Callable[..., Any]


def fetch_edsm_system(
    system: str,
    *,
    user_agent: str,
    timeout: float = DEFAULT_TIMEOUT_S,
    http_get: HttpGet | None = None,
) -> dict[str, Any]:
    """
    Return ``{"population": int, "factions": list}`` for a star system.

    On any network/HTTP/parse failure, returns empty defaults (does not raise).
    """
    get = http_get or requests.get
    headers = {"User-Agent": user_agent}
    try:
        r = get(
            EDSM_FACTIONS_URL,
            params={"systemName": system},
            timeout=timeout,
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()

        pop_params: dict[str, str] = {"systemName": system, "showInformation": "1"}
        pop_r = get(
            EDSM_SYSTEM_URL,
            params=pop_params,
            timeout=timeout,
            headers=headers,
        )
        pop = 0
        if pop_r.ok:
            info = pop_r.json().get("information") or {}
            pop = int(info.get("population") or 0)
        return {"population": pop, "factions": data.get("factions") or []}
    except Exception as e:
        logger.warning("EDSM fetch failed: %s", e)
        return {"population": 0, "factions": []}


def apply_edsm_system_data(
    tracker: TrackerState,
    system: str,
    data: dict[str, Any],
) -> None:
    """Merge an EDSM system payload into tracker (population + tracked faction INF)."""
    tracker.system = system
    tracker.population = int(data.get("population") or 0) or tracker.population
    for f in data.get("factions") or []:
        if not isinstance(f, dict):
            continue
        # EDSM uses lowercase "name" / "influence"
        if f.get("name") == tracker.faction:
            tracker.current_influence = float(f.get("influence") or 0)
