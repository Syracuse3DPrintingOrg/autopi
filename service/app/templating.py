"""Jinja2 templates and the shared theme context."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates

from .config import APP_NAME, APP_VERSION, settings

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))


def theme_context(request, **extra: Any) -> dict[str, Any]:
    """Base template variables every page needs."""
    ctx: dict[str, Any] = {
        "request": request,
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "theme_mode": settings.theme_mode,
    }
    ctx.update(extra)
    return ctx
