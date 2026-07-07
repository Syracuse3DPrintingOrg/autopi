"""The local database.

Actions, layouts, and settings live in small atomic JSON files (see
``services/state.py``); this package adds a SQLite database, alongside that
JSON state, for the platform's larger and more structured records: actions,
vehicle profiles, CAN messages, and logic rules. It is additive, not a
replacement: the JSON action registry keeps working unchanged, and nothing
here deletes or resets existing data. ``init_db()`` only ever calls
``Base.metadata.create_all``, so an upgrade adds new tables and columns
without touching a production install's data.

Modules:

- ``models``: the SQLAlchemy declarative models.
- ``engine``: the engine, session factory, and ``init_db()``.
- ``importexport``: serialize the whole database (or one profile) to a plain
  JSON dict, and load one back with an upsert that never wipes existing rows.
"""
from __future__ import annotations

from .engine import get_session, init_db, session_scope
from .models import Action, Base, CanDatabase, CanMessage, CanSignal, LogicRule, Profile

__all__ = [
    "Base",
    "Action",
    "Profile",
    "CanDatabase",
    "CanMessage",
    "CanSignal",
    "LogicRule",
    "init_db",
    "get_session",
    "session_scope",
]
