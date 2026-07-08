"""Logic rules and the logic runtime.

The runtime runs the PLC-like engine on a scan loop against live inputs (CAN
signals decoded via a DBC, GPIO pins, constants) and fires the action ids the
rules ask for. This is what lets a CAN signal drive an output, or a physical
input trigger a CAN command (Phase 3).
"""
from __future__ import annotations

import time

from fastapi import APIRouter
from pydantic import BaseModel

from ..logic import runtime as rt
from ..logic.store import load_rules, save_rules
from ..logic.rule import Rule

router = APIRouter(prefix="/logic", tags=["logic"])


@router.get("/rules")
def list_rules():
    return {"rules": [rule.to_dict() for rule in load_rules()]}


class RulesIn(BaseModel):
    rules: list[dict]


@router.put("/rules")
def set_rules(body: RulesIn):
    save_rules([Rule.from_dict(r) for r in body.rules])
    return {"ok": True, "count": len(body.rules)}


@router.get("/runtime")
def runtime_state():
    return {"running": rt.runtime.running(), "config": rt.get_config(),
            "last_result": rt.runtime.last_result}


class RuntimeConfigIn(BaseModel):
    scan_ms: int | None = None
    inputs: list[dict] | None = None


@router.put("/runtime")
def runtime_config(body: RuntimeConfigIn):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    return {"ok": True, "config": rt.set_config(updates)}


@router.post("/runtime/start")
def runtime_start():
    rt.runtime.start()
    return {"ok": True, "running": rt.runtime.running()}


@router.post("/runtime/stop")
def runtime_stop():
    rt.runtime.stop()
    return {"ok": True, "running": rt.runtime.running()}


@router.post("/runtime/scan-once")
def runtime_scan_once():
    return {"ok": True, "result": rt.runtime.scan_once(time.time())}
