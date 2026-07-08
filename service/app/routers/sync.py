"""Profile sync: pull vehicle profiles from a central AutoPi server.

Future feature (AutoPi-aj2): there is no real server yet. Every route here
degrades to a clean ``{"ok": False, "error": ...}`` when sync is not
configured or the server cannot be reached, the same way the network and
host-bridge routes degrade off a Raspberry Pi. See
``services/profile_sync.py`` for the protocol and the pull/apply logic.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..config import settings
from ..services import profile_sync

router = APIRouter(prefix="/sync", tags=["sync"])


class PullIn(BaseModel):
    key: str


@router.get("/status")
def sync_status():
    return {"configured": profile_sync.configured(), "server": settings.sync_server_url}


@router.post("/list")
def sync_list():
    return profile_sync.list_remote()


@router.post("/pull")
def sync_pull(body: PullIn):
    return profile_sync.pull(body.key)


@router.post("/pull-all")
def sync_pull_all():
    return profile_sync.pull_all()
