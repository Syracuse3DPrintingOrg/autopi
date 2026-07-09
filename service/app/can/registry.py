"""Provider registry: open a CAN channel by backend name.

``socketcan`` (the Waveshare 2-Ch CAN-FD HAT, and every other Linux CAN
adapter) is the default. ``pcan`` (PEAK PCAN-USB), ``vector`` (Vector
Informatik interfaces), and ``virtual`` (an in-process loopback bus for
testing without hardware) wrap the matching python-can backend the same
way. ``lin`` and ``doip`` are registered as NOT-YET-IMPLEMENTED stubs (see
``lin.py`` and ``doip.py``) so the extension point is visible in code.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import CanProvider

# The kernel's CAN-FD frame MTU. A link brought up "fd on" has MTU 72; a classic
# CAN link has MTU 16. A classic SocketCAN socket never receives a bus's FD
# frames, so we must open FD sockets on an FD link even when the app has no saved
# interface config for it.
_CANFD_MTU = 72
from .doip import DoipProvider
from .lin import LinProvider
from .pcan import PcanProvider
from .socketcan import SocketCanProvider
from .vector import VectorProvider
from .virtual import VirtualProvider

# backend name -> provider class.
PROVIDER_CLASSES: dict[str, type[CanProvider]] = {
    "socketcan": SocketCanProvider,
    "pcan": PcanProvider,
    "vector": VectorProvider,
    "virtual": VirtualProvider,
    "lin": LinProvider,
    "doip": DoipProvider,
}

# Backends a device can actually be configured with today. lin/doip are
# registered above (so create_provider/get_channel resolve them) but left
# out of the configurable list since they always report unavailable.
CONFIGURABLE_BACKENDS = ("socketcan", "pcan", "vector", "virtual")

# One provider instance per (backend, channel), so repeated sends reuse the
# same open bus instead of reopening it every time, mirroring how the GPIO
# driver caches one device per pin.
_channels: dict[str, CanProvider] = {}


def register_provider(backend: str, cls: type[CanProvider]) -> None:
    PROVIDER_CLASSES[backend] = cls


def list_backends() -> list[dict[str, Any]]:
    """Describe every configurable backend, for the settings UI."""
    labels = {
        "socketcan": "SocketCAN (Linux CAN interface, e.g. the Waveshare HAT)",
        "pcan": "PEAK PCAN-USB",
        "vector": "Vector (VN1610, VN1630, and similar)",
        "virtual": "Virtual (loopback, no hardware needed)",
    }
    return [{"backend": b, "label": labels.get(b, b)} for b in CONFIGURABLE_BACKENDS]


def create_provider(backend: str, channel: str, **kwargs: Any) -> CanProvider:
    """Instantiate a fresh provider for the given backend (default socketcan
    if the name is not recognized, since that covers every Linux CAN HAT)."""
    cls = PROVIDER_CLASSES.get(backend, SocketCanProvider)
    return cls(channel, **kwargs)


def _link_is_fd(channel: str, sysfs_root: str = "/sys/class/net") -> bool:
    """Whether a live SocketCAN link is up in CAN-FD mode, read from its MTU.
    Lets a bus brought up in FD mode outside the app (the boot bring-up service,
    or a manual ``ip link``) still be opened in FD mode, so a capture on it is
    not a silent classic socket that receives nothing."""
    try:
        mtu = int(Path(f"{sysfs_root}/{channel}/mtu").read_text().strip())
    except (OSError, ValueError):
        return False
    return mtu >= _CANFD_MTU


def link_stats(channel: str, sysfs_root: str = "/sys/class/net") -> dict[str, Any]:
    """Best-effort SocketCAN link diagnostics from sysfs: whether the interface
    is present and up, its MTU (72 means CAN-FD), and the kernel rx_packets
    counter. Used to explain why a live capture came back empty (idle port vs a
    port that is receiving frames the socket did not read). ``{}`` when the
    interface is not a sysfs device."""
    base = Path(f"{sysfs_root}/{channel}")
    if not base.exists():
        return {}

    def _int(rel: str) -> int | None:
        try:
            return int((base / rel).read_text().strip())
        except (OSError, ValueError):
            return None

    def _str(rel: str) -> str | None:
        try:
            return (base / rel).read_text().strip()
        except OSError:
            return None

    mtu = _int("mtu")
    return {
        "present": True,
        "operstate": _str("operstate"),
        "mtu": mtu,
        "fd": (mtu or 0) >= _CANFD_MTU,
        "rx_packets": _int("statistics/rx_packets"),
        # rx_errors climbs on receive errors (bad CRC/form/bit), which is how a
        # CAN-FD bit-timing or termination mismatch shows up: the link is up and
        # the bus is active, but frames arrive corrupt instead of clean.
        "rx_errors": _int("statistics/rx_errors"),
    }


def _configured_settings(channel: str, backend: str) -> dict[str, Any]:
    """The fd/bitrate a configured interface uses, so any caller opens the bus
    the way the user set it up. A CAN-FD bus MUST be opened with fd=True or the
    kernel never delivers its FD frames to us (a classic socket only sees classic
    frames), which is why the monitor and diagnostics could show nothing on an FD
    bus. Best-effort and lazy to avoid an import cycle."""
    out: dict[str, Any] = {}
    try:
        from ..services import can_interfaces
        for entry in can_interfaces.list_interfaces():
            if entry.get("channel") == channel and entry.get("backend", "socketcan") == backend:
                out = {"fd": bool(entry.get("fd"))}
                if entry.get("bitrate"):
                    out["bitrate"] = entry["bitrate"]
                if entry.get("data_bitrate"):
                    out["data_bitrate"] = entry["data_bitrate"]
                break
    except Exception:
        pass
    # The live link is ground truth for CAN-FD. A classic socket receives NO
    # frames from a bus that is up in CAN-FD, so if the link reports FD (MTU 72)
    # we open FD regardless of a missing or stale saved fd flag (e.g. an
    # interface saved before its FD box was ticked, or brought up FD by the boot
    # service). An FD socket still receives classic frames, so forcing FD here is
    # always safe, and it is the only way a capture on an FD bus sees anything.
    if backend == "socketcan" and _link_is_fd(channel):
        out["fd"] = True
    return out


def get_channel(channel: str, backend: str = "socketcan", **kwargs: Any) -> CanProvider:
    """Return the cached provider for this channel, creating it on first use.

    fd/bitrate default from the channel's configured interface so every caller
    (monitor, capture, self-test, sniff) opens an FD bus in FD mode, not only the
    ones that happen to pass fd. If a cached provider was opened with a different
    fd than we now need, it is rebuilt.
    """
    settings = _configured_settings(channel, backend)
    settings.update({k: v for k, v in kwargs.items() if v is not None})
    key = f"{backend}:{channel}"
    provider = _channels.get(key)
    if provider is not None and getattr(provider, "fd", None) is not None \
            and bool(getattr(provider, "fd")) != bool(settings.get("fd", getattr(provider, "fd"))):
        try:
            provider.close()
        except Exception:
            pass
        provider = None
    if provider is None:
        provider = create_provider(backend, channel, **settings)
        _channels[key] = provider
    return provider


def open_channel(channel: str, backend: str = "socketcan", **kwargs: Any) -> CanProvider:
    """A fresh, un-cached provider with its own socket, resolving fd/bitrate from
    the configured interface like get_channel. Use this for a short read (Listen,
    Snapshot, a one-off capture) so it never competes with the live Monitor over
    one shared socket, and never inherits a socket left stale by an interface
    down/up. SocketCAN delivers every frame to each open socket, so a dedicated
    socket always sees the traffic. The caller MUST close it when done."""
    settings = _configured_settings(channel, backend)
    settings.update({k: v for k, v in kwargs.items() if v is not None})
    return create_provider(backend, channel, **settings)


def reset_channels() -> None:
    """Close and drop every cached provider. Mainly for tests."""
    for provider in _channels.values():
        try:
            provider.close()
        except Exception:
            pass
    _channels.clear()
