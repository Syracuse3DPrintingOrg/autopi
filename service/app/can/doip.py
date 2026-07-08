"""DoIP (Diagnostics over IP) provider: NOT YET IMPLEMENTED.

DoIP is automotive Ethernet's diagnostic transport (ISO 13400), used by
newer vehicles alongside or instead of a CAN gateway for UDS diagnostic
sessions. It is not a CAN backend at all, so it does not map cleanly onto
``CanProvider``: DoIP addresses ECUs by a logical address over TCP/UDP, not
by CAN arbitration id, and framing is a different shape than ``Frame``.

python-can has no DoIP backend. A real implementation would likely sit
alongside this ``can/`` package (not inside it) and use the MIT-licensed
`doipclient <https://github.com/jacobjrose/doipclient>`_ library for the
protocol, exposing a comparable "connect a channel, send/receive" surface
so the rest of the app (actions, the monitor) can treat it uniformly.

This stub exists so the extension point is visible in code, not just in
docs (see ``docs/can.md``). It always reports unavailable and every method
is a no-op; nothing in the app calls it yet.
"""
from __future__ import annotations

from typing import Any

from .base import CanProvider, Frame


class DoipProvider(CanProvider):
    name = "doip"

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
