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


def get_channel(channel: str, backend: str = "socketcan", **kwargs: Any) -> CanProvider:
    """Return the cached provider for this channel, creating it on first use."""
    key = f"{backend}:{channel}"
    provider = _channels.get(key)
    if provider is None:
        provider = create_provider(backend, channel, **kwargs)
        _channels[key] = provider
    return provider


def reset_channels() -> None:
    """Close and drop every cached provider. Mainly for tests."""
    for provider in _channels.values():
        try:
            provider.close()
        except Exception:
            pass
    _channels.clear()
