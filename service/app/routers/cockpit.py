"""Virtual cockpit CRUD, background image upload, live gauge values, and key
firing.

A cockpit is a user-designed surface: an uploaded background image with keys
and gauges placed on it (see ``services/cockpit.py`` for the model). This
router is a thin REST wrapper: it validates and stores uploads, resolves a
gauge/indicator element's live value through the CAN monitor and DBC decode,
and dispatches a key element's action through the same registry every other
surface uses.
"""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..services import cockpit as cockpit_svc

router = APIRouter(prefix="/cockpit", tags=["cockpit"])


class CockpitIn(BaseModel):
    name: str = ""
    profile_id: int | None = None


class CockpitUpdateIn(BaseModel):
    name: str | None = None
    profile_id: int | None = None


class ElementIn(BaseModel):
    type: str = "key"
    x: float = 0.1
    y: float = 0.1
    w: float = 0.12
    h: float = 0.12
    label: str = ""
    color: str = "#334155"
    action_id: str | None = None
    database_id: int | None = None
    arbitration_id: str | int | None = None
    signal: str | None = None
    channel: str = "can0"
    backend: str = "socketcan"
    min: float = 0.0
    max: float = 100.0
    style: str | None = None
    threshold: float | None = None
    unit: str = ""


def _get_or_404(cockpit_id: int) -> dict:
    cockpit = cockpit_svc.get_cockpit(cockpit_id)
    if cockpit is None:
        raise HTTPException(404, "No such cockpit")
    return cockpit


@router.get("")
def list_cockpits():
    return {"cockpits": cockpit_svc.list_cockpits()}


@router.post("")
def create_cockpit(body: CockpitIn):
    return cockpit_svc.create_cockpit(name=body.name, profile_id=body.profile_id)


@router.get("/{cockpit_id}")
def get_cockpit(cockpit_id: int):
    return _get_or_404(cockpit_id)


@router.patch("/{cockpit_id}")
def update_cockpit(cockpit_id: int, body: CockpitUpdateIn):
    updated = cockpit_svc.update_cockpit(cockpit_id, **body.model_dump(exclude_unset=True))
    if updated is None:
        raise HTTPException(404, "No such cockpit")
    return updated


@router.delete("/{cockpit_id}")
def delete_cockpit(cockpit_id: int):
    cockpit = cockpit_svc.get_cockpit(cockpit_id)
    if cockpit is None:
        raise HTTPException(404, "No such cockpit")
    path = cockpit_svc.image_path_for(cockpit)
    cockpit_svc.delete_cockpit(cockpit_id)
    if path is not None:
        path.unlink(missing_ok=True)
    return {"ok": True}


@router.post("/{cockpit_id}/image")
async def upload_image(cockpit_id: int, file: UploadFile = File(...)):
    cockpit = _get_or_404(cockpit_id)
    body = await file.read()
    error = cockpit_svc.validate_image_upload(file.filename, len(body))
    if error:
        raise HTTPException(400, error)
    from pathlib import Path
    ext = Path(file.filename or "").suffix.lower()
    directory = cockpit_svc.image_dir()
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{cockpit_id}{ext}"
    (directory / filename).write_bytes(body)
    # Drop a stale image saved under a different extension for this cockpit.
    old_path = cockpit_svc.image_path_for(cockpit)
    if old_path is not None and old_path.name != filename:
        old_path.unlink(missing_ok=True)
    updated = cockpit_svc.set_background_image(cockpit_id, filename)
    return {"ok": True, "cockpit": updated}


@router.get("/{cockpit_id}/image")
def get_image(cockpit_id: int):
    cockpit = _get_or_404(cockpit_id)
    path = cockpit_svc.image_path_for(cockpit)
    if path is None or not path.exists():
        raise HTTPException(404, "No background image uploaded yet")
    return FileResponse(path)


@router.post("/{cockpit_id}/elements")
def add_element(cockpit_id: int, body: ElementIn):
    _get_or_404(cockpit_id)
    updated = cockpit_svc.add_element(cockpit_id, body.model_dump())
    if updated is None:
        raise HTTPException(404, "No such cockpit")
    return updated


@router.patch("/{cockpit_id}/elements/{element_id}")
def update_element(cockpit_id: int, element_id: str, body: dict):
    _get_or_404(cockpit_id)
    updated = cockpit_svc.update_element(cockpit_id, element_id, body)
    if updated is None:
        raise HTTPException(404, "No such cockpit element")
    return updated


@router.delete("/{cockpit_id}/elements/{element_id}")
def delete_element(cockpit_id: int, element_id: str):
    _get_or_404(cockpit_id)
    if not cockpit_svc.delete_element(cockpit_id, element_id):
        raise HTTPException(404, "No such cockpit element")
    return {"ok": True}


def _resolve_dbc_text(database_id: int | None) -> str | None:
    if database_id is None:
        return None
    from ..db import CanDatabase, session_scope
    with session_scope() as s:
        database = s.get(CanDatabase, database_id)
        return database.dbc_text if database is not None else None


@router.get("/{cockpit_id}/values")
def get_values(cockpit_id: int):
    """The current display value for every gauge/indicator element, for the
    operate view to poll. A key element or an unbound gauge just reports
    "no data" rather than failing the whole request.
    """
    from ..can import monitor as mon

    cockpit = _get_or_404(cockpit_id)
    values: dict[str, dict] = {}
    dbc_cache: dict[int, str | None] = {}
    for element in cockpit.get("elements", []):
        if element.get("type") not in ("gauge", "indicator"):
            continue
        database_id = element.get("database_id")
        if database_id is None or not element.get("signal") or element.get("arbitration_id") is None:
            values[element["id"]] = {"ok": False, "raw": None, "value": None,
                                      "percent": None, "on": None, "display": "--"}
            continue
        if database_id not in dbc_cache:
            dbc_cache[database_id] = _resolve_dbc_text(database_id)
        dbc_text = dbc_cache[database_id]
        monitor = mon.get_monitor(element.get("channel", "can0"), backend=element.get("backend", "socketcan"))
        raw = cockpit_svc.latest_signal_value(
            monitor.frames(), dbc_text, element.get("arbitration_id"), element.get("signal"))
        values[element["id"]] = cockpit_svc.map_element_value(element, raw)
    return {"values": values}


@router.post("/{cockpit_id}/elements/{element_id}/fire")
def fire_element(cockpit_id: int, element_id: str):
    """Run a key element's bound action, exactly like tapping it on the start
    menu or a Stream Deck key.
    """
    cockpit = _get_or_404(cockpit_id)
    element = next((e for e in cockpit.get("elements", []) if e.get("id") == element_id), None)
    if element is None:
        raise HTTPException(404, "No such cockpit element")
    if element.get("type") != "key":
        raise HTTPException(400, "Only a key element can be fired")
    action_id = element.get("action_id")
    if not action_id:
        return {"ok": False, "message": "This key has no action bound yet"}
    from ..actions import registry
    result = registry.run(action_id)
    return {"ok": result.ok, "message": result.message, "data": result.data}
