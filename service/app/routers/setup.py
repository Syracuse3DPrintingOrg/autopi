"""Settings page and its save endpoint.

Only the fields present in the request are applied (partial saves), so a
per-section form posts just its own fields without clobbering the others.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..config import settings
from ..services import deck_layout
from ..templating import templates, theme_context

router = APIRouter(prefix="/setup", tags=["setup"])


@router.get("", response_class=HTMLResponse)
def setup_page(request: Request):
    return templates.TemplateResponse(request, "setup.html", theme_context(
        request,
        settings=settings,
        rotations=(0, 90, 180, 270),
        key_counts=deck_layout.supported_key_counts(),
    ))


@router.post("/save")
async def save_settings(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        return {"ok": False, "error": "expected a JSON object"}
    # Coerce known typed fields so a form's strings land as the right type.
    updates: dict = {}
    for key, value in body.items():
        if key in {"start_page_enabled", "kiosk_enabled", "require_pin"}:
            updates[key] = bool(value)
        elif key in {"deck_rotation", "deck_brightness"}:
            try:
                updates[key] = int(value)
            except (TypeError, ValueError):
                continue
        else:
            updates[key] = value
    settings.save(updates)
    return {"ok": True}
