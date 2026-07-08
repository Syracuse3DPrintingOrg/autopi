"""Wi-Fi status, scan, and connect, relayed to the host-bridge.

Every route is a clean no-op on a plain server (no bridge, no Wi-Fi radio to
manage): the operating system owns networking there. On a Raspberry Pi
appliance these forward to the host-bridge at 127.0.0.1:9299, which runs
nmcli (or a wpa_cli fallback) as root.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..services import bridge

router = APIRouter(prefix="/network", tags=["network"])

# Wi-Fi control runs through the host-bridge (which does the nmcli as root on
# the host). The right gate is therefore "is the bridge reachable?", not
# "can the container see Pi hardware?" (it usually cannot). This message is
# returned when no bridge answers.
_NO_BRIDGE = ("The host-bridge is not reachable. Wi-Fi control runs through the "
              "AutoPi host-bridge on a Raspberry Pi appliance; make sure the "
              "device has been updated and the bridge is running.")


@router.get("/status")
def network_status():
    """Current SSID (if any), IP address, and hostname."""
    if not bridge.available():
        return {"ok": False, "error": _NO_BRIDGE, "ssid": None, "ip": None, "hostname": None}
    return bridge.call("GET", "/network/status", timeout=8)


@router.post("/wifi/scan")
def network_scan():
    """Visible Wi-Fi networks, strongest signal first."""
    if not bridge.available():
        return {"ok": False, "error": _NO_BRIDGE}
    return bridge.call("POST", "/network/wifi/scan", timeout=20)


@router.post("/wifi/connect")
async def network_connect(request: Request):
    """Join a Wi-Fi network by SSID, with an optional passphrase."""
    if not bridge.available():
        return {"ok": False, "error": _NO_BRIDGE}
    body = await request.json()
    if not isinstance(body, dict):
        return {"ok": False, "error": "expected a JSON object"}
    ssid = str(body.get("ssid") or "").strip()
    psk = str(body.get("psk") or "")
    if not ssid:
        return {"ok": False, "error": "ssid is required"}
    return bridge.call("POST", "/network/wifi/connect", timeout=30, json={"ssid": ssid, "psk": psk})
