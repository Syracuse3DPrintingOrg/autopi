"""CAN core (Phase 2): a backend-independent Frame type, a provider
abstraction, and a registry that opens a channel by name.

Built on `python-can <https://python-can.readthedocs.io/>`_ with
``socketcan`` as the default backend, which is what the Waveshare
2-Channel CAN-FD HAT presents once its overlay is enabled. ``pcan``,
``vector``, and ``virtual`` wrap other python-can backends for other test
equipment. See ``scripts/image-build/setup-can-waveshare.sh`` for hardware
bring-up and ``docs/can.md`` for the full picture.
"""
from __future__ import annotations

from .base import CanProvider, Frame, parse_arbitration_id, parse_data_bytes
from .doip import DoipProvider
from .lin import LinProvider
from .pcan import PcanProvider
from .registry import (
    create_provider,
    get_channel,
    list_backends,
    register_provider,
    reset_channels,
)
from .simulation import SimEngine, build_frame, engine as sim_engine
from .socketcan import SocketCanProvider
from .vector import VectorProvider
from .virtual import VirtualProvider

__all__ = [
    "CanProvider",
    "DoipProvider",
    "Frame",
    "LinProvider",
    "PcanProvider",
    "SimEngine",
    "SocketCanProvider",
    "VectorProvider",
    "VirtualProvider",
    "build_frame",
    "create_provider",
    "get_channel",
    "list_backends",
    "parse_arbitration_id",
    "parse_data_bytes",
    "register_provider",
    "reset_channels",
    "sim_engine",
]
