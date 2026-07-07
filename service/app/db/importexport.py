"""Serialize the database to a plain JSON dict, and load one back.

Import is always an upsert: a record with an id that already exists gets its
fields updated, one with a new or missing id gets inserted, and nothing
already in the database is ever deleted by an import. That matches the rest
of the app's rule that an existing install's data is production and must
survive an update.

The dict shape is deliberately flat and stable so it works as a file format:

```
{
    "version": 1,
    "actions": [...],
    "profiles": [...],
    "can_messages": [...],   # each with a nested "signals" list
    "logic_rules": [...],
}
```

Every function here takes a session the caller owns (opened with
``db.session_scope()``), so this module has no I/O of its own and stays easy
to unit-test with an in-memory SQLite session.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .models import Action, CanDatabase, CanMessage, CanSignal, LogicRule, Profile

FORMAT_VERSION = 1

_EMPTY: dict[str, list] = {
    "actions": [],
    "profiles": [],
    "can_messages": [],
    "logic_rules": [],
}


def export_all(session: Session) -> dict[str, Any]:
    """Serialize every table to a JSON-safe dict."""
    return {
        "version": FORMAT_VERSION,
        "actions": [a.to_dict() for a in session.query(Action).all()],
        "profiles": [p.to_dict() for p in session.query(Profile).all()],
        "can_databases": [_database_export(d) for d in session.query(CanDatabase).all()],
        "can_messages": [m.to_dict() for m in session.query(CanMessage).all()],
        "logic_rules": [r.to_dict() for r in session.query(LogicRule).all()],
    }


def _database_export(d: CanDatabase) -> dict[str, Any]:
    """A CanDatabase serialized for export, including the DBC text so decode
    still works after an import (to_dict omits the large text for the API)."""
    out = d.to_dict()
    out.pop("message_count", None)
    out["dbc_text"] = d.dbc_text or ""
    return out


def export_profile(session: Session, profile_id: int) -> dict[str, Any] | None:
    """Serialize a single profile. Returns None if no such profile exists."""
    profile = session.get(Profile, profile_id)
    if profile is None:
        return None
    return {
        "version": FORMAT_VERSION,
        "actions": [],
        "profiles": [profile.to_dict()],
        "can_databases": [],
        "can_messages": [],
        "logic_rules": [],
    }


def import_data(session: Session, data: dict[str, Any]) -> dict[str, int]:
    """Upsert every record in ``data`` into the database. Never deletes.

    Returns a count of records touched per table, for a friendly response.
    """
    if not isinstance(data, dict):
        raise ValueError("Import payload must be a JSON object")

    counts = {"actions": 0, "profiles": 0, "can_databases": 0,
              "can_messages": 0, "can_signals": 0, "logic_rules": 0}

    for item in data.get("actions") or []:
        _upsert_action(session, item)
        counts["actions"] += 1

    for item in data.get("profiles") or []:
        _upsert_profile(session, item)
        counts["profiles"] += 1

    # Databases before messages so a message's database_id has a target.
    for item in data.get("can_databases") or []:
        _upsert_can_database(session, item)
        counts["can_databases"] += 1

    for item in data.get("can_messages") or []:
        signal_count = _upsert_can_message(session, item)
        counts["can_messages"] += 1
        counts["can_signals"] += signal_count

    for item in data.get("logic_rules") or []:
        _upsert_logic_rule(session, item)
        counts["logic_rules"] += 1

    return counts


def _upsert_action(session: Session, item: dict[str, Any]) -> Action:
    action_id = item.get("id")
    if not action_id:
        raise ValueError("An action in the import payload has no id")
    obj = session.get(Action, action_id)
    if obj is None:
        obj = Action(id=action_id)
        session.add(obj)
    obj.label = item.get("label", obj.label or "")
    obj.driver = item.get("driver", obj.driver or "shell")
    obj.params = item.get("params", {}) or {}
    obj.icon = item.get("icon", obj.icon or "bi-lightning-charge")
    obj.color = item.get("color", obj.color or "#334155")
    obj.category = item.get("category", obj.category or "Actions")
    obj.members = item.get("members", []) or []
    obj.deck_only = bool(item.get("deck_only", obj.deck_only or False))
    return obj


def _upsert_profile(session: Session, item: dict[str, Any]) -> Profile:
    profile_id = item.get("id")
    obj = session.get(Profile, profile_id) if profile_id is not None else None
    if obj is None:
        obj = Profile(id=profile_id) if profile_id is not None else Profile()
        session.add(obj)
    obj.name = item.get("name", obj.name or "")
    obj.year = item.get("year", obj.year)
    obj.make = item.get("make", obj.make or "")
    obj.model = item.get("model", obj.model or "")
    obj.vin = item.get("vin", obj.vin or "")
    obj.config = item.get("config", {}) or {}
    return obj


def _upsert_can_database(session: Session, item: dict[str, Any]) -> CanDatabase:
    db_id = item.get("id")
    obj = session.get(CanDatabase, db_id) if db_id is not None else None
    if obj is None:
        obj = CanDatabase(id=db_id) if db_id is not None else CanDatabase()
        session.add(obj)
    obj.name = item.get("name", obj.name or "")
    obj.source = item.get("source", obj.source or "")
    obj.license = item.get("license", obj.license or "")
    obj.version = item.get("version", obj.version or "")
    obj.make = item.get("make", obj.make or "")
    obj.model = item.get("model", obj.model or "")
    obj.year = item.get("year", obj.year)
    obj.notes = item.get("notes", obj.notes or "")
    obj.dbc_text = item.get("dbc_text", obj.dbc_text or "")
    session.flush()
    return obj


def _upsert_can_message(session: Session, item: dict[str, Any]) -> int:
    message_id = item.get("id")
    obj = session.get(CanMessage, message_id) if message_id is not None else None
    if obj is None:
        obj = CanMessage(id=message_id) if message_id is not None else CanMessage()
        session.add(obj)
    obj.arbitration_id = int(item.get("arbitration_id", obj.arbitration_id or 0))
    obj.name = item.get("name", obj.name or "")
    obj.is_fd = bool(item.get("is_fd", obj.is_fd or False))
    if "database_id" in item:
        obj.database_id = item.get("database_id")
    # Flush so a brand-new message has an id before its signals reference it.
    session.flush()

    signal_count = 0
    for sig_item in item.get("signals") or []:
        _upsert_can_signal(session, obj.id, sig_item)
        signal_count += 1
    return signal_count


def _upsert_can_signal(session: Session, message_id: int, item: dict[str, Any]) -> CanSignal:
    signal_id = item.get("id")
    obj = session.get(CanSignal, signal_id) if signal_id is not None else None
    if obj is None:
        obj = CanSignal(id=signal_id, message_id=message_id) if signal_id is not None \
            else CanSignal(message_id=message_id)
        session.add(obj)
    obj.message_id = message_id
    obj.name = item.get("name", obj.name or "")
    obj.definition = item.get("definition", {}) or {}
    return obj


def _upsert_logic_rule(session: Session, item: dict[str, Any]) -> LogicRule:
    rule_id = item.get("id")
    obj = session.get(LogicRule, rule_id) if rule_id is not None else None
    if obj is None:
        obj = LogicRule(id=rule_id) if rule_id is not None else LogicRule()
        session.add(obj)
    obj.name = item.get("name", obj.name or "")
    obj.definition = item.get("definition", {}) or {}
    return obj
