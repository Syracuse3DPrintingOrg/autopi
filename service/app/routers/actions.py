"""Action library REST API: list drivers, CRUD actions, and run one."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..actions import registry
from ..actions.drivers import DRIVERS
from ..actions.registry import ActionSpec
from ..services import layout as layout_svc

router = APIRouter(prefix="/actions", tags=["actions"])


class ActionIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    label: str = ""
    driver: str = "shell"
    params: dict = Field(default_factory=dict)
    icon: str = "bi-lightning-charge"
    color: str = "#334155"
    category: str = "Actions"
    members: list[str] = Field(default_factory=list)


@router.get("/drivers")
def list_drivers():
    return {"drivers": [d.describe() for d in DRIVERS.values()]}


@router.get("")
def list_actions():
    return {"actions": [s.to_dict() for s in registry.all_actions().values()]}


@router.post("")
def create_or_update_action(body: ActionIn):
    if body.id in registry.BUILTINS:
        raise HTTPException(400, f"{body.id} is a builtin")
    if body.driver not in DRIVERS and body.driver != "macro":
        raise HTTPException(400, f"Unknown driver: {body.driver}")
    registry.upsert_action(ActionSpec.from_dict(body.model_dump()))
    return {"ok": True, "id": body.id}


@router.delete("/{action_id}")
def delete_action(action_id: str):
    if not registry.delete_action(action_id):
        raise HTTPException(404, f"No user action named {action_id}")
    layout_svc.remove_action_everywhere(action_id)
    return {"ok": True}


@router.post("/{action_id}/run")
def run_action(action_id: str):
    result = registry.run(action_id)
    return {"ok": result.ok, "message": result.message, "data": result.data}
