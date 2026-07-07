"""Export and import the local database as a single JSON file.

``GET /db/export`` downloads the whole database (or, with ``?profile_id=``,
just one vehicle profile) as a JSON file. ``POST /db/import`` loads a
previously exported file back in. Import is always an upsert: existing
records are updated by id and nothing already stored is deleted, so it is
safe to import an older or partial export onto a running install.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..db import importexport, session_scope

router = APIRouter(prefix="/db", tags=["database"])


class ImportPayload(BaseModel):
    version: int | None = None
    actions: list[dict] = []
    profiles: list[dict] = []
    can_messages: list[dict] = []
    logic_rules: list[dict] = []


@router.get("/export")
def export_database(profile_id: int | None = None):
    with session_scope() as session:
        if profile_id is not None:
            data = importexport.export_profile(session, profile_id)
            if data is None:
                raise HTTPException(404, f"No profile with id {profile_id}")
            filename = f"autopi-profile-{profile_id}.json"
        else:
            data = importexport.export_all(session)
            filename = "autopi-export.json"

    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import")
def import_database(payload: ImportPayload):
    data = payload.model_dump()
    with session_scope() as session:
        try:
            counts = importexport.import_data(session, data)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "imported": counts}
