"""Provider registry: open a CAN channel by backend name.

``socketcan`` (the Waveshare 2-Ch CAN-FD HAT, and every other Linux CAN
adapter) is the default. ``pcan`` (PEAK PCAN-USB), ``vector`` (Vector
Informatik interfaces), and ``virtual`` (an in-process loopback bus for
testing without hardware) wrap the matching python-can backend the same
way. ``lin`` and ``doip`` are registered as NOT-YET-IMPLEMENTED stubs (see
``lin.py`` and ``doip.py``) so the extension point is visible in code.
"""
from __future__ import annotations

from typing import Any

from .base import CanProvider
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


def _configured_settings(channel: str, backend: str) -> dict[str, Any]:
    """The fd/bitrate a configured interface uses, so any caller opens the bus
    the way the user set it up. A CAN-FD bus MUST be opened with fd=True or the
    kernel never delivers its FD frames to us (a classic socket only sees classic
    frames), which is why the monitor and diagnostics could show nothing on an FD
    bus. Best-effort and lazy to avoid an import cycle."""
    try:
        from ..services import can_interfaces
        for entry in can_interfaces.list_interfaces():
            if entry.get("channel") == channel and entry.get("backend", "socketcan") == backend:
                out: dict[str, Any] = {"fd": bool(entry.get("fd"))}
                if entry.get("bitrate"):
                    out["bitrate"] = entry["bitrate"]
                if entry.get("data_bitrate"):
                    out["data_bitrate"] = entry["data_bitrate"]
                return out
    except Exception:
        pass
    return {}


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
