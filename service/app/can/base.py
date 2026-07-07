"""CAN core: the backend-independent Frame value type and provider ABC.

Kept independent of any concrete backend (python-can, socketcan) so frame
parsing, validation, and formatting stay pure and unit-testable without any
hardware or the ``can`` package installed.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# Classic CAN carries 0-8 data bytes.
CLASSIC_LENGTHS = range(0, 9)
# CAN-FD's DLC maps to these payload lengths (the extra sizes above 8 bytes).
FD_LENGTHS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64)

STANDARD_ID_MAX = 0x7FF
EXTENDED_ID_MAX = 0x1FFFFFFF


@dataclass(frozen=True)
class Frame:
    """One CAN (or CAN-FD) frame, independent of any backend.

    ``arbitration_id`` is the raw integer id (11-bit standard or 29-bit
    extended). ``data`` is the payload as a list of 0-255 ints. A remote
    frame requests data from another node and carries none of its own.
    """

    arbitration_id: int
    data: list[int] = field(default_factory=list)
    is_fd: bool = False
    is_extended_id: bool = False
    is_remote: bool = False

    @property
    def dlc(self) -> int:
        return len(self.data)

    def validate(self) -> str | None:
        """Return an error string, or None if the frame is well-formed."""
        max_id = EXTENDED_ID_MAX if self.is_extended_id else STANDARD_ID_MAX
        if not (0 <= self.arbitration_id <= max_id):
            width = "29-bit extended" if self.is_extended_id else "11-bit standard"
            return f"Arbitration id 0x{self.arbitration_id:X} exceeds the {width} range"
        if any(b < 0 or b > 0xFF for b in self.data):
            return "Data bytes must be 0x00-0xFF"
        if self.is_remote and self.data:
            return "A remote frame carries no data of its own"
        allowed = FD_LENGTHS if self.is_fd else CLASSIC_LENGTHS
        if len(self.data) not in allowed:
            kind = "CAN-FD" if self.is_fd else "classic CAN"
            return f"{len(self.data)} data bytes is not a valid {kind} length"
        return None

    def format(self) -> str:
        """Human-readable one-liner, e.g. '0x7DF#02 01 0C (ext, fd)'."""
        hex_id = f"0x{self.arbitration_id:X}"
        if self.is_remote:
            hex_data = "(remote)"
        elif self.data:
            hex_data = " ".join(f"{b:02X}" for b in self.data)
        else:
            hex_data = "(empty)"
        flags = [f for f, on in (("ext", self.is_extended_id), ("fd", self.is_fd)) if on]
        suffix = f" ({', '.join(flags)})" if flags else ""
        return f"{hex_id}#{hex_data}{suffix}"


def parse_arbitration_id(raw: str) -> int:
    """Parse a user-typed arbitration id: '0x7DF' as hex, '2024' by Python's
    normal integer rules (decimal, or '0x'/'0o'/'0b' prefixed).

    Raises ValueError on anything else.
    """
    raw = raw.strip()
    if not raw:
        raise ValueError("empty arbitration id")
    if raw.lower().startswith("0x"):
        return int(raw, 16)
    return int(raw, 0)


def parse_data_bytes(raw: str) -> list[int]:
    """Parse space/comma separated hex bytes, e.g. '02 01 0C' -> [2, 1, 12]."""
    tokens = raw.replace(",", " ").split()
    return [int(t, 16) for t in tokens]


class CanProvider(ABC):
    """A CAN bus backend for one channel (e.g. ``can0``).

    A concrete provider (``SocketCanProvider`` today; ``pcan``, ``vector``,
    and ``virtual`` are separate follow-on beads) wraps whatever transport
    python-can supports. A provider that cannot reach its channel, because
    python-can is not installed or the interface does not exist, reports
    ``available`` False and every other method becomes a safe no-op, so a
    build with no CAN hardware attached still imports, registers actions, and
    runs its tests.
    """

    name: str = ""

    def __init__(self, channel: str, **kwargs: Any) -> None:
        self.channel = channel

    @property
    @abstractmethod
    def available(self) -> bool:
        """Whether this provider could plausibly open its channel right now."""
        raise NotImplementedError

    @abstractmethod
    def open(self) -> bool:
        """Open the channel. Returns True on success, False (never raises)
        if the backend or the channel is unavailable."""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """Close the channel if open. Safe to call repeatedly or unopened."""
        raise NotImplementedError

    @abstractmethod
    def send(self, frame: Frame) -> bool:
        """Send a frame. Returns True on success, False on any failure."""
        raise NotImplementedError

    @abstractmethod
    def recv(self, timeout: float | None = None) -> Frame | None:
        """Receive one frame, waiting up to ``timeout`` seconds (None: block
        forever, 0: poll). Returns None on timeout, closed channel, or an
        unavailable backend."""
        raise NotImplementedError

    @abstractmethod
    def set_filters(self, filters: list[dict[str, Any]]) -> None:
        """Install acceptance filters (python-can's filter dict shape:
        ``{"can_id": ..., "can_mask": ..., "extended": ...}``). A no-op when
        unavailable."""
        raise NotImplementedError
