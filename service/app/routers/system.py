"""Host operations, relayed to the host-bridge. No-ops on a plain server."""
from __future__ import annotations

from fastapi import APIRouter

from ..services import bridge

router = APIRouter(prefix="/system", tags=["system"])


# These host operations run through the host-bridge, so the gate is whether the
# bridge answers, not whether the container can see Pi hardware (it usually
# cannot). The bridge only runs on a Pi appliance.
_NO_BRIDGE = {"ok": False, "error": "The host-bridge is not reachable (this runs "
              "on a Raspberry Pi appliance with the AutoPi host-bridge)."}


@router.get("/health")
def system_health():
    """Decoded Pi power/thermal/disk health (from the bridge)."""
    if not bridge.available():
        return _NO_BRIDGE
    raw = bridge.call("GET", "/system/health", timeout=8)
    if raw.get("error"):
        return {"ok": False, "error": raw["error"]}
    return {"ok": True, **bridge.health_summary(raw)}


@router.get("/bridge")
def bridge_status():
    """Host-bridge reachability and version, so the UI can flag a stale bridge."""
    h = bridge.health_check()
    is_stale = bridge.stale()
    return {
        "pi": bridge.is_raspberry_pi(),
        "bridge": bool(h),
        "version": h.get("version"),
        "expected": bridge.EXPECTED_BRIDGE_VERSION,
        "stale": is_stale,
        "restart_hint": "sudo systemctl restart autopi-host-bridge" if is_stale else None,
    }


@router.post("/update")
def system_update():
    if not bridge.available():
        return _NO_BRIDGE
    # The OTA can take a while (image build); give it room.
    return bridge.call("POST", "/update", timeout=1800)


@router.post("/reboot")
def system_reboot():
    if not bridge.available():
        return _NO_BRIDGE
    return bridge.call("POST", "/reboot", timeout=10)
