"""CAN interface configuration: which backend and settings a channel uses.

``GET /can/interfaces`` (in ``can_dbc.py``) reports live availability for
the two default channel names. This router is the config CRUD behind the
"CAN interfaces" settings pane, kept at a distinct path
(``/can/interfaces/config``) so it never collides with that route.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..can.registry import list_backends
from ..services import can_interfaces

router = APIRouter(prefix="/can/interfaces", tags=["can-interfaces"])


class InterfaceIn(BaseModel):
    id: str
    backend: str = "socketcan"
    channel: str = ""
    bitrate: int = can_interfaces.DEFAULT_BITRATE
    fd: bool = False
    data_bitrate: int | None = None
    label: str = ""


@router.get("/backends")
def get_backends():
    return {"backends": list_backends()}


@router.get("/config")
def get_config():
    return {"interfaces": can_interfaces.list_interfaces()}


@router.post("/config")
def save_config(body: InterfaceIn):
    if not body.id.strip():
        raise HTTPException(400, "An interface id (the channel name) is required")
    entry = can_interfaces.save_interface(body.model_dump())
    return {"ok": True, "interface": entry}


@router.delete("/config/{interface_id}")
def delete_config(interface_id: str):
    if not can_interfaces.delete_interface(interface_id):
        raise HTTPException(404, "No such configured interface")
    return {"ok": True}


@router.get("/config/{interface_id}/status")
def config_status(interface_id: str):
    """Open (or reuse) the provider for a configured interface and report
    whether it is actually available on this host, without sending anything."""
    entry = can_interfaces.get_interface(interface_id)
    if entry is None:
        raise HTTPException(404, "No such configured interface")
    from ..can import get_channel

    kwargs = {"bitrate": entry["bitrate"], "fd": entry["fd"]}
    if entry.get("data_bitrate"):
        kwargs["data_bitrate"] = entry["data_bitrate"]
    provider = get_channel(entry["channel"], backend=entry["backend"], **kwargs)
    return {"id": entry["id"], "available": provider.available}
