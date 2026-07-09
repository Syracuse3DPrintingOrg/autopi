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


def theme_context(request, **extra: Any) -> dict[str, Any]:
    """Base template variables every page needs."""
    ctx: dict[str, Any] = {
        "request": request,
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "theme_mode": settings.theme_mode,
        "llm_configured": _llm_configured(),
    }
    ctx.update(extra)
    return ctx
