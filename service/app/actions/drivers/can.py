"""CAN bus driver (Phase 2 placeholder).

Phase 2 adds the automotive CAN environment through CAN HATs, with the
Waveshare 2-Channel CAN-FD HAT as the first target. That board carries two
MCP2518FD controllers on SPI; on Raspberry Pi OS they come up as SocketCAN
interfaces (can0, can1) once the mcp251xfd overlay is enabled and the bitrate
is set with ``ip link``.

The intended implementation sits on python-can with the socketcan backend:
send a frame, send an ISO-TP / UDS request, or watch an id and react. Until
that lands this driver reports itself unavailable and records the frame it
would have sent, so CAN actions can already be created, laid out, and tested.
"""
from __future__ import annotations

from typing import Any

from .base import Driver, DriverResult


class CanDriver(Driver):
    name = "can"
    label = "CAN frame (Phase 2)"
    param_schema = [
        {"key": "channel", "label": "Interface", "type": "text", "required": True,
         "default": "can0"},
        {"key": "arbitration_id", "label": "Arbitration ID (hex)", "type": "text",
         "required": True, "help": "e.g. 0x7DF"},
        {"key": "data", "label": "Data bytes (hex)", "type": "text", "required": False,
         "help": "Space or comma separated, e.g. 02 01 0C"},
        {"key": "is_fd", "label": "CAN-FD frame", "type": "bool", "required": False,
         "default": False},
        {"key": "is_extended_id", "label": "Extended (29-bit) id", "type": "bool",
         "required": False, "default": False},
    ]

    @property
    def available(self) -> bool:
        # Available once python-can is installed and a socketcan interface can
        # be opened. Kept False by default so Phase 1 hosts never try to send.
        try:
            import can  # noqa: F401
            return False  # flip to a real interface probe when Phase 2 lands
        except Exception:
            return False

    def execute(self, params: dict[str, Any]) -> DriverResult:
        frame = _parse_frame(params)
        if isinstance(frame, str):
            return DriverResult.failure(frame)
        return DriverResult.success(
            "(not yet implemented) would send CAN frame "
            f"id={hex(frame['arbitration_id'])} data={frame['data']!r} "
            f"on {frame['channel']}",
            simulated=True, **frame,
        )


def _parse_frame(params: dict[str, Any]) -> dict[str, Any] | str:
    """Validate and normalize CAN frame params. Returns an error string on failure.

    Pure so Phase 2 can unit-test frame parsing without any hardware.
    """
    channel = str(params.get("channel", "can0")).strip() or "can0"
    raw_id = str(params.get("arbitration_id", "")).strip()
    if not raw_id:
        return "No arbitration id configured"
    try:
        arbitration_id = int(raw_id, 16) if raw_id.lower().startswith("0x") else int(raw_id, 0)
    except ValueError:
        return f"Invalid arbitration id: {raw_id}"
    data_raw = str(params.get("data", "")).replace(",", " ").split()
    try:
        data = [int(b, 16) for b in data_raw]
    except ValueError:
        return f"Invalid data bytes: {params.get('data')}"
    if any(b < 0 or b > 0xFF for b in data):
        return "Data bytes must be 0x00-0xFF"
    return {
        "channel": channel,
        "arbitration_id": arbitration_id,
        "data": data,
        "is_fd": bool(params.get("is_fd", False)),
        "is_extended_id": bool(params.get("is_extended_id", False)),
    }
