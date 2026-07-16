"""CAN transmit simulation API: periodic and one-shot signal playback.

A thin REST wrapper over :mod:`app.can.simulation`'s transmit list and
background scheduler: CRUD on transmit entries, enable/disable, a one-shot
send, and start/stop for the scheduler thread.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..can import simulation as sim
from ..can.base import parse_arbitration_id

router = APIRouter(prefix="/can/sim", tags=["can-sim"])


class SimEntryIn(BaseModel):
    name: str = ""
    channel: str = "can0"
    backend: str = "socketcan"
    arbitration_id: str = Field(..., description="Hex ('0x100') or decimal")
    data: str = ""
    database_id: int | None = None
    message: str | int | None = None
    signals: dict = Field(default_factory=dict)
    period_ms: int = Field(0, ge=0)
    is_fd: bool = False
    is_extended_id: bool = False
    enabled: bool = True


def _to_entry_dict(body: SimEntryIn) -> dict:
    try:
        arbitration_id = parse_arbitration_id(body.arbitration_id)
    except ValueError as exc:
        raise HTTPException(400, f"Bad arbitration id: {exc}")
    entry = body.model_dump()
    entry["arbitration_id"] = arbitration_id
    return entry


def _resolve_dbc_text(database_id: int) -> str | None:
    from ..db import session_scope
    from ..db.models import CanDatabase
    with session_scope() as s:
        database = s.get(CanDatabase, database_id)
        if database is None:
            raise HTTPException(404, "No such CAN database")
        return database.dbc_text


def _validate_entry(entry: dict) -> None:
    """Best-effort validation at save time, using a DBC if one is configured."""
    dbc_text = _resolve_dbc_text(entry["database_id"]) if entry.get("database_id") else None
    try:
        sim.build_frame(entry, dbc_text)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("")
def list_entries():
    return {"entries": sim.list_entries(), "running": sim.engine.is_running()}


@router.get("/{entry_id}")
def get_entry(entry_id: str):
    entry = sim.get_entry(entry_id)
    if entry is None:
        raise HTTPException(404, "No such transmit entry")
    return entry


@router.post("")
def create_entry(body: SimEntryIn):
    entry = _to_entry_dict(body)
    _validate_entry(entry)
    created = sim.create_entry(entry)
    return {"ok": True, "entry": created}


@router.put("/{entry_id}")
def update_entry(entry_id: str, body: SimEntryIn):
    if sim.get_entry(entry_id) is None:
        raise HTTPException(404, "No such transmit entry")
    entry = _to_entry_dict(body)
    _validate_entry(entry)
    updated = sim.update_entry(entry_id, entry)
    return {"ok": True, "entry": updated}


@router.delete("/{entry_id}")
def delete_entry(entry_id: str):
    if not sim.delete_entry(entry_id):
        raise HTTPException(404, "No such transmit entry")
    return {"ok": True}


@router.post("/{entry_id}/enable")
def enable_entry(entry_id: str):
    entry = sim.set_enabled(entry_id, True)
    if entry is None:
        raise HTTPException(404, "No such transmit entry")
    return {"ok": True, "entry": entry}


@router.post("/{entry_id}/disable")
def disable_entry(entry_id: str):
    entry = sim.set_enabled(entry_id, False)
    if entry is None:
        raise HTTPException(404, "No such transmit entry")
    return {"ok": True, "entry": entry}


@router.post("/{entry_id}/send")
def send_entry(entry_id: str):
    ok, error = sim.engine.send_once(entry_id)
    if error == "No such transmit entry":
        raise HTTPException(404, error)
    return {"ok": ok, "error": error}


@router.post("/scheduler/start")
def start_scheduler():
    started = sim.engine.start()
    return {"ok": True, "running": True, "started": started}


@router.post("/scheduler/stop")
def stop_scheduler():
    stopped = sim.engine.stop()
    return {"ok": True, "running": False, "stopped": stopped}


@router.get("/scheduler/status")
def scheduler_status():
    return {"running": sim.engine.is_running()}


class FuzzIn(BaseModel):
    channel: str = "can0"
    arbitration_id: str
    data: str = ""
    fuzz_bytes: list[int] = Field(default_factory=list)
    count: int = 100
    period_ms: int = 50
    is_fd: bool = False
    is_extended_id: bool = False


@router.post("/fuzz")
def fuzz_route(body: FuzzIn):
    """Send a bounded run of frames on one id with chosen bytes randomized each
    frame, and return exactly what was sent so a reaction can be traced back to
    the frame that caused it. Transmits on a live bus, so it is deliberate."""
    from ..can.base import parse_data_bytes
    from ..services import can_tx
    try:
        arbitration_id = parse_arbitration_id(body.arbitration_id)
    except ValueError as exc:
        raise HTTPException(400, f"Bad arbitration id: {exc}")
    try:
        template = parse_data_bytes(body.data) if body.data.strip() else [0] * 8
    except ValueError as exc:
        raise HTTPException(400, f"Bad data bytes: {exc}")
    sent = can_tx.fuzz(body.channel, arbitration_id, template, body.fuzz_bytes,
                       count=body.count, period_ms=body.period_ms,
                       is_fd=body.is_fd, is_extended_id=body.is_extended_id)
    if not sent:
        return {"ok": False, "error": f"Could not send on {body.channel} "
                "(interface not available or not accepting frames)."}
    return {"ok": True, "count": len(sent),
            "sent": [" ".join(f"{b:02X}" for b in s["data"]) for s in sent]}
