"""Virtual provider: an in-process loopback bus with no hardware at all.

Wraps python-can's ``virtual`` interface. Any two ``VirtualProvider``
instances opened with the same channel name, in the same Python process,
see each other's frames, which makes this useful for testing an action
layout (or the CAN monitor / DBC decode pages) without any adapter plugged
in. Only python-can itself needs to be installed; unlike every other
provider here, there is no external driver or interface to be missing, so
``available`` only depends on the module import succeeding.
"""
from __future__ import annotations

import logging
from typing import Any

from .base import CanProvider, Frame

log = logging.getLogger(__name__)


class VirtualProvider(CanProvider):
    name = "virtual"

    def __init__(self, channel: str = "virtual0", fd: bool = False, **kwargs: Any) -> None:
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
        return self._module_importable()

    @staticmethod
    def _module_importable() -> bool:
        try:
            import can  # noqa: F401
        except Exception:
            return False
        return True

    def open(self) -> bool:
        if self._bus is not None:
            return True
        if not self._module_importable():
            log.info("python-can not installed; virtual provider unavailable")
            self._open_failed = True
            return False
        try:
            import can

            self._bus = can.interface.Bus(channel=self.channel, interface="virtual", fd=self.fd)
            self._open_failed = False
            return True
        except Exception as exc:
            log.info("Could not open virtual CAN channel %s: %s", self.channel, exc)
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
            log.info("Virtual CAN send failed on %s: %s", self.channel, exc)
            return False

    def recv(self, timeout: float | None = None) -> Frame | None:
        if self._bus is None and not self.open():
            return None
        try:
            msg = self._bus.recv(timeout=timeout)
        except Exception as exc:
            log.info("Virtual CAN recv failed on %s: %s", self.channel, exc)
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
            log.info("Could not set virtual CAN filters on %s: %s", self.channel, exc)
