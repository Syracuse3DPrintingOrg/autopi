"""The shared command library: reusable CAN commands independent of any vehicle.

Found commands can be saved here (and/or onto a vehicle) and later dropped onto
any vehicle's control slots. See ``services/command_library.py``.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import command_library as library_svc

router = APIRouter(prefix="/library", tags=["library"])


class CommandIn(BaseModel):
    name: str = ""
    command: dict = {}


@router.get("/commands")
def list_commands():
    return {"commands": library_svc.list_commands()}


@router.post("/commands")
def add_command(body: CommandIn):
    return library_svc.add_command(body.name, body.command)


@router.delete("/commands/{command_id}")
def delete_command(command_id: int):
    if not library_svc.delete_command(command_id):
        raise HTTPException(404, "No such command")
    return {"ok": True}
