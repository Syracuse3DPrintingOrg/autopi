"""Client for the host-bridge (the root helper at 127.0.0.1:9299).

The app is unprivileged and containerized, so it cannot reboot the host, restart
a systemd unit, or read Pi throttle state. It relays those to the host-bridge,
which the appliance compose lets it reach over loopback (network_mode: host).

The bridge writes a shared token into the app's data dir (a bind mount); this
client sends it back as X-Bridge-Token, caches it after the first read, does not
cache a miss (so first boot picks it up as soon as the bridge writes it), and
drops the cache on a 401 so a rotated token is re-read. Every relay is a clean
no-op on a plain server, guarded by is_raspberry_pi().
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from ..config import settings

BRIDGE_URL = "http://127.0.0.1:9299"
_token_cache: dict[str, str | None] = {"value": None}


def is_raspberry_pi() -> bool:
    """Best-effort Pi detection that also works from inside the container.

    The device-tree model files are not always visible in a container, so
    /proc/cpuinfo (the host's, since the kernel is shared) is checked too. Note
    this is only a hint: the authoritative capability check for host operations
    is whether the host-bridge answers (``available()``), because the bridge is
    what actually performs them and only runs on a Pi appliance.
    """
    for p in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model", "/proc/cpuinfo"):
        try:
            if "raspberry pi" in Path(p).read_text(errors="ignore").lower():
                return True
        except OSError:
            continue
    return False


def _token() -> str:
    if _token_cache["value"] is not None:
        return _token_cache["value"]
    try:
        tok = (settings.data_dir / "bridge-token").read_text().strip()
    except OSError:
        return ""  # do not cache a miss; the bridge may not have written it yet
    _token_cache["value"] = tok
    return tok


def available() -> bool:
    """Is a host-bridge answering right now?"""
    try:
        return httpx.get(f"{BRIDGE_URL}/health", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def call(method: str, path: str, timeout: float = 30.0, json: Any = None) -> dict:
    """Relay a request to the bridge, attaching the token. Never raises."""
    headers = {}
    tok = _token()
    if tok:
        headers["X-Bridge-Token"] = tok
    try:
        r = httpx.request(method, f"{BRIDGE_URL}{path}", headers=headers, timeout=timeout, json=json)
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"host-bridge unreachable: {exc}"}
    if r.status_code == 401:
        _token_cache["value"] = None  # rotated token; re-read next call
    if r.status_code == 404:
        # The bridge answered but does not know this route, which almost always
        # means an older bridge is still running (the update replaced the file
        # but the process was not restarted). Give an actionable message.
        return {"ok": False, "stale_bridge": True,
                "error": "The host-bridge is out of date (it does not have this "
                         "feature yet). Restart it on the device: "
                         "sudo systemctl restart autopi-host-bridge"}
    try:
        return r.json()
    except ValueError:
        return {"ok": r.status_code < 400, "detail": r.text[:500]}


# --- pure decode of the Pi throttle bitmask (testable, no hardware) ----------
_FLAG_BITS = {
    "under_voltage_now": 0x1,
    "freq_capped_now": 0x2,
    "throttled_now": 0x4,
    "soft_temp_now": 0x8,
    "under_voltage_since_boot": 0x10000,
    "freq_capped_since_boot": 0x20000,
    "throttled_since_boot": 0x40000,
    "soft_temp_since_boot": 0x80000,
}


def decode_throttled(bits: int | None) -> dict:
    """Decode `vcgencmd get_throttled` into flags and human warnings."""
    if bits is None:
        return {"flags": {}, "warnings": []}
    flags = {name: bool(bits & mask) for name, mask in _FLAG_BITS.items()}
    warnings = []
    if flags["under_voltage_now"] or flags["under_voltage_since_boot"]:
        warnings.append("Under-voltage detected: check the power supply and cable.")
    if flags["throttled_now"] or flags["throttled_since_boot"]:
        warnings.append("The CPU has been throttled.")
    if flags["soft_temp_now"] or flags["soft_temp_since_boot"]:
        warnings.append("The CPU hit the soft temperature limit.")
    return {"flags": flags, "warnings": warnings}


def health_summary(raw: dict) -> dict:
    """Turn the bridge's raw health read into a decoded, user-facing summary."""
    out = decode_throttled(raw.get("throttled"))
    temp = raw.get("temp_c")
    disk = raw.get("disk_percent")
    out["temp_c"] = temp
    out["disk_percent"] = disk
    if isinstance(temp, (int, float)) and temp >= 80:
        out["warnings"].append(f"CPU temperature is high ({temp}C).")
    if isinstance(disk, (int, float)) and disk >= 90:
        out["warnings"].append(f"Disk is {disk}% full.")
    return out
