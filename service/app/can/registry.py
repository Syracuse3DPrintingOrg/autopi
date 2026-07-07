"""Provider registry: open a CAN channel by backend name.

Only ``socketcan`` is implemented (the Waveshare 2-Ch CAN-FD HAT, and every
other Linux CAN adapter, comes up as a SocketCAN interface). ``pcan``,
``vector``, and ``virtual`` are separate follow-on beads; register them here
the same way once they land, nothing else in the app needs to change.
"""
from __future__ import annotations

from typing import Any

from .base import CanProvider
from .socketcan import SocketCanProvider

# backend name -> provider class. Extend here for pcan / vector / virtual.
PROVIDER_CLASSES: dict[str, type[CanProvider]] = {
    "socketcan": SocketCanProvider,
}

# One provider instance per (backend, channel), so repeated sends reuse the
# same open bus instead of reopening it every time, mirroring how the GPIO
# driver caches one device per pin.
_channels: dict[str, CanProvider] = {}


def register_provider(backend: str, cls: type[CanProvider]) -> None:
    PROVIDER_CLASSES[backend] = cls


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
