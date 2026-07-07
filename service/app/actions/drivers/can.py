"""CAN bus driver.

Phase 2 adds the automotive CAN environment through CAN HATs, with the
Waveshare 2-Channel CAN-FD HAT as the first target. That board carries two
MCP2518FD controllers on SPI; on Raspberry Pi OS they come up as SocketCAN
interfaces (can0, can1) once the mcp251xfd overlay is enabled and the bitrate
is set with ``ip link`` (see ``scripts/image-build/setup-can-waveshare.sh``).

This driver sends a frame through ``app.can``: the ``socketcan`` provider on
python-can when a real interface is present, or a simulated send (the frame
is validated and reported, nothing goes out) when it is not. That is what
lets CAN actions be created, laid out, and tested on any machine, and then
actually fire once a channel is wired up.
"""
from __future__ import annotations

from typing import Any

from app.can import Frame, get_channel, parse_arbitration_id, parse_data_bytes

from .base import Driver, DriverResult

# Interfaces the Waveshare 2-Ch CAN-FD HAT brings up by default.
_DEFAULT_CHANNELS = ("can0", "can1")


class CanDriver(Driver):
    name = "can"
    label = "CAN frame"
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
        # True once at least one of the default channels is a real, openable
        # SocketCAN interface. Individual actions can still target any other
        # channel name; this just reports whether CAN plumbing exists at all
        # on this host, so the setup UI and the tests can tell a laptop with
        # no HAT apart from a Pi with one wired up.
        return any(get_channel(ch).available for ch in _DEFAULT_CHANNELS)

    def execute(self, params: dict[str, Any]) -> DriverResult:
        frame_params = _parse_frame(params)
        if isinstance(frame_params, str):
            return DriverResult.failure(frame_params)

        frame = Frame(
            arbitration_id=frame_params["arbitration_id"],
            data=frame_params["data"],
            is_fd=frame_params["is_fd"],
            is_extended_id=frame_params["is_extended_id"],
        )
        error = frame.validate()
        if error:
            return DriverResult.failure(error)

        channel_name = frame_params["channel"]
        channel = get_channel(channel_name)
        if not channel.available:
            return DriverResult.success(
                f"(simulated) would send {frame.format()} on {channel_name}",
                simulated=True, **frame_params,
            )
        if channel.send(frame):
            return DriverResult.success(
                f"Sent {frame.format()} on {channel_name}", **frame_params)
        return DriverResult.failure(
            f"CAN send failed on {channel_name}", **frame_params)


def _parse_frame(params: dict[str, Any]) -> dict[str, Any] | str:
    """Validate and normalize CAN frame params. Returns an error string on failure.

    Pure so frame parsing can be unit-tested without hardware.
    """
    channel = str(params.get("channel", "can0")).strip() or "can0"
    raw_id = str(params.get("arbitration_id", "")).strip()
    if not raw_id:
        return "No arbitration id configured"
    try:
        arbitration_id = parse_arbitration_id(raw_id)
    except ValueError:
        return f"Invalid arbitration id: {raw_id}"
    try:
        data = parse_data_bytes(str(params.get("data", "")))
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
