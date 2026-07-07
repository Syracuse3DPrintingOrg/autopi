"""Read-only view of the configured logic rules (the Phase 2 PLC-like engine).

This is intentionally small: it just reports what's stored today
(``logic.json`` through ``app.logic.store``). Running the engine, wiring its
scan cycle to real inputs, and editing rules from the UI are later work.
"""
from __future__ import annotations

from fastapi import APIRouter

from ..logic.store import load_rules

router = APIRouter(prefix="/logic", tags=["logic"])


@router.get("/rules")
def list_rules():
    return {"rules": [rule.to_dict() for rule in load_rules()]}
