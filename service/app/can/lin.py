"""LIN provider: NOT YET IMPLEMENTED.

LIN (Local Interconnect Network) is the low-speed, single-wire bus vehicles
use for body electronics (window switches, mirrors, seat controls) where a
full CAN transceiver would be overkill. python-can has no LIN backend, so
this would need a vendor-specific LIN library (most USB-LIN adapters ship
their own Python bindings) and a different frame identifier scheme (LIN
uses 6-bit ids and a checksum, not the 11/29-bit CAN arbitration id in
``Frame``).

This stub exists so the extension point is visible in code, not just in
docs (see ``docs/can.md``). It always reports unavailable and every method
is a no-op; nothing in the app calls it yet.
"""
from __future__ import annotations

from typing import Any

from .base import CanProvider, Frame


class LinProvider(CanProvider):
    name = "lin"

    def __init__(self, channel: str = "", **kwargs: Any) -> None:
        super().__init__(channel)

    @property
    def available(self) -> bool:
        return False

    def open(self) -> bool:
        return False

    def close(self) -> None:
        return None

    def send(self, frame: Frame) -> bool:
        return False

    def recv(self, timeout: float | None = None) -> Frame | None:
        return None

    def set_filters(self, filters: list[dict[str, Any]]) -> None:
        return None
