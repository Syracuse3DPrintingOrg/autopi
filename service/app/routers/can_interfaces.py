"""CAN interface configuration: which backend and settings a channel uses.

``GET /can/interfaces`` (in ``can_dbc.py``) reports live availability for
the two default channel names. This router is the config CRUD behind the
"CAN interfaces" settings pane, kept at a distinct path
(``/can/interfaces/config``) so it never collides with that route.

Bringing a SocketCAN interface up or down needs root (``ip link set``), which
a container does not have, so those calls relay to the host-bridge the same
way Wi-Fi control does (see ``routers/network.py``): a clean, honest failure
message when no bridge answers (off a Pi, or before the device is set up),
never a claimed success.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..can.linkstate import classify_health, parse_link_show
from ..can.registry import list_backends
from ..services import bridge, can_interfaces

router = APIRouter(prefix="/can/interfaces", tags=["can-interfaces"])

# Bringing an interface up or down (and reading its live state) only makes
# sense for a real SocketCAN device; other backends have no kernel link to
# manage this way.
_LINK_BACKENDS = {"socketcan"}

_NO_BRIDGE = ("The host-bridge is not reachable, so AutoPi cannot bring this interface "
              "up itself. Run this on the device instead: ")


def _manual_up_command(entry: dict) -> str:
    cmd = f"sudo ip link set {entry['channel']} down; " \
          f"sudo ip link set {entry['channel']} type can bitrate {entry['bitrate']}"
    if entry.get("sample_point"):
        cmd += f" sample-point {entry['sample_point']}"
    if entry.get("fd"):
        cmd += f" dbitrate {entry.get('data_bitrate') or entry['bitrate']} fd on"
        if entry.get("data_sample_point"):
            cmd += f" dsample-point {entry['data_sample_point']}"
    cmd += f"; sudo ip link set {entry['channel']} up"
    return cmd


class InterfaceIn(BaseModel):
    id: str
    backend: str = "socketcan"
    channel: str = ""
    bitrate: int = can_interfaces.DEFAULT_BITRATE
    fd: bool = False
    data_bitrate: int | None = None
    sample_point: float | None = None
    data_sample_point: float | None = None
    purpose: str = ""
    label: str = ""


@router.get("/backends")
def get_backends():
    return {"backends": list_backends()}


@router.get("/detected")
def detected_interfaces():
    """The CAN interfaces that actually exist on this device, so a user can see
    which channel names to use (and what each one is) instead of guessing."""
    from ..can.detect import list_can_interfaces
    return {"interfaces": list_can_interfaces()}


def _with_display_label(entry: dict) -> dict:
    return {**entry, "purpose_label": can_interfaces.display_label(entry)}


@router.get("/config")
def get_config():
    return {"interfaces": [_with_display_label(i) for i in can_interfaces.list_interfaces()]}


@router.post("/config")
def save_config(body: InterfaceIn):
    if not body.id.strip():
        raise HTTPException(400, "An interface id (the channel name) is required")
    entry = can_interfaces.save_interface(body.model_dump())
    return {"ok": True, "interface": _with_display_label(entry)}


@router.delete("/config/{interface_id}")
def delete_config(interface_id: str):
    if not can_interfaces.delete_interface(interface_id):
        raise HTTPException(404, "No such configured interface")
    return {"ok": True}


@router.get("/config/{interface_id}/status")
def config_status(interface_id: str):
    """Open (or reuse) the provider for a configured interface and report
    whether it is actually available on this host, without sending anything."""
    entry = can_interfaces.get_interface(interface_id)
    if entry is None:
        raise HTTPException(404, "No such configured interface")
    from ..can import get_channel

    kwargs = {"bitrate": entry["bitrate"], "fd": entry["fd"]}
    if entry.get("data_bitrate"):
        kwargs["data_bitrate"] = entry["data_bitrate"]
    provider = get_channel(entry["channel"], backend=entry["backend"], **kwargs)
    available = provider.available
    return {"id": entry["id"], "available": available,
            "error": None if available else getattr(provider, "last_error", None)}


def _require_link_backed(interface_id: str) -> dict:
    entry = can_interfaces.get_interface(interface_id)
    if entry is None:
        raise HTTPException(404, "No such configured interface")
    if entry["backend"] not in _LINK_BACKENDS:
        raise HTTPException(400, f"'{entry['backend']}' interfaces have no kernel link to bring up or down")
    return entry


@router.post("/config/{interface_id}/up")
def bring_up(interface_id: str):
    """Bring the interface's kernel link up at its configured bitrate."""
    entry = _require_link_backed(interface_id)
    if not bridge.available():
        return {"ok": False, "error": _NO_BRIDGE + _manual_up_command(entry)}
    body = {"interface": entry["channel"], "bitrate": entry["bitrate"], "fd": entry["fd"]}
    if entry.get("data_bitrate"):
        body["data_bitrate"] = entry["data_bitrate"]
    if entry.get("sample_point"):
        body["sample_point"] = entry["sample_point"]
    if entry.get("data_sample_point"):
        body["data_sample_point"] = entry["data_sample_point"]
    result = bridge.call("POST", "/can/up", timeout=15, json=body)
    if result.get("link") is not None:
        result["state"] = parse_link_show(result["link"])
    return result


@router.post("/config/{interface_id}/down")
def bring_down(interface_id: str):
    """Bring the interface's kernel link down."""
    entry = _require_link_backed(interface_id)
    if not bridge.available():
        return {"ok": False,
                "error": _NO_BRIDGE + f"sudo ip link set {entry['channel']} down"}
    result = bridge.call("POST", "/can/down", timeout=10, json={"interface": entry["channel"]})
    if result.get("link") is not None:
        result["state"] = parse_link_show(result["link"])
    return result


@router.get("/config/{interface_id}/link-status")
def link_status(interface_id: str):
    """Live kernel link state (up/down, bitrate, bus state, error counters)."""
    entry = _require_link_backed(interface_id)
    if not bridge.available():
        return {"ok": False, "error": _NO_BRIDGE + f"ip -details link show {entry['channel']}"}
    result = bridge.call("POST", "/can/status", timeout=8, json={"interface": entry["channel"]})
    if not result.get("ok"):
        return result
    return {"ok": True, "state": parse_link_show(result.get("link"))}


@router.get("/config/{interface_id}/errors")
def error_counters(interface_id: str):
    """Live CAN error counters (error-warn/error-pass/bus-off, and restarts),
    so the UI can show whether errors are still climbing while tuning timing."""
    entry = _require_link_backed(interface_id)
    if not bridge.available():
        return {"ok": False, "error": _NO_BRIDGE + f"ip -s -d link show {entry['channel']}"}
    result = bridge.call("POST", "/can/stats", timeout=8, json={"interface": entry["channel"]})
    if not result.get("ok"):
        return result
    from ..can.linkstate import parse_can_stats
    return {"ok": True, "counters": parse_can_stats(result.get("text") or "")}


@router.get("/config/{interface_id}/health")
def health(interface_id: str):
    """Bus health read (error-active/warning/passive/bus-off) for the UI."""
    entry = _require_link_backed(interface_id)
    if not bridge.available():
        return {"ok": False, "error": _NO_BRIDGE + f"ip -details link show {entry['channel']}"}
    result = bridge.call("POST", "/can/status", timeout=8, json={"interface": entry["channel"]})
    if not result.get("ok"):
        return result
    state = parse_link_show(result.get("link"))
    return {"ok": True, "state": state, "health": classify_health(state)}


@router.post("/config/{interface_id}/send-test-frame")
def send_test_frame(interface_id: str):
    """Send the fixed CAN self-test frame on this channel, so a scope or a
    second node can confirm traffic is actually going out."""
    entry = can_interfaces.get_interface(interface_id)
    if entry is None:
        raise HTTPException(404, "No such configured interface")
    from ..can import get_channel
    from ..can.selftest import build_test_frame

    kwargs = {"bitrate": entry["bitrate"], "fd": entry["fd"]}
    if entry.get("data_bitrate"):
        kwargs["data_bitrate"] = entry["data_bitrate"]
    provider = get_channel(entry["channel"], backend=entry["backend"], **kwargs)
    if not provider.available:
        return {"ok": False, "error": "Interface is not available. Bring it up first."}
    frame = build_test_frame(is_fd=entry["fd"])
    if provider.send(frame):
        return {"ok": True, "message": f"Sent {frame.format()} on {entry['channel']}"}
    return {"ok": False, "error": f"Send failed on {entry['channel']}"}


@router.post("/config/{interface_id}/sniff")
def sniff(interface_id: str, seconds: float = 3.0):
    """Listen on this channel for a few seconds and report how many frames
    arrived and which arbitration ids were seen. This is the quickest way to
    tell whether a bus is actually streaming (0 frames means nothing is
    reaching this interface, even when it is up and self-tests fine)."""
    import time

    entry = can_interfaces.get_interface(interface_id)
    if entry is None:
        raise HTTPException(404, "No such configured interface")
    from ..can import open_channel

    kwargs = {"bitrate": entry["bitrate"], "fd": entry["fd"]}
    if entry.get("data_bitrate"):
        kwargs["data_bitrate"] = entry["data_bitrate"]
    # A dedicated socket, so a short listen never competes with the live Monitor
    # over one shared socket and never inherits a socket left stale by a down/up.
    provider = open_channel(entry["channel"], backend=entry["backend"], **kwargs)
    if not provider.available:
        try:
            provider.close()
        except Exception:
            pass
        return {"ok": False, "error": getattr(provider, "last_error", None)
                or "Interface is not available. Bring it up first."}
    seconds = max(0.5, min(float(seconds), 10.0))
    deadline = time.monotonic() + seconds
    count = 0
    ids: dict[str, int] = {}
    samples: list[str] = []
    try:
        while time.monotonic() < deadline:
            frame = provider.recv(timeout=0.3)
            if frame is None:
                continue
            count += 1
            key = hex(frame.arbitration_id)
            ids[key] = ids.get(key, 0) + 1
            if len(samples) < 8:
                samples.append(frame.format())
    finally:
        try:
            provider.close()
        except Exception:
            pass
    return {"ok": True, "channel": entry["channel"], "seconds": seconds,
            "frames": count, "unique_ids": len(ids),
            "ids": sorted(ids.keys())[:32], "samples": samples}


@router.post("/config/{interface_id}/self-test")
def self_test(interface_id: str):
    """Loopback self-test: send the test frame and confirm it comes back.

    Opens a dedicated provider with self-reception on (see
    ``can.selftest``), independent of the cached channel used for normal
    sends, so this never disturbs a monitor or simulation already running on
    the same channel.
    """
    entry = can_interfaces.get_interface(interface_id)
    if entry is None:
        raise HTTPException(404, "No such configured interface")
    from ..can.registry import create_provider
    from ..can.selftest import run_loopback_test

    kwargs = {"bitrate": entry["bitrate"], "fd": entry["fd"], "receive_own_messages": True}
    if entry.get("data_bitrate"):
        kwargs["data_bitrate"] = entry["data_bitrate"]
    provider = create_provider(entry["backend"], entry["channel"], **kwargs)
    try:
        return run_loopback_test(provider)
    finally:
        provider.close()
