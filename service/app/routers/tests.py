"""Automated test sequence API: CRUD sequences, run one, resolve an operator
confirmation, and read back live status and the final report.

A thin REST wrapper over :mod:`app.testseq`: persistence is
``testseq.store``, execution is the module-level active
:class:`~app.testseq.runner.Runner` from ``testseq.runner``. Only one
sequence runs at a time, matching a test bench validating one vehicle.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import testseq
from ..testseq.model import Sequence

router = APIRouter(prefix="/tests", tags=["tests"])


class StepIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    type: str = "send"
    label: str = ""
    channel: str = "can0"
    backend: str = "socketcan"
    arbitration_id: str = ""
    data: str = ""
    database_id: int | None = None
    message: str | int | None = None
    signals: dict = Field(default_factory=dict)
    is_fd: bool = False
    is_extended_id: bool = False
    timeout_ms: int = 2000
    signal_name: str = ""
    op: str = "=="
    value: object = None
    prompt_text: str = ""
    delay_ms: int = 0
    action_id: str = ""


class SequenceIn(BaseModel):
    name: str = ""
    profile_id: int | None = None
    steps: list[StepIn] = Field(default_factory=list)


class ConfirmIn(BaseModel):
    passed: bool
    note: str = ""


def _validate_steps(steps: list[StepIn]) -> None:
    for step in steps:
        if step.type not in testseq.STEP_TYPES:
            raise HTTPException(400, f"Unknown step type: {step.type}")
        if step.type in ("send", "expect") and not step.arbitration_id and not (
            step.type == "send" and step.database_id and step.message
        ):
            raise HTTPException(400, f"Step {step.id}: an arbitration id is required")
        if step.type == "expect" and step.signal_name and step.op not in testseq.COMPARE_OPS:
            raise HTTPException(400, f"Step {step.id}: unknown comparison op {step.op}")
        if step.type == "action" and not step.action_id:
            raise HTTPException(400, f"Step {step.id}: an action id is required")


@router.get("")
def list_sequences(profile_id: int | None = None):
    return {"sequences": testseq.list_sequences(profile_id)}


@router.get("/{sequence_id}")
def get_sequence(sequence_id: str):
    doc = testseq.get_sequence(sequence_id)
    if doc is None:
        raise HTTPException(404, "No such test sequence")
    return doc


@router.post("")
def create_sequence(body: SequenceIn):
    _validate_steps(body.steps)
    created = testseq.create_sequence(body.model_dump())
    return {"ok": True, "sequence": created}


@router.put("/{sequence_id}")
def update_sequence(sequence_id: str, body: SequenceIn):
    if testseq.get_sequence(sequence_id) is None:
        raise HTTPException(404, "No such test sequence")
    _validate_steps(body.steps)
    updated = testseq.update_sequence(sequence_id, body.model_dump())
    return {"ok": True, "sequence": updated}


@router.delete("/{sequence_id}")
def delete_sequence(sequence_id: str):
    if not testseq.delete_sequence(sequence_id):
        raise HTTPException(404, "No such test sequence")
    return {"ok": True}


@router.post("/{sequence_id}/run")
def run(sequence_id: str):
    doc = testseq.get_sequence(sequence_id)
    if doc is None:
        raise HTTPException(404, "No such test sequence")
    sequence = Sequence.from_dict(doc)
    if not sequence.steps:
        raise HTTPException(400, "This sequence has no steps to run")
    runner = testseq.run_sequence(sequence)
    return {"ok": True, "status": runner.status()}


@router.get("/run/status")
def run_status():
    runner = testseq.get_active()
    if runner is None:
        raise HTTPException(404, "No test run in progress")
    return runner.status()


@router.post("/run/confirm")
def run_confirm(body: ConfirmIn):
    runner = testseq.get_active()
    if runner is None:
        raise HTTPException(404, "No test run in progress")
    resolved = runner.resolve_prompt(body.passed, body.note)
    if not resolved:
        raise HTTPException(400, "No confirmation is pending")
    return {"ok": True, "status": runner.status()}


@router.get("/run/report")
def run_report():
    runner = testseq.get_active()
    if runner is None:
        raise HTTPException(404, "No test run in progress")
    return runner.report()
