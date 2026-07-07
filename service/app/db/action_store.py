"""A DB-backed action store, kept alongside the live JSON action registry.

``actions/registry.py`` still reads and writes ``actions.json`` today and
this module does not change that; it exists so a future switch to the
database (or an external management tool) has a ready-made, tested store to
point at, without having to invent the schema at that time. The functions
mirror the registry's shape (``ActionSpec``-like dicts) so swapping the
registry's storage backend later is a small, mechanical change.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .models import Action


def list_actions(session: Session) -> list[dict[str, Any]]:
    return [a.to_dict() for a in session.query(Action).order_by(Action.id).all()]


def get_action(session: Session, action_id: str) -> dict[str, Any] | None:
    obj = session.get(Action, action_id)
    return obj.to_dict() if obj is not None else None


def upsert_action(session: Session, spec: dict[str, Any]) -> dict[str, Any]:
    action_id = spec.get("id")
    if not action_id:
        raise ValueError("An action needs an id")
    obj = session.get(Action, action_id)
    if obj is None:
        obj = Action(id=action_id)
        session.add(obj)
    obj.label = spec.get("label", obj.label or "")
    obj.driver = spec.get("driver", obj.driver or "shell")
    obj.params = spec.get("params", {}) or {}
    obj.icon = spec.get("icon", obj.icon or "bi-lightning-charge")
    obj.color = spec.get("color", obj.color or "#334155")
    obj.category = spec.get("category", obj.category or "Actions")
    obj.members = spec.get("members", []) or []
    obj.deck_only = bool(spec.get("deck_only", obj.deck_only or False))
    session.flush()
    return obj.to_dict()


def delete_action(session: Session, action_id: str) -> bool:
    obj = session.get(Action, action_id)
    if obj is None:
        return False
    session.delete(obj)
    return True
