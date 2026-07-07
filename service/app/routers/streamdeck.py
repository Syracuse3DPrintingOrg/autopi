"""Stream Deck status and control.

The controller process (which owns the USB device) POSTs its live status here so
the editor can scale the grid to the real deck and show a connected badge. When
no controller has reported recently, the editor falls back to the selected deck
model. ``restart`` best-effort bounces the systemd service on a Pi appliance.
"""
from __future__ import annotations

import subprocess
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
                     default={"connected": False, "key_count": 0, "ts": 0})


class StatusIn(BaseModel):
    connected: bool = False
    key_count: int = 0
    deck_type: str = ""


@router.post("/status")
def report_status(body: StatusIn):
    """Called by the controller to publish that a deck is (or is not) attached."""
    _store().write({"connected": bool(body.connected), "key_count": int(body.key_count),
                    "deck_type": body.deck_type, "ts": time.time()})
    return {"ok": True}


@router.get("/status")
def get_status():
    """Resolve the grid the editor should draw: the live deck if one reported
    recently, otherwise the configured model."""
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
    }


@router.post("/restart")
def restart_service():
    """Bounce the controller service (Pi appliance). No-op elsewhere."""
    try:
        subprocess.run(["systemctl", "restart", "autopi-streamdeck.service"],
                       capture_output=True, timeout=10, check=True)
        return {"ok": True, "message": "Stream Deck service restarted"}
    except (FileNotFoundError, subprocess.SubprocessError):
        return {"ok": False, "message": "No Stream Deck service on this host"}
