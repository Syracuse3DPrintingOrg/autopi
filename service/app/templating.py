"""Jinja2 templates and the shared theme context."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates

from .config import APP_NAME, APP_VERSION, settings

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))


def _llm_configured() -> bool:
    """Whether the optional AI assist can run, gated in templates so pages
    only offer AI actions that will actually work. Never raises."""
    try:
        from .llm import status
        return bool(status().get("available"))
    except Exception:
        return False


def _vehicle_context() -> dict[str, Any]:
    """The active vehicle and the pickable list, for the persistent selector in
    the top nav. Degrades to no selector if the profile store is unavailable, so
    a DB hiccup never 500s every page."""
    try:
        from .services import profiles as profiles_svc
        active_id = profiles_svc.get_active_profile_id()
        vehicles = [{"id": p.get("id"), "label": profiles_svc.profile_label(p)}
                    for p in profiles_svc.list_profiles()]
        active = next((v for v in vehicles if v["id"] == active_id), None)
        return {"nav_vehicles": vehicles, "nav_active_vehicle": active,
                "nav_active_vehicle_id": active_id}
    except Exception:
        return {"nav_vehicles": [], "nav_active_vehicle": None, "nav_active_vehicle_id": None}


def theme_context(request, **extra: Any) -> dict[str, Any]:
    """Base template variables every page needs."""
    ctx: dict[str, Any] = {
        "request": request,
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "theme_mode": settings.theme_mode,
        "llm_configured": _llm_configured(),
    }
    ctx.update(_vehicle_context())
    ctx.update(extra)
    return ctx
