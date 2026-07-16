"""The active vehicle's CAN database seam.

A vehicle profile links one or more CAN databases (its ``can_database_ids``
config key, set from the Databases page). When a vehicle is active, its linked
database is the one the app should decode traffic with, without the user
picking it again on every page. This module resolves that choice in one place
so every surface (the CAN Monitor, and anything else that decodes) can prefer
it automatically.

The pick itself is pure and lives in :mod:`dbc_catalog`
(``pick_active_database_id``); this module wires it to the profile store and
the ``CanDatabase`` table. Every lookup degrades to ``None`` if the stores are
unavailable, so a decode surface never crashes just because no vehicle is
active or the database is gone.
"""
from __future__ import annotations

from typing import Any

from . import dbc_catalog
from . import profiles as profiles_svc


def linked_database_ids(profile: dict | None) -> list[int]:
    """The database ids a profile has linked, as ints, filtering junk."""
    if not profile:
        return []
    ids = (profile.get("config") or {}).get("can_database_ids") or []
    out: list[int] = []
    for i in ids:
        try:
            out.append(int(i))
        except (TypeError, ValueError):
            continue
    return out


def active_linked_database_ids() -> list[int]:
    """The linked database ids for whichever vehicle is currently active."""
    try:
        active_id = profiles_svc.get_active_profile_id()
        if active_id is None:
            return []
        return linked_database_ids(profiles_svc.get_profile(active_id))
    except Exception:
        return []


def _available_ids() -> list[int]:
    from ..db import CanDatabase, session_scope
    with session_scope() as s:
        return [d.id for d in s.query(CanDatabase).all()]


def active_database_id() -> int | None:
    """The id of the database the active vehicle should decode with, or ``None``
    when no vehicle is active, none is linked, or the linked row is gone."""
    linked = active_linked_database_ids()
    if not linked:
        return None
    try:
        return dbc_catalog.pick_active_database_id(linked, _available_ids())
    except Exception:
        return None


def active_database() -> dict[str, Any] | None:
    """The active vehicle's decode database as a dict (``to_dict``), or ``None``."""
    db_id = active_database_id()
    if db_id is None:
        return None
    try:
        from ..db import CanDatabase, session_scope
        with session_scope() as s:
            d = s.get(CanDatabase, db_id)
            return d.to_dict() if d is not None else None
    except Exception:
        return None


def active_dbc_text() -> str | None:
    """The DBC text of the active vehicle's decode database, or ``None`` when
    there is nothing to decode with. Used to default decoding on surfaces that
    did not receive an explicit database selection."""
    db_id = active_database_id()
    if db_id is None:
        return None
    try:
        from ..db import CanDatabase, session_scope
        with session_scope() as s:
            d = s.get(CanDatabase, db_id)
            return (d.dbc_text or None) if d is not None else None
    except Exception:
        return None
