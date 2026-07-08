"""Signal Finder API: statistically reverse engineer which CAN field carries
a signal a bench technician can see or trigger by hand, from a capture plus a
reference series they recorded while operating the real control.

A thin REST wrapper over :mod:`app.can.reverse`'s pure search and statistics;
the algorithm itself never touches the database or a capture file, only
plain lists of frame records and reference points.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..can import capture as cap
from ..can import reverse as rev
from ..db import CanDatabase, session_scope

router = APIRouter(prefix="/reverse", tags=["can-reverse"])


class ReferencePoint(BaseModel):
    t: float
    value: float
    available: bool = True


def _capture_or_404(capture_id: str) -> dict:
    capture = cap.get_capture(capture_id)
    if capture is None:
        raise HTTPException(404, "No such capture")
    return capture


def _frames_for_id(capture: dict, arbitration_id: int) -> list[dict]:
    return [f for f in capture.get("frames", []) if f.get("arbitration_id") == arbitration_id]


def _frames_by_id(capture: dict) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for frame in capture.get("frames", []):
        grouped.setdefault(frame.get("arbitration_id"), []).append(frame)
    return grouped


@router.get("/captures")
def list_captures():
    """Captures available to reverse engineer (the same inhale buffers the
    CAN console records)."""
    return {"captures": cap.list_captures()}


@router.get("/captures/{capture_id}/ids")
def list_ids(capture_id: str):
    """Arbitration ids present in one capture, with a frame count each, so
    the UI can populate an id picker without shipping every frame."""
    capture = _capture_or_404(capture_id)
    grouped = _frames_by_id(capture)
    ids = [
        {"arbitration_id": arb_id, "frame_count": len(frames)}
        for arb_id, frames in grouped.items()
    ]
    ids.sort(key=lambda entry: entry["arbitration_id"])
    return {"ids": ids}


class BitActivityIn(BaseModel):
    capture_id: str
    arbitration_id: int


@router.post("/bit-activity")
def bit_activity_route(body: BitActivityIn):
    capture = _capture_or_404(body.capture_id)
    frames = _frames_for_id(capture, body.arbitration_id)
    if not frames:
        raise HTTPException(404, "No frames with that arbitration id in this capture")
    return rev.bit_activity(frames)


class SurveyIn(BaseModel):
    capture_id: str
    reference: list[ReferencePoint]
    opts: dict = {}


@router.post("/survey")
def survey_route(body: SurveyIn):
    capture = _capture_or_404(body.capture_id)
    grouped = _frames_by_id(capture)
    reference = [p.model_dump() for p in body.reference]
    ranked = rev.survey(grouped, reference, body.opts or {})
    return {"ranked": ranked}


class BitsearchIn(BaseModel):
    capture_id: str
    arbitration_id: int
    reference: list[ReferencePoint]
    opts: dict = {}


@router.post("/bitsearch")
def bitsearch_route(body: BitsearchIn):
    capture = _capture_or_404(body.capture_id)
    frames = _frames_for_id(capture, body.arbitration_id)
    if not frames:
        raise HTTPException(404, "No frames with that arbitration id in this capture")
    reference = [p.model_dump() for p in body.reference]
    candidates = rev.bitsearch(frames, reference, body.opts or {})
    return {"candidates": candidates}


class SaveIn(BaseModel):
    database_id: int
    name: str
    candidate: dict
    message_name: str | None = None
    unit: str = ""
    comment: str = ""


@router.post("/save")
def save_route(body: SaveIn):
    if not body.name.strip():
        raise HTTPException(400, "Signal needs a name")
    derived = rev.derive_scale_offset(body.candidate)
    definition = rev.to_dbc_signal(body.name.strip(), derived, unit=body.unit, comment=body.comment)
    with session_scope() as s:
        database = s.get(CanDatabase, body.database_id)
        if database is None:
            raise HTTPException(404, "No such CAN database")
        try:
            rev.add_signal_to_database(
                s, database, int(body.candidate["arbitration_id"]), body.name.strip(),
                definition, message_name=body.message_name,
            )
        except Exception as exc:
            raise HTTPException(400, f"Could not save signal: {exc}")
        s.flush()
        return {"ok": True, "database": database.to_dict(with_messages=True),
                "candidate": derived}
