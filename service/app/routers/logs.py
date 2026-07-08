"""The logging journal REST API: recent events, the file list, a download,
and clearing the journal.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from ..services import journal

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/recent")
def recent(limit: int = 200, kind: str | None = None):
    limit = max(1, min(limit, 2000))
    return {"events": journal.recent(limit=limit, kind=kind), "enabled": journal.enabled()}


@router.get("/files")
def files():
    return {"files": journal.list_files()}


@router.get("/file/{name}")
def download_file(name: str):
    text = journal.read_file(name)
    if text is None:
        raise HTTPException(404, "No such log file")
    return PlainTextResponse(
        text, media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/clear")
def clear():
    removed = journal.clear()
    return {"ok": True, "removed": removed}
