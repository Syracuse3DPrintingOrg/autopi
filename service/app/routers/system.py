"""Host operations, relayed to the host-bridge. No-ops on a plain server."""
from __future__ import annotations

from fastapi import APIRouter

from ..services import bridge

router = APIRouter(prefix="/system", tags=["system"])


def _not_on_this_platform():
    return {"ok": False, "error": "Only available on a Raspberry Pi appliance."}


@router.get("/health")
def system_health():
    """Decoded Pi power/thermal/disk health (from the bridge)."""
    if not bridge.is_raspberry_pi():
        return {"ok": False, "error": "Not a Raspberry Pi."}
    raw = bridge.call("GET", "/system/health", timeout=8)
    if raw.get("error"):
        return {"ok": False, "error": raw["error"]}
    return {"ok": True, **bridge.health_summary(raw)}


@router.get("/bridge")
def bridge_status():
    """Whether a host-bridge is reachable (drives the Updates UI)."""
    return {"pi": bridge.is_raspberry_pi(), "bridge": bridge.available()}


@router.post("/update")
def system_update():
    if not bridge.is_raspberry_pi():
        return _not_on_this_platform()
    # The OTA can take a while (image build); give it room.
    return bridge.call("POST", "/update", timeout=1800)


@router.post("/reboot")
def system_reboot():
    if not bridge.is_raspberry_pi():
        return _not_on_this_platform()
    return bridge.call("POST", "/reboot", timeout=10)
