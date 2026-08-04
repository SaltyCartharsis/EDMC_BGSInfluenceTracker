"""Unit tests for optional EDMC Overlay adapter."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import overlay_client
from overlay_client import OverlayClient


def test_unavailable_when_no_backend(monkeypatch: Any) -> None:
    monkeypatch.setattr(overlay_client, "edmcoverlay", None)
    client = OverlayClient()
    assert client.available is False
    # No-op; must not raise
    client.send("id", "hello")


def test_available_when_overlay_constructs(monkeypatch: Any) -> None:
    mock_overlay = MagicMock()
    mock_mod = SimpleNamespace(Overlay=MagicMock(return_value=mock_overlay))
    monkeypatch.setattr(overlay_client, "edmcoverlay", mock_mod)

    client = OverlayClient()
    assert client.available is True
    client.send(
        "bgsinf",
        "hello",
        color="#ff0000",
        size="large",
        x=10,
        y=20,
        ttl=5,
    )
    mock_overlay.send_message.assert_called_once_with(
        msgid="bgsinf",
        text="hello",
        color="#ff0000",
        size="large",
        x=10,
        y=20,
        ttl=5,
    )


def test_constructor_exception_marks_unavailable(monkeypatch: Any) -> None:
    mock_mod = SimpleNamespace(Overlay=MagicMock(side_effect=RuntimeError("no display")))
    monkeypatch.setattr(overlay_client, "edmcoverlay", mock_mod)
    client = OverlayClient()
    assert client.available is False


def test_send_swallows_client_errors(monkeypatch: Any) -> None:
    mock_overlay = MagicMock()
    mock_overlay.send_message.side_effect = OSError("broken pipe")
    mock_mod = SimpleNamespace(Overlay=MagicMock(return_value=mock_overlay))
    monkeypatch.setattr(overlay_client, "edmcoverlay", mock_mod)

    client = OverlayClient()
    assert client.available is True
    client.send("id", "msg")  # must not raise
