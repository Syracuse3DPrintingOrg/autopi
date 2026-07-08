"""Vector provider for Vector Informatik interfaces (VN1610, VN1630, etc).

Wraps python-can's ``vector`` interface, which needs the vendor's XL Driver
Library installed on the host. Degrades gracefully: if python-can (or the
Vector driver) is not present, or no Vector hardware answers, ``available``
is False and every call is a safe no-op, mirroring ``SocketCanProvider``.
"""
from __future__ import annotations

import logging
from typing import Any

from .base import CanProvider, Frame

log = logging.getLogger(__name__)


class VectorProvider(CanProvider):
    name = "vector"

    def __init__(
        self,
        channel: str = "0",
        fd: bool = False,
        bitrate: int = 500000,
        data_bitrate: int | None = None,
        app_name: str = "AutoPi",
        **kwargs: Any,
    ) -> None:
        super().__init__(channel)
        self.fd = fd
        self.bitrate = bitrate
        self.data_bitrate = data_bitrate
        self.app_name = app_name
        self._bus: Any = None
        self._open_failed = False
        self.last_error: str | None = None

    @property
    def available(self) -> bool:
        # As with PCAN, availability means the hardware actually opens (the
        # Vector backend needs the vendor XL Driver Library), so the status badge
        # reflects a real connection attempt rather than just python-can being
        # importable.
        if self._bus is not None:
            return True
        if self._open_failed:
            return False
        if not self._module_importable():
            self.last_error = "python-can is not installed."
            return False
        return self.open()

    @staticmethod
    def _module_importable() -> bool:
        try:
            import can  # noqa: F401
        except Exception:
            return False
        return True

    def _channel_index(self) -> int | str:
        # The Vector backend takes an integer channel index (or a list of
        # them); fall back to the raw string if it is not numeric so a
        # named channel still gets passed through to python-can as-is.
        try:
            return int(self.channel)
        except (TypeError, ValueError):
            return self.channel

    def open(self) -> bool:
        if self._bus is not None:
            return True
        if not self._module_importable():
            self.last_error = "python-can is not installed."
            log.info("python-can not installed; vector provider unavailable")
            self._open_failed = True
            return False
        try:
            import can

            kwargs: dict[str, Any] = {
                "channel": self._channel_index(),
                "interface": "vector",
                "app_name": self.app_name,
                "bitrate": self.bitrate,
            }
            if self.fd:
                kwargs["fd"] = True
                if self.data_bitrate:
                    kwargs["data_bitrate"] = self.data_bitrate
            self._bus = can.interface.Bus(**kwargs)
            self._open_failed = False
            self.last_error = None
            return True
        except Exception as exc:
            detail = str(exc) or exc.__class__.__name__
            self.last_error = (
                f"Could not open Vector channel '{self.channel}' ({detail}). Check the "
                "adapter is connected and the Vector XL Driver Library is installed; the "
                "app_name must also be registered in the Vector Hardware Config."
            )
            log.info("Could not open Vector channel %s: %s", self.channel, exc)
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
            log.info("Vector send failed on %s: %s", self.channel, exc)
            return False

    def recv(self, timeout: float | None = None) -> Frame | None:
        if self._bus is None and not self.open():
            return None
        try:
            msg = self._bus.recv(timeout=timeout)
        except Exception as exc:
            log.info("Vector recv failed on %s: %s", self.channel, exc)
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
            log.info("Could not set Vector filters on %s: %s", self.channel, exc)
