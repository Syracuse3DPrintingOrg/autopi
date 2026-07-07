"""DBC database support, built on cantools.

The open-source CAN world ships its message and signal definitions as DBC
files (opendbc from comma.ai is the largest open collection). This module
parses a DBC with `cantools <https://github.com/cantools/cantools>`_ (MIT),
imports its messages and signals into the local database as a named
``CanDatabase``, and decodes/encodes frames against it.

cantools is an optional dependency: importing a DBC needs it, but the rest of
the app runs without it. ``available()`` reports whether it is installed.

Two representations are kept per imported database:

- the parsed messages and signals in the DB (for listing, search, and editing,
  and so a user can add custom messages and commands), and
- the original DBC text on the ``CanDatabase`` row, so cantools can decode and
  encode frames against the database exactly, without us reimplementing DBC
  bit math.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from ..db.models import CanDatabase, CanMessage, CanSignal


def available() -> bool:
    try:
        import cantools  # noqa: F401
        return True
    except Exception:
        return False


def _load(dbc_text: str):
    import cantools
    return cantools.database.load_string(dbc_text, database_format="dbc")


@lru_cache(maxsize=64)
def _load_cached(dbc_text: str):
    """cantools Database for a DBC text, cached by the text itself."""
    return _load(dbc_text)


def _signal_to_definition(sig) -> dict[str, Any]:
    """Turn a cantools Signal into our JSON decode definition."""
    return {
        "start": sig.start,
        "length": sig.length,
        "byte_order": sig.byte_order,          # "little_endian" | "big_endian"
        "is_signed": bool(sig.is_signed),
        "scale": sig.scale,
        "offset": sig.offset,
        "minimum": sig.minimum,
        "maximum": sig.maximum,
        "unit": sig.unit or "",
        "is_float": bool(getattr(sig, "is_float", False)),
        "choices": {int(k): str(v) for k, v in (sig.choices or {}).items()},
        "comment": sig.comment or "",
        "receivers": list(sig.receivers or []),
        "is_multiplexer": bool(getattr(sig, "is_multiplexer", False)),
        "multiplexer_ids": list(getattr(sig, "multiplexer_ids", []) or []),
    }


def parse_dbc(dbc_text: str) -> list[dict[str, Any]]:
    """Parse DBC text into a list of message dicts (pure, no DB writes).

    Raises if cantools is missing or the DBC does not parse, so callers can
    report a clear error to the user.
    """
    db = _load(dbc_text)
    messages = []
    for msg in db.messages:
        messages.append({
            "name": msg.name,
            "arbitration_id": msg.frame_id,
            "is_extended": bool(msg.is_extended_frame),
            "is_fd": bool(getattr(msg, "is_fd", False)),
            "length": msg.length,
            "senders": list(msg.senders or []),
            "comment": msg.comment or "",
            "signals": [
                {"name": sig.name, "definition": _signal_to_definition(sig)}
                for sig in msg.signals
            ],
        })
    return messages


def import_dbc(session, name: str, dbc_text: str, *, source: str = "upload",
               license: str = "", version: str = "", make: str = "",
               model: str = "", year: int | None = None, notes: str = "") -> CanDatabase:
    """Parse a DBC and store it as a new CanDatabase with its messages/signals."""
    parsed = parse_dbc(dbc_text)
    database = CanDatabase(
        name=name, source=source, license=license, version=version,
        make=make, model=model, year=year, notes=notes, dbc_text=dbc_text,
    )
    session.add(database)
    session.flush()  # assign database.id
    for m in parsed:
        message = CanMessage(
            database_id=database.id,
            arbitration_id=m["arbitration_id"],
            name=m["name"],
            is_fd=m["is_fd"],
        )
        session.add(message)
        session.flush()
        for s in m["signals"]:
            session.add(CanSignal(message_id=message.id, name=s["name"],
                                  definition=s["definition"]))
    session.flush()
    return database


def decode(dbc_text: str, arbitration_id: int, data: bytes) -> dict[str, Any]:
    """Decode a frame's data into named signal values using cantools."""
    db = _load_cached(dbc_text)
    decoded = db.decode_message(arbitration_id, bytes(data))
    # cantools may return NamedSignalValue objects; make them JSON-friendly.
    return {k: (v.value if hasattr(v, "value") else v) for k, v in decoded.items()}


def encode(dbc_text: str, message: str | int, signals: dict[str, Any]) -> list[int]:
    """Encode named signal values into frame data bytes using cantools.

    ``message`` may be a message name or an arbitration id.
    """
    db = _load_cached(dbc_text)
    data = db.encode_message(message, signals)
    return list(bytes(data))
