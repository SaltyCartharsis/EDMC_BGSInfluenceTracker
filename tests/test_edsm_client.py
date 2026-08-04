"""Mocked unit tests for EDSM client (never hits the network)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from bgsinf.edsm_client import (
    EDSM_FACTIONS_URL,
    EDSM_SYSTEM_URL,
    apply_edsm_system_data,
    fetch_edsm_system,
)
from bgsinf.influence_model import TrackerState

UA = "TestAgent/1.0"


def _resp(json_data: dict[str, Any], *, ok: bool = True, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.ok = ok
    r.status_code = status
    r.json.return_value = json_data
    if ok and status < 400:
        r.raise_for_status.return_value = None
    else:
        r.raise_for_status.side_effect = Exception(f"HTTP {status}")
    return r


def test_fetch_edsm_system_happy_path() -> None:
    factions_body = {
        "factions": [
            {"name": "Mother Gaia", "influence": 0.312},
            {"name": "Other", "influence": 0.1},
        ]
    }
    system_body = {"information": {"population": 12_345_678}}

    calls: list[str] = []

    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        calls.append(url)
        assert kwargs["headers"] == {"User-Agent": UA}
        assert kwargs["params"]["systemName"] == "Sol"
        assert kwargs["timeout"] == 8.0
        if url == EDSM_FACTIONS_URL:
            return _resp(factions_body)
        if url == EDSM_SYSTEM_URL:
            assert kwargs["params"].get("showInformation") in (1, "1")
            return _resp(system_body)
        raise AssertionError(f"unexpected url {url}")

    data = fetch_edsm_system("Sol", user_agent=UA, http_get=fake_get)
    assert data["population"] == 12_345_678
    assert data["factions"] == factions_body["factions"]
    assert calls == [EDSM_FACTIONS_URL, EDSM_SYSTEM_URL]


def test_fetch_edsm_system_population_request_not_ok() -> None:
    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        if url == EDSM_FACTIONS_URL:
            return _resp({"factions": [{"name": "A", "influence": 0.5}]})
        # population endpoint soft-fails → pop stays 0
        return _resp({}, ok=False, status=500)

    data = fetch_edsm_system("X", user_agent=UA, http_get=fake_get)
    assert data["population"] == 0
    assert data["factions"] == [{"name": "A", "influence": 0.5}]


def test_fetch_edsm_system_missing_factions_key() -> None:
    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        if url == EDSM_FACTIONS_URL:
            return _resp({})  # no factions key
        return _resp({"information": {}})

    data = fetch_edsm_system("Empty", user_agent=UA, http_get=fake_get)
    assert data == {"population": 0, "factions": []}


def test_fetch_edsm_system_http_error_returns_empty() -> None:
    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        return _resp({}, ok=False, status=503)

    data = fetch_edsm_system("Sol", user_agent=UA, http_get=fake_get)
    assert data == {"population": 0, "factions": []}


def test_fetch_edsm_system_timeout_returns_empty() -> None:
    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        raise TimeoutError("timed out")

    data = fetch_edsm_system("Sol", user_agent=UA, http_get=fake_get)
    assert data == {"population": 0, "factions": []}


def test_fetch_edsm_system_null_population_treated_as_zero() -> None:
    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        if url == EDSM_FACTIONS_URL:
            return _resp({"factions": []})
        return _resp({"information": {"population": None}})

    data = fetch_edsm_system("Sol", user_agent=UA, http_get=fake_get)
    assert data["population"] == 0


# ---------------------------------------------------------------------------
# apply_edsm_system_data
# ---------------------------------------------------------------------------


def test_apply_edsm_updates_tracked_faction() -> None:
    tracker = TrackerState(
        system="Old",
        faction="Mother Gaia",
        population=1000,
        current_influence=0.1,
    )
    apply_edsm_system_data(
        tracker,
        "Sol",
        {
            "population": 99_000_000,
            "factions": [
                {"name": "Other", "influence": 0.2},
                {"name": "Mother Gaia", "influence": 0.45},
            ],
        },
    )
    assert tracker.system == "Sol"
    assert tracker.population == 99_000_000
    assert tracker.current_influence == pytest.approx(0.45)


def test_apply_edsm_zero_population_keeps_existing() -> None:
    tracker = TrackerState(system="Sol", faction="X", population=5_000)
    apply_edsm_system_data(tracker, "Sol", {"population": 0, "factions": []})
    assert tracker.population == 5_000


def test_apply_edsm_skips_malformed_faction_rows() -> None:
    tracker = TrackerState(faction="Mother Gaia", current_influence=0.0)
    apply_edsm_system_data(
        tracker,
        "Sol",
        {
            "population": 10,
            "factions": ["bad", {"name": "Mother Gaia", "influence": 0.33}],
        },
    )
    assert tracker.current_influence == pytest.approx(0.33)
