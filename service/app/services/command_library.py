"""A shared, vehicle-independent library of saved CAN commands.

A command found with the Signal Finder (or entered by hand) can be saved to the
active vehicle, to this shared library, or both. The library is where reusable
commands live so they can be dropped onto any vehicle's control later. It is
small cross-surface state, kept as one atomic JSON file under data_dir, the same
pattern as the active-vehicle selection and timers.

A command is a plain dict mirroring the ``can`` driver's params, so a library
entry can be applied to a control or an action without translation:

    {channel, arbitration_id, data, is_fd, is_extended_id, period_ms,
     overlay_byte, overlay_mask, overlay_value}
"""
from __future__ import annotations

import time
from typing import Any

from ..config import settings
from .state import StateFile


def _store() -> StateFile:
    return StateFile(settings.data_dir / "command-library.json", default={"commands": []})


def normalize_command(command: dict | None) -> dict:
    """Keep only the known command fields, so callers can pass a whole form or a
    Signal Finder result and the stored shape stays predictable. Pure."""
    c = dict(command or {})
    out: dict[str, Any] = {
        "channel": str(c.get("channel") or "can0"),
        "arbitration_id": str(c.get("arbitration_id") or ""),
        "data": str(c.get("data") or ""),
        "is_fd": bool(c.get("is_fd", False)),
        "is_extended_id": bool(c.get("is_extended_id", False)),
        "period_ms": int(c.get("period_ms") or 0),
    }
    for key in ("overlay_byte", "overlay_mask", "overlay_value"):
        if c.get(key) not in (None, ""):
            out[key] = c[key]
    return out


def list_commands() -> list[dict]:
    return list(_store().read().get("commands", []))


def add_command(name: str, command: dict) -> dict:
    """Save a command under a name. Returns the stored entry (with a new id)."""
    store = _store()
    doc = store.read()
    commands = list(doc.get("commands", []))
    next_id = max((int(c.get("id", 0)) for c in commands), default=0) + 1
    entry = {"id": next_id, "name": (name or "").strip() or f"Command {next_id}",
             "command": normalize_command(command), "created": time.time()}
    commands.append(entry)
    doc["commands"] = commands
    store.write(doc)
    return entry


def get_command(command_id: int) -> dict | None:
    return next((c for c in list_commands() if int(c.get("id", 0)) == int(command_id)), None)


def delete_command(command_id: int) -> bool:
    store = _store()
    doc = store.read()
    commands = list(doc.get("commands", []))
    kept = [c for c in commands if int(c.get("id", 0)) != int(command_id)]
    if len(kept) == len(commands):
        return False
    doc["commands"] = kept
    store.write(doc)
    return True
