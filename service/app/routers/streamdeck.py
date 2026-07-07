"""Stream Deck status and control.

The controller process (which owns the USB device) POSTs its live status here so
the editor can scale the grid to the real deck and show a connected badge. It
also GETs this endpoint each poll to pull the desired rotation and brightness
(set in the web editor) and to see a restart request, so config changes take
effect live and a restart needs no host privileges.

The app runs in a container and cannot restart the host systemd service
directly, so "restart" is a flag the controller reads: it exits on request and
systemd relaunches it. When no controller is running, the flag simply waits.
"""
from __future__ import annotations

import time

from fastapi import APIRouter
from pydantic import BaseModel

from ..config import settings
from ..services import deck_layout
from ..services.state import StateFile

router = APIRouter(prefix="/streamdeck", tags=["streamdeck"])

# A live report is considered current for this many seconds after it arrives.
_FRESH_SECONDS = 30


def _store() -> StateFile:
    return StateFile(settings.data_dir / "streamdeck-status.json",
                     default={"connected": False, "key_count": 0, "ts": 0, "restart_ts": 0})


class StatusIn(BaseModel):
    connected: bool = False
    key_count: int = 0
    deck_type: str = ""


@router.post("/status")
def report_status(body: StatusIn):
    """Called by the controller to publish that a deck is (or is not) attached."""
    store = _store()
    doc = store.read()
    doc.update({"connected": bool(body.connected), "key_count": int(body.key_count),
                "deck_type": body.deck_type, "ts": time.time()})
    store.write(doc)
    return {"ok": True}


@router.get("/status")
def get_status():
    """Resolve the grid the editor should draw and the settings the controller
    should apply: the live deck if one reported recently, otherwise the model."""
    doc = _store().read()
    live = bool(doc.get("connected")) and (time.time() - doc.get("ts", 0)) < _FRESH_SECONDS
    model = settings.deck_model if settings.deck_model in deck_layout.GRID else 15
    key_count = int(doc.get("key_count") or 0) if live else model
    if key_count not in deck_layout.GRID:
        key_count = model
    return {
        "connected": live,
        "deck_type": doc.get("deck_type", "") if live else "",
        "key_count": key_count,
        "model": model,
        "rotation": settings.deck_rotation,
        "brightness": settings.deck_brightness,
        "enabled": settings.streamdeck_enabled,
        "supported": list(deck_layout.supported_key_counts()),
        "restart_ts": doc.get("restart_ts", 0),
    }


@router.post("/restart")
def restart_controller():
    """Ask the controller to reconnect. It reads this flag on its next poll and
    exits so systemd relaunches it, which re-applies rotation and repaints."""
    store = _store()
    doc = store.read()
    doc["restart_ts"] = time.time()
    store.write(doc)
    live = bool(doc.get("connected")) and (time.time() - doc.get("ts", 0)) < _FRESH_SECONDS
    if live:
        return {"ok": True, "message": "Reconnecting the Stream Deck…"}
    return {"ok": True, "message": "Restart requested; it applies when the deck controller is running"}
