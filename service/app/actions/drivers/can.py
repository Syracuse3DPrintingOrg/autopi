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
    simulate_when_unavailable = True  # execute() reports a simulated send with no bus
    param_schema = [
        {"key": "channel", "label": "Interface", "type": "text", "required": True,
         "default": "can0",
         "help": "The channel name, e.g. can0. See CAN Interfaces in Settings for what "
                 "each configured channel is used for."},
        {"key": "arbitration_id", "label": "Arbitration ID (hex)", "type": "text",
         "required": True, "help": "e.g. 0x7DF"},
        {"key": "data", "label": "Data bytes (hex)", "type": "text", "required": False,
         "help": "Space or comma separated, e.g. 02 01 0C"},
        {"key": "is_fd", "label": "CAN-FD frame", "type": "bool", "required": False,
         "default": False},
        {"key": "is_extended_id", "label": "Extended (29-bit) id", "type": "bool",
         "required": False, "default": False},
        {"key": "period_ms", "label": "Repeat every (ms, 0 = one-shot)", "type": "number",
         "required": False, "default": 0,
         "help": "0 sends the frame once per press. A value keeps sending it at that rate "
                 "and the key toggles it on/off (needed for controls the ECU expects every cycle)."},
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

        channel_name = frame_params["channel"]
        # A CAN-FD action must transmit on an fd=True socket; a classic socket
        # rejects the FD frame and sends nothing. Force fd for an FD frame and
        # leave classic frames on the channel's configured mode (fd=None does
        # not override the resolved setting).
        channel = get_channel(channel_name,
                              fd=True if frame_params["is_fd"] else None)
        overlay = frame_params.get("overlay")

        # Resolve the bytes actually put on the bus. A control saved with a bit
        # mask changes only its own bits on the frame that is live right now,
        # leaving the other signals in that shared message alone; the stored data
        # is only the resting template used when the id is not currently on the
        # bus (or there is no live channel to read). A plain fixed-data action
        # sends its stored bytes verbatim, as before.
        send_data = frame_params["data"]
        source = "fixed"
        if overlay:
            from app.can import overlay as ov
            live_provider = channel if channel.available else None
            send_data, source = ov.overlaid_data(
                live_provider, frame_params["arbitration_id"],
                overlay["byte"], overlay["mask"], overlay["active"],
                template=frame_params["data"])

        frame = Frame(
            arbitration_id=frame_params["arbitration_id"],
            data=send_data,
            is_fd=frame_params["is_fd"],
            is_extended_id=frame_params["is_extended_id"],
        )
        error = frame.validate()
        if error:
            return DriverResult.failure(error)

        # A repeat rate turns this into a toggle: press once to start sending the
        # frame every period_ms (to hold a control state), press again to stop.
        # An overlaid control reads the live frame once when it is toggled on;
        # per-cycle re-read and rolling-counter/checksum recompute are a later
        # layer (see AutoPi-v72), needed only on buses that checksum.
        try:
            period_ms = int(params.get("period_ms") or 0)
        except (TypeError, ValueError):
            period_ms = 0
        if period_ms > 0:
            from app.services import can_tx
            now_on = can_tx.toggle(channel_name, frame_params["arbitration_id"], send_data,
                                   period_ms=period_ms, is_fd=frame_params["is_fd"],
                                   is_extended_id=frame_params["is_extended_id"])
            return DriverResult.success(
                (f"Sending {frame.format()} on {channel_name} every {period_ms} ms" if now_on
                 else f"Stopped sending {frame.format()} on {channel_name}"),
                periodic=now_on, **frame_params)

        if not channel.available:
            return DriverResult.success(
                f"(simulated) would send {frame.format()} on {channel_name}",
                simulated=True, **frame_params,
            )
        if channel.send(frame):
            suffix = f" (changed its bits on the {source} frame)" if overlay else ""
            return DriverResult.success(
                f"Sent {frame.format()} on {channel_name}{suffix}", **frame_params)
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
        "overlay": _parse_overlay(params),
    }


def _parse_overlay(params: dict[str, Any]) -> dict[str, int] | None:
    """A control saved by the Signal Finder carries a bit mask so the driver
    changes only its bits on the live frame instead of replaying stored bytes.
    Returns None for a plain fixed-data action (the legacy shape). Pure.
    """
    def _as_int(value: Any) -> int:
        if isinstance(value, (int, float)):
            return int(value)
        text = str(value).strip().lower()
        return int(text, 16) if text.startswith("0x") else int(text or 0)

    raw_mask = str(params.get("overlay_mask", "")).strip().lower()
    if raw_mask in ("", "0", "0x0", "0x00"):
        return None
    try:
        mask = _as_int(raw_mask)
        byte = _as_int(params.get("overlay_byte") or 0)
        active = _as_int(params.get("overlay_value") or 0)
    except (TypeError, ValueError):
        return None
    mask &= 0xFF
    if not mask or byte < 0:
        return None
    return {"byte": byte, "mask": mask, "active": active & mask}
