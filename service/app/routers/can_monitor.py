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


@router.post("/clear")
def clear(body: MonitorRequest):
    """Forget the traffic seen so far on this channel, including the by-id table,
    so the next look at the bus starts clean."""
    mon.get_monitor(body.channel, backend=body.backend).clear()
    return {"ok": True}


@router.get("/ids")
def ids(channel: str = "can0", backend: str = "socketcan", database_id: int | None = None,
        obd2: bool | None = None):
    """Every arbitration id seen on this channel with the message it last sent.

    Unlike ``/frames`` (the recent-frame ring buffer, where an id that stops
    transmitting scrolls out within a second on a busy bus), this keeps one row
    per id for as long as the monitor runs, so a quiet id stays visible with its
    last payload. That is what makes it usable for watching which byte moves when
    you operate a control."""
    from ..config import settings
    from ..services import can_databases as can_db_svc
    obd2_overlay = settings.obd2_overlay if obd2 is None else bool(obd2)
    monitor = mon.get_monitor(channel, backend=backend)
    if database_id:
        dbc_text = _resolve_dbc_text(database_id)
    else:
        dbc_text = can_db_svc.active_dbc_text()
    # Parse the DBC once per request rather than once per id (this endpoint is
    # polled on the same 500ms cadence as /frames).
    from ..can import dbc as dbc_mod
    parsed_db = dbc_mod.load(dbc_text) if dbc_text else None
    rows = []
    for record in monitor.latest_by_id():
        entry = dict(record)
        entry["decoded"] = (decode_record(record, dbc_text, obd2_overlay=obd2_overlay, db=parsed_db)
                            if (parsed_db is not None or obd2_overlay) else None)
        rows.append(entry)
    return {"status": monitor.status(), "ids": rows, "obd2_overlay": obd2_overlay}


@router.get("/frames")
def frames(channel: str = "can0", backend: str = "socketcan", database_id: int | None = None,
           obd2: bool | None = None):
    from ..config import settings
    from ..services import can_databases as can_db_svc
    obd2_overlay = settings.obd2_overlay if obd2 is None else bool(obd2)
    monitor = mon.get_monitor(channel, backend=backend)
    # An explicit selection wins; otherwise fall back to the active vehicle's
    # linked database so decoding "just works" once a vehicle is picked.
    if database_id:
        dbc_text = _resolve_dbc_text(database_id)
    else:
        dbc_text = can_db_svc.active_dbc_text()
    # Parse the DBC once per request, not once per frame: this loop runs over up
    # to 500 buffered frames every 500ms poll.
    from ..can import dbc as dbc_mod
    parsed_db = dbc_mod.load(dbc_text) if dbc_text else None
    records = []
    for record in monitor.frames():
        entry = dict(record)
        entry["decoded"] = (decode_record(record, dbc_text, obd2_overlay=obd2_overlay, db=parsed_db)
                            if (parsed_db is not None or obd2_overlay) else None)
        records.append(entry)
    # Newest first: easier to watch live traffic without the table scrolling.
    records.reverse()
    return {"status": monitor.status(), "frames": records, "obd2_overlay": obd2_overlay}
