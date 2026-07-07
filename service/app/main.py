import secrets
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import APP_NAME, APP_VERSION, settings
from .routers import actions as actions_router
from .routers import layout as layout_router
from .routers import setup as setup_router
from .routers import ui as ui_router

app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.add_middleware(SessionMiddleware, secret_key=secrets.token_hex(32))

_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(ui_router.router)
app.include_router(actions_router.router)
app.include_router(layout_router.router)
app.include_router(setup_router.router)


@app.get("/health")
def health():
    return {"app": "autopi", "version": APP_VERSION, "mode": settings.deployment_mode}
