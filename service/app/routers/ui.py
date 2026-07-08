"""User-facing pages: the start menu, the layout editor, and a home redirect."""
from __future__ import annotations

import math

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
        common = {
            "id": spec.id,
            "label": spec.label or spec.id,
            "icon": spec.icon or "bi-lightning-charge",
            "color": spec.color or "#334155",
        }
        common["kind"] = "deckonly" if spec.deck_only else "action"
        keys.append(common)
    return keys


def _grid_dims(n: int) -> tuple[int, int]:
    """A near-square grid that holds n keys (cols, rows)."""
    if n <= 0:
        return 1, 1
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    return cols, rows


@router.get("/")
def home():
    if settings.start_page_enabled:
        return RedirectResponse("/start")
    return RedirectResponse("/layout-editor")


@router.get("/start", response_class=HTMLResponse)
def start_page(request: Request):
    keys = _render_slots("start")
    cols, rows = _grid_dims(len(keys))
    return templates.TemplateResponse(request, "start.html", theme_context(
        request, keys=keys, cols=cols, rows=rows,
        enabled=settings.start_page_enabled))


@router.get("/layout-editor", response_class=HTMLResponse)
def layout_editor(request: Request):
    # The editor loads actions, layout, and deck status over the API itself.
    return templates.TemplateResponse(request, "layout_editor.html",
                                      theme_context(request))


@router.get("/can", response_class=HTMLResponse)
def can_console(request: Request):
    # The CAN console loads databases, interfaces, and decode/encode over the API.
    return templates.TemplateResponse(request, "can.html", theme_context(request))


@router.get("/automation", response_class=HTMLResponse)
def automation(request: Request):
    # Logic rules and database backup/restore, loaded over the API.
    return templates.TemplateResponse(request, "automation.html", theme_context(request))


@router.get("/ui/profiles", response_class=HTMLResponse)
def profiles_page(request: Request):
    # Under /ui because /profiles is already the CRUD API's prefix.
    return templates.TemplateResponse(request, "profiles.html", theme_context(request))


@router.get("/ui/can-sim", response_class=HTMLResponse)
def can_sim_page(request: Request):
    # The panel loads the transmit list and scheduler status over the API.
    return templates.TemplateResponse(request, "can_sim.html", theme_context(request))
