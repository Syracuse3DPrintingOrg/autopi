"""Configured CAN interfaces: which backend and settings a channel name uses.

A "channel" like ``can0`` is just a string until something tells the app
which python-can backend to open it with, and at what bitrate. That mapping
is cross-surface state (the settings UI writes it, ``routers/can_dbc.py``
and any CAN action read it), so it lives in the same atomic JSON state file
pattern as the layout and the active profile (see ``services/state.py``),
not a database table.

Each entry:

- ``id``: a stable string key (the channel name, e.g. ``can0``), unique
  per interface.
- ``backend``: one of ``registry.CONFIGURABLE_BACKENDS``.
- ``channel``: the value passed to the backend (``can0`` for socketcan,
  ``PCAN_USBBUS1`` for pcan, a numeric index for vector, any name for
  virtual).
- ``bitrate``: arbitration bitrate in bit/s.
- ``fd``: whether to open the bus in CAN-FD mode.
- ``data_bitrate``: CAN-FD data-phase bitrate in bit/s, ignored when
  ``fd`` is False.
- ``label``: an optional human-friendly name shown in the UI.
"""
from __future__ import annotations

from ..config import settings
from .state import StateFile

DEFAULT_BITRATE = 500000


def _store() -> StateFile:
    return StateFile(settings.data_dir / "can-interfaces.json", default={"interfaces": []})


def list_interfaces() -> list[dict]:
    return _store().read().get("interfaces", [])


def get_interface(interface_id: str) -> dict | None:
    for i in list_interfaces():
        if i.get("id") == interface_id:
            return i
    return None


def _normalize(entry: dict) -> dict:
    return {
        "id": str(entry["id"]),
        "backend": entry.get("backend") or "socketcan",
        "channel": str(entry.get("channel") or entry["id"]),
        "bitrate": int(entry.get("bitrate") or DEFAULT_BITRATE),
        "fd": bool(entry.get("fd", False)),
        "data_bitrate": int(entry["data_bitrate"]) if entry.get("data_bitrate") else None,
        "label": entry.get("label") or "",
    }


def save_interface(entry: dict) -> dict:
    """Create or replace the interface with this ``id`` (upsert by id)."""
    if not entry.get("id"):
        raise ValueError("An interface id (the channel name) is required")
    normalized = _normalize(entry)
    store = _store()
    doc = store.read()
    interfaces = [i for i in doc.get("interfaces", []) if i.get("id") != normalized["id"]]
    interfaces.append(normalized)
    doc["interfaces"] = interfaces
    store.write(doc)
    return normalized


def delete_interface(interface_id: str) -> bool:
    store = _store()
    doc = store.read()
    before = doc.get("interfaces", [])
    after = [i for i in before if i.get("id") != interface_id]
    if len(after) == len(before):
        return False
    doc["interfaces"] = after
    store.write(doc)
    return True
