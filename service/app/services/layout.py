"""The layout model: which actions sit on which surface, in what order.

A **surface** is a place keys are shown. AutoPi ships two, both driven by the
same model: ``start`` (the full-screen web start menu) and ``streamdeck`` (the
physical deck). A surface's layout is a flat, ordered list of action ids, with
``None`` for a blank slot. The drag-and-drop editor rewrites that list; the
start page renders it as a CSS grid, and the deck controller runs it through
:mod:`app.services.deck_layout` for paging and rotation.

The whole layout is one atomic JSON state file so every worker and the deck
controller agree. Adding a surface is just adding a key here, which keeps the
model open for other products built on this platform.
"""
from __future__ import annotations

from typing import Optional

from ..config import settings
from ..services.state import StateFile

SURFACES = ("start", "streamdeck")


def _store() -> StateFile:
    return StateFile(settings.data_dir / "layout.json",
                     default={s: [] for s in SURFACES})


def get_layout(surface: str) -> list[Optional[str]]:
    if surface not in SURFACES:
        raise ValueError(f"Unknown surface: {surface}")
    doc = _store().read()
    raw = doc.get(surface, [])
    if not isinstance(raw, list):
        return []
    # Normalize: keep strings, turn anything falsy into an explicit blank.
    return [item if isinstance(item, str) and item else None for item in raw]


def get_all() -> dict[str, list[Optional[str]]]:
    return {s: get_layout(s) for s in SURFACES}


def set_layout(surface: str, action_ids: list[Optional[str]]) -> None:
    if surface not in SURFACES:
        raise ValueError(f"Unknown surface: {surface}")
    store = _store()
    doc = store.read()
    doc[surface] = [a if isinstance(a, str) and a else None for a in action_ids]
    store.write(doc)


def remove_action_everywhere(action_id: str) -> None:
    """Blank out a deleted action wherever it was placed, keeping positions."""
    store = _store()
    doc = store.read()
    changed = False
    for surface in SURFACES:
        items = doc.get(surface, [])
        if isinstance(items, list) and action_id in items:
            doc[surface] = [None if i == action_id else i for i in items]
            changed = True
    if changed:
        store.write(doc)
