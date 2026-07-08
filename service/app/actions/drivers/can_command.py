"""Vehicle command driver: send a named CAN message.

A "vehicle command" is a message you already know by name, e.g. Volume Up,
because it came from an imported CAN database (DBC): pick the database, the
message, and the signal values to encode (``app.can.dbc.encode`` does the bit
math), and this driver builds the frame and sends it. That is what lets
someone build a "Volume Up" key without typing a raw arbitration id or hex
bytes by hand.

For a message with no database (or a one-off frame you already know the id
and bytes for), the driver falls back to a raw mode: an explicit
``arbitration_id`` and ``data``, the same shape as the plain ``can`` driver.

Sending itself goes through ``app.can``, the same channel registry the ``can``
driver uses: a real send on the ``socketcan`` provider when a channel is
open, or a simulated send (validated and reported, nothing goes out) when it
is not, so a command action can be created and tested on any machine.
"""
from __future__ import annotations

from typing import Any

from app.can import Frame, get_channel, parse_arbitration_id, parse_data_bytes
from app.can.dbc import encode as dbc_encode
from app.db import CanDatabase, CanMessage, session_scope

from .base import Driver, DriverResult

# Interfaces the Waveshare 2-Ch CAN-FD HAT brings up by default.
_DEFAULT_CHANNELS = ("can0", "can1")


class CanCommandDriver(Driver):
    name = "can_command"
    label = "Vehicle command (CAN)"
    simulate_when_unavailable = True  # execute() reports a simulated send with no bus
    param_schema = [
        {"key": "channel", "label": "Interface", "type": "text", "required": False,
         "default": "can0",
         "help": "The channel name, e.g. can0. See CAN Interfaces in Settings for what "
                 "each configured channel is used for."},
        {"key": "database_id", "label": "CAN database", "type": "number", "required": False,
         "help": "Pick the database this command's message belongs to. Leave blank "
                 "to send a raw frame instead."},
        {"key": "checksum", "label": "Checksum algorithm", "type": "choice",
         "choices": ["", "chrysler"], "required": False, "default": "",
         "help": "Set to chrysler for Stellantis CUSW messages so a real module accepts the frame."},
        {"key": "message", "label": "Message", "type": "text", "required": False,
         "help": "The message name from the selected database, e.g. VOLUME_CONTROL."},
        {"key": "signals", "label": "Signal values", "type": "keyvalue", "required": False,
         "help": "Signal name to value, e.g. VOLUME_UP: 1."},
        {"key": "arbitration_id", "label": "Arbitration ID (hex)", "type": "text",
         "required": False,
         "help": "Only needed for a raw frame with no database, e.g. 0x3D1."},
        {"key": "data", "label": "Data bytes (hex)", "type": "text", "required": False,
         "help": "Only needed for a raw frame with no database. Space or comma "
                 "separated, e.g. 02 01 0C."},
        {"key": "is_fd", "label": "CAN-FD frame", "type": "bool", "required": False,
         "default": False},
        {"key": "is_extended_id", "label": "Extended (29-bit) id", "type": "bool",
         "required": False, "default": False},
    ]

    @property
    def available(self) -> bool:
        # Mirrors the plain `can` driver: true once one of the default
        # channels is a real, openable SocketCAN interface.
        return any(get_channel(ch).available for ch in _DEFAULT_CHANNELS)

    def execute(self, params: dict[str, Any]) -> DriverResult:
        database_id = params.get("database_id")
        message = str(params.get("message") or "").strip()
        dbc_text: str | None = None
        resolved_arbitration_id: int | None = None

        if database_id not in (None, "") and message:
            try:
                database_id = int(database_id)
            except (TypeError, ValueError):
                return DriverResult.failure(f"Invalid CAN database id: {database_id}")
            with session_scope() as s:
                database = s.get(CanDatabase, database_id)
                if database is None or not database.dbc_text:
                    return DriverResult.failure(f"No DBC text for database {database_id}")
                dbc_text = database.dbc_text
                row = (
                    s.query(CanMessage)
                    .filter_by(database_id=database_id, name=message)
                    .first()
                )
                resolved_arbitration_id = row.arbitration_id if row else None

        built = build_command_frame(
            params, dbc_text=dbc_text, resolved_arbitration_id=resolved_arbitration_id)
        if isinstance(built, str):
            return DriverResult.failure(built)

        frame = Frame(**built["frame"])
        error = frame.validate()
        if error:
            return DriverResult.failure(error)

        channel_name = built["channel"]
        channel = get_channel(channel_name)
        report = {
            "channel": channel_name,
            "arbitration_id": frame.arbitration_id,
            "data": frame.data,
        }
        if not channel.available:
            return DriverResult.success(
                f"(simulated) would send {frame.format()} on {channel_name}",
                simulated=True, **report,
            )
        if channel.send(frame):
            return DriverResult.success(f"Sent {frame.format()} on {channel_name}", **report)
        return DriverResult.failure(f"CAN send failed on {channel_name}", **report)


def build_command_frame(
    params: dict[str, Any],
    dbc_text: str | None = None,
    resolved_arbitration_id: int | None = None,
) -> dict[str, Any] | str:
    """Resolve a ``can_command`` action's params into frame kwargs.

    Pure with respect to any database: encoding a database message needs its
    DBC text and (when known) the message's arbitration id passed in by the
    caller, so this stays unit-testable without a database. Returns an error
    string on failure so callers can report it directly.
    """
    channel = str(params.get("channel") or "can0").strip() or "can0"
    is_fd = bool(params.get("is_fd", False))
    is_extended_id = bool(params.get("is_extended_id", False))
    message = str(params.get("message") or "").strip()
    signals = params.get("signals") if isinstance(params.get("signals"), dict) else {}

    override_raw = str(params.get("arbitration_id", "")).strip()

    if dbc_text and message:
        checksum = str(params.get("checksum", "") or "")
        counter = None
        if checksum:
            from app.can import checksum as checksum_mod
            counter = checksum_mod.next_counter(f"cmd:{message}")
        try:
            data = dbc_encode(dbc_text, message, signals, counter=counter, checksum=checksum)
        except Exception as exc:  # cantools raises its own exception types
            return f"Could not encode {message}: {exc}"
        arbitration_id = resolved_arbitration_id
        if override_raw:
            try:
                arbitration_id = parse_arbitration_id(override_raw)
            except ValueError:
                return f"Invalid arbitration id: {override_raw}"
        if arbitration_id is None:
            return f"Could not determine an arbitration id for {message}"
    else:
        if not override_raw:
            return "No database/message or arbitration id configured"
        try:
            arbitration_id = parse_arbitration_id(override_raw)
        except ValueError:
            return f"Invalid arbitration id: {override_raw}"
        try:
            data = parse_data_bytes(str(params.get("data", "")))
        except ValueError:
            return f"Invalid data bytes: {params.get('data')}"

    if any(b < 0 or b > 0xFF for b in data):
        return "Data bytes must be 0x00-0xFF"

    return {
        "channel": channel,
        "frame": {
            "arbitration_id": arbitration_id,
            "data": list(data),
            "is_fd": is_fd,
            "is_extended_id": is_extended_id,
        },
    }
