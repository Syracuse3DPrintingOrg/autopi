"""CAN core (Phase 2): a backend-independent Frame type, a provider
abstraction, and a registry that opens a channel by name.

Built on `python-can <https://python-can.readthedocs.io/>`_ with the
``socketcan`` backend as the default, which is what the Waveshare
2-Channel CAN-FD HAT presents once its overlay is enabled. See
``scripts/image-build/setup-can-waveshare.sh`` for hardware bring-up and
``docs/can.md`` for the full picture.
"""
from __future__ import annotations

from .base import CanProvider, Frame, parse_arbitration_id, parse_data_bytes
from .registry import create_provider, get_channel, register_provider, reset_channels
from .simulation import SimEngine, build_frame, engine as sim_engine
from .socketcan import SocketCanProvider

__all__ = [
    "CanProvider",
    "Frame",
    "SimEngine",
    "SocketCanProvider",
    "build_frame",
    "create_provider",
    "get_channel",
    "parse_arbitration_id",
    "parse_data_bytes",
    "register_provider",
    "reset_channels",
    "sim_engine",
]
