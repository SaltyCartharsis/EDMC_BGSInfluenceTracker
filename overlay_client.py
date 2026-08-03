# overlay_client.py
try:
    from EDMCOverlay import edmcoverlay
except ImportError:
    try:
        from edmcoverlay import edmcoverlay
    except ImportError:
        edmcoverlay = None

class OverlayClient:
    def __init__(self):
        self._client = None
        if edmcoverlay is not None:
            try:
                self._client = edmcoverlay.Overlay()
            except Exception:
                self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def send(self, msgid: str, text: str, color: str = "#00ff88",
             size: str = "normal", x: int = 20, y: int = 180, ttl: int = 8):
        if not self._client:
            return
        try:
            self._client.send_message(msgid=msgid, text=text, color=color,
                                      size=size, x=x, y=y, ttl=ttl)
        except Exception:
            pass