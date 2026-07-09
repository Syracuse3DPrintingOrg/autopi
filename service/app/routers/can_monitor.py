"""Live CAN bus monitor API: start/stop a channel reader and read its recent
frame history, optionally decoded against an imported DBC.

A thin REST wrapper over :mod:`app.can.monitor`'s background reader and ring
buffer.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..can import monitor as mon
from ..can.monitor import decode_record

router = APIRouter(prefix="/can/monitor", tags=["can-monitor"])


class MonitorRequest(BaseModel):
    channel: str = "can0"
    backend: str = "socketcan"


def _resolve_dbc_text(database_id: int) -> str | None:
    from ..db import session_scope
    from ..db.models import CanDatabase
    with session_scope() as s:
        database = s.get(CanDatabase, database_id)
        if database is None:
            raise HTTPException(404, "No such CAN database")
        return database.dbc_text


@router.post("/start")
def start(body: MonitorRequest):
    started = mon.start_monitor(body.channel, backend=body.backend)
    status = mon.get_monitor(body.channel, backend=body.backend).status()
    return {"ok": True, "started": started, "status": status}


@router.post("/stop")
def stop(body: MonitorRequest):
    stopped = mon.stop_monitor(body.channel, backend=body.backend)
    return {"ok": True, "stopped": stopped}


@router.get("/status")
def status():
    return {"channels": mon.list_statuses()}


@router.get("/frames")
def frames(channel: str = "can0", backend: str = "socketcan", database_id: int | None = None,
           obd2: bool | None = None):
    from ..config import settings
    obd2_overlay = settings.obd2_overlay if obd2 is None else bool(obd2)
    monitor = mon.get_monitor(channel, backend=backend)
    dbc_text = _resolve_dbc_text(database_id) if database_id else None
    records = []
    for record in monitor.frames():
        entry = dict(record)
        entry["decoded"] = (decode_record(record, dbc_text, obd2_overlay=obd2_overlay)
                            if (dbc_text or obd2_overlay) else None)
        records.append(entry)
    # Newest first: easier to watch live traffic without the table scrolling.
    records.reverse()
    return {"status": monitor.status(), "frames": records, "obd2_overlay": obd2_overlay}
