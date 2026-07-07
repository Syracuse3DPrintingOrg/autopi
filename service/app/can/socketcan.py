"""SocketCAN provider, the default backend on Linux.

Wraps python-can's ``socketcan`` interface, which is what the Waveshare
2-Channel CAN-FD HAT (and every other Linux CAN adapter) presents once its
kernel driver is up: a ``can0``/``can1`` style network interface. Degrades
gracefully: if python-can is not installed, or the named interface does not
exist or cannot be opened, ``available`` is False and every call is a safe
no-op, so the app imports and the test suite runs on a laptop with no CAN
hardware attached.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .base import CanProvider, Frame

log = logging.getLogger(__name__)


class SocketCanProvider(CanProvider):
    name = "socketcan"

    def __init__(self, channel: str = "can0", fd: bool = False, **kwargs: Any) -> None:
        super().__init__(channel)
        self.fd = fd
        self._bus: Any = None
        self._open_failed = False

    @property
    def available(self) -> bool:
        if self._bus is not None:
            return True
        if self._open_failed:
            return False
        return self._module_importable() and self._interface_present()

    @staticmethod
    def _module_importable() -> bool:
        try:
            import can  # noqa: F401
        except Exception:
            return False
        return True

    def _interface_present(self) -> bool:
        # A SocketCAN interface shows up under /sys/class/net on Linux once
        # the mcp251xfd overlay (or any other CAN driver) has brought it up.
        # Off Linux, or before the overlay is enabled, this is simply False,
        # which is the expected state on a dev laptop.
        return Path(f"/sys/class/net/{self.channel}").exists()

    def open(self) -> bool:
        if self._bus is not None:
            return True
        if not self._module_importable():
            log.info("python-can not installed; socketcan provider unavailable")
            self._open_failed = True
            return False
        try:
            import can

            self._bus = can.interface.Bus(channel=self.channel, interface="socketcan", fd=self.fd)
            self._open_failed = False
            return True
        except Exception as exc:
            log.info("Could not open CAN channel %s: %s", self.channel, exc)
            self._open_failed = True
            self._bus = None
            return False

    def close(self) -> None:
        if self._bus is not None:
            try:
                self._bus.shutdown()
            except Exception:
                pass
            self._bus = None

    def send(self, frame: Frame) -> bool:
        if self._bus is None and not self.open():
            return False
        try:
            import can

            msg = can.Message(
                arbitration_id=frame.arbitration_id,
                data=bytes(frame.data),
                is_extended_id=frame.is_extended_id,
                is_fd=frame.is_fd,
                is_remote_frame=frame.is_remote,
            )
            self._bus.send(msg)
            return True
        except Exception as exc:
            log.info("CAN send failed on %s: %s", self.channel, exc)
            return False

    def recv(self, timeout: float | None = None) -> Frame | None:
        if self._bus is None and not self.open():
            return None
        try:
            msg = self._bus.recv(timeout=timeout)
        except Exception as exc:
            log.info("CAN recv failed on %s: %s", self.channel, exc)
            return None
        if msg is None:
            return None
        return Frame(
            arbitration_id=msg.arbitration_id,
            data=list(msg.data),
            is_fd=bool(getattr(msg, "is_fd", False)),
            is_extended_id=bool(msg.is_extended_id),
            is_remote=bool(msg.is_remote_frame),
        )

    def set_filters(self, filters: list[dict[str, Any]]) -> None:
        if self._bus is None and not self.open():
            return
        try:
            self._bus.set_filters(filters)
        except Exception as exc:
            log.info("Could not set CAN filters on %s: %s", self.channel, exc)
