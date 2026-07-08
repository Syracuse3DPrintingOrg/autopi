"""PCAN provider for PEAK Systems' PCAN-USB adapters.

Wraps python-can's ``pcan`` interface. Degrades gracefully: if python-can (or
its PCAN-Basic driver dependency) is not installed, or the adapter is not
plugged in, ``available`` is False and every call is a safe no-op, mirroring
``SocketCanProvider``.
"""
from __future__ import annotations

import logging
import sys
from typing import Any

from .base import CanProvider, Frame

log = logging.getLogger(__name__)


class PcanProvider(CanProvider):
    name = "pcan"

    def __init__(
        self,
        channel: str = "PCAN_USBBUS1",
        fd: bool = False,
        bitrate: int = 500000,
        data_bitrate: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(channel)
        self.fd = fd
        self.bitrate = bitrate
        self.data_bitrate = data_bitrate
        self._bus: Any = None
        self._open_failed = False
        # The last connection error, in plain language, so the self-test and the
        # status badge can say why a PEAK adapter would not connect instead of a
        # generic failure.
        self.last_error: str | None = None

    @property
    def available(self) -> bool:
        # Availability means the adapter actually opens, not merely that
        # python-can is importable: the "pcan" interface needs PEAK's PCAN-Basic
        # userspace driver, which most Linux/Pi setups do not have. Attempt the
        # open once (cached) so the status badge tells the truth.
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

    def open(self) -> bool:
        if self._bus is not None:
            return True
        if not self._module_importable():
            log.info("python-can not installed; pcan provider unavailable")
            self._open_failed = True
            return False
        try:
            import can

            kwargs: dict[str, Any] = {
                "channel": self.channel,
                "interface": "pcan",
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
            self.last_error = self._explain(exc)
            log.info("Could not open PCAN channel %s: %s", self.channel, exc)
            self._open_failed = True
            self._bus = None
            return False

    def _explain(self, exc: Exception) -> str:
        """Turn a python-can open failure into an actionable message.

        The common trap on a Raspberry Pi is picking the pcan backend at all: a
        PEAK PCAN-USB there is handled by the mainline peak_usb kernel driver and
        shows up as a normal SocketCAN interface (can0/can1), which AutoPi drives
        through the socketcan backend. python-can's pcan interface instead needs
        PEAK's separate PCAN-Basic userspace library, which is mostly a
        Windows/macOS thing and is rarely installed on Linux.
        """
        detail = str(exc) or exc.__class__.__name__
        if sys.platform.startswith("linux"):
            return (
                f"Could not open PEAK adapter '{self.channel}' ({detail}). "
                "On Linux a PEAK PCAN-USB is used through SocketCAN, not this pcan "
                "backend: set this interface's backend to socketcan with channel "
                "can0 (or can1) and bring it up on the CAN Interfaces page. The pcan "
                "backend needs PEAK's PCAN-Basic driver, which is not installed here."
            )
        return (
            f"Could not open PEAK adapter '{self.channel}' ({detail}). Check that the "
            "adapter is plugged in and PEAK's PCAN-Basic driver is installed."
        )

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
            log.info("PCAN send failed on %s: %s", self.channel, exc)
            return False

    def recv(self, timeout: float | None = None) -> Frame | None:
        if self._bus is None and not self.open():
            return None
        try:
            msg = self._bus.recv(timeout=timeout)
        except Exception as exc:
            log.info("PCAN recv failed on %s: %s", self.channel, exc)
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
            log.info("Could not set PCAN filters on %s: %s", self.channel, exc)
