# overlay_client.py
from __future__ import annotations

from contextlib import suppress
from typing import Any

try:
    from EDMCOverlay import edmcoverlay
except ImportError:
    try:
        from edmcoverlay import edmcoverlay
    except ImportError:
        edmcoverlay = None


class OverlayClient:
    def __init__(self) -> None:
        self._client: Any = None
        if edmcoverlay is not None:
            with suppress(Exception):
                self._client = edmcoverlay.Overlay()

    @property
    def available(self) -> bool:
        return self._client is not None

    def send(
        self,
        msgid: str,
        text: str,
        color: str = "#00ff88",
        size: str = "normal",
        x: int = 20,
        y: int = 180,
        ttl: int = 8,
    ) -> None:
        if not self._client:
            return
        with suppress(Exception):
            self._client.send_message(
                msgid=msgid, text=text, color=color, size=size, x=x, y=y, ttl=ttl
            )
