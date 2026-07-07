"""Layout editor API: read and rewrite the drag-and-drop key layout."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import deck_layout, layout as layout_svc

router = APIRouter(prefix="/layout", tags=["layout"])


class LayoutIn(BaseModel):
    # Ordered action ids; null (None) is an explicit blank slot.
    slots: list[str | None]


@router.get("")
def get_all_layouts():
    return {
        "surfaces": layout_svc.get_all(),
        "supported_key_counts": deck_layout.supported_key_counts(),
    }


@router.get("/{surface}")
def get_layout(surface: str):
    try:
        return {"surface": surface, "slots": layout_svc.get_layout(surface)}
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.put("/{surface}")
def set_layout(surface: str, body: LayoutIn):
    try:
        layout_svc.set_layout(surface, body.slots)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {"ok": True, "surface": surface, "count": len(body.slots)}
