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
    try:
        return cantools.database.load_string(dbc_text, database_format="dbc")
    except Exception:
        # Real-world DBCs (e.g. opendbc) sometimes have quirks strict parsing
        # rejects; retry leniently so they still import and decode.
        return cantools.database.load_string(dbc_text, database_format="dbc", strict=False)


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


def encode(dbc_text: str, message: str | int, signals: dict[str, Any],
           counter: int | None = None, checksum: str = "") -> list[int]:
    """Encode named signal values into frame data bytes using cantools.

    ``message`` may be a message name or an arbitration id. Signals the caller
    does not set are filled with 0 (or their first named value), so a command
    key that sets a single button does not have to spell out every other signal
    in the message.

    When ``counter`` is given and the message has a COUNTER signal, it is set to
    that value; when ``checksum`` names an algorithm (e.g. "chrysler"), the
    checksum byte is recomputed so a real module accepts the frame.
    """
    from . import checksum as checksum_mod
    db = _load_cached(dbc_text)
    msg = db.get_message_by_name(message) if isinstance(message, str) else db.get_message_by_frame_id(message)
    full = dict(signals or {})
    signal_names = {sig.name for sig in msg.signals}
    unknown = set(full) - signal_names
    if unknown:
        raise KeyError(f"Unknown signal(s) for {msg.name}: {', '.join(sorted(unknown))}")
    if counter is not None and "COUNTER" in signal_names:
        full["COUNTER"] = int(counter) % 16
    for sig in msg.signals:
        if sig.name not in full:
            # Fill an unset signal so its raw value is 0 (an empty frame for
            # those bits). For a signal with an offset, physical 0 can be out of
            # the field's range, so use the physical value that maps to raw 0.
            full[sig.name] = sig.offset if getattr(sig, "offset", None) is not None else 0
    # strict=False: real DBCs (e.g. opendbc) often carry placeholder [0|1]
    # signal ranges that would wrongly reject a valid physical value.
    data = list(bytes(db.encode_message(msg.frame_id, full, strict=False)))
    return checksum_mod.finalize(checksum, data, address=msg.frame_id)
