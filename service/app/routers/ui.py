"""User-facing pages: the start menu, the layout editor, and a home redirect."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..actions import registry
from ..config import settings
from ..services import layout as layout_svc
from ..templating import templates, theme_context

router = APIRouter(tags=["ui"])


def _render_slots(surface: str):
    """Turn a surface layout into template-ready key dicts."""
    actions = registry.all_actions()
    keys = []
    for action_id in layout_svc.get_layout(surface):
        spec = actions.get(action_id) if action_id else None
        if spec is None or spec.id == "blank":
            keys.append({"kind": "blank"})
            continue
        keys.append({
            "kind": "key",
            "id": spec.id,
            "label": spec.label or spec.id,
            "icon": spec.icon or "bi-lightning-charge",
            "color": spec.color or "#334155",
        })
    return keys


@router.get("/")
def home():
    if settings.start_page_enabled:
        return RedirectResponse("/start")
    return RedirectResponse("/layout-editor")


@router.get("/start", response_class=HTMLResponse)
def start_page(request: Request):
    keys = _render_slots("start")
    return templates.TemplateResponse(request, "start.html", theme_context(
        request, keys=keys, enabled=settings.start_page_enabled))


@router.get("/layout-editor", response_class=HTMLResponse)
def layout_editor(request: Request):
    return templates.TemplateResponse(request, "layout_editor.html", theme_context(
        request,
        actions=[s.to_dict() for s in registry.all_actions().values()],
        surfaces=layout_svc.get_all(),
    ))
