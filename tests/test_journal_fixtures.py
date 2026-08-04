"""Sanity checks for journal fixtures (shapes aligned with Journal Manual v32)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "journal"


@pytest.mark.parametrize(
    ("name", "event"),
    [
        ("fsd_jump.json", "FSDJump"),
        ("location.json", "Location"),
        ("carrier_jump.json", "CarrierJump"),
        ("mission_completed.json", "MissionCompleted"),
        ("mission_completed_manual.json", "MissionCompleted"),
        ("bounty_kill.json", "Bounty"),
        ("bounty_kill_multi.json", "Bounty"),
        ("bounty_skimmer.json", "Bounty"),
        ("redeem_voucher.json", "RedeemVoucher"),
        ("redeem_voucher_legacy.json", "RedeemVoucher"),
        ("redeem_voucher_bond.json", "RedeemVoucher"),
        ("redeem_voucher_with_perk.json", "RedeemVoucher"),
        ("sell_exploration_data.json", "SellExplorationData"),
        ("multi_sell_exploration_data.json", "MultiSellExplorationData"),
    ],
)
def test_journal_fixture_loads(name: str, event: str) -> None:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert data["event"] == event
    assert "timestamp" in data


def test_mission_manual_fixture_has_faction_effects() -> None:
    data = json.loads((FIXTURES / "mission_completed_manual.json").read_text(encoding="utf-8"))
    effects = data["FactionEffects"]
    assert len(effects) == 2
    assert effects[0]["Influence"][0]["Influence"] == "++++"


def test_redeem_modern_has_factions_array() -> None:
    data = json.loads((FIXTURES / "redeem_voucher.json").read_text(encoding="utf-8"))
    assert data["Type"] == "bounty"
    assert isinstance(data["Factions"], list)
