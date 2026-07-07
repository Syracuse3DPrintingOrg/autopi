import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import APP_NAME, APP_VERSION, settings
from .routers import actions as actions_router
from .routers import db as db_router
from .routers import layout as layout_router
from .routers import logic as logic_router
from .routers import setup as setup_router
from .routers import streamdeck as streamdeck_router
from .routers import system as system_router
from .routers import ui as ui_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Seed a starter layout and demo keys on a fresh install so the start menu
    # and Stream Deck are populated. Best-effort: a read-only data dir just
    # leaves an empty grid.
    try:
        from .services.seed import seed_if_empty
        seed_if_empty()
    except Exception:
        pass
    # Create any missing database tables. Never drops or resets existing data:
    # create_all only adds what is not already there (db/engine.py).
    try:
        from .db import init_db
        init_db()
    except Exception:
        pass
    yield


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=secrets.token_hex(32))

_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(ui_router.router)
app.include_router(actions_router.router)
app.include_router(layout_router.router)
app.include_router(setup_router.router)
app.include_router(streamdeck_router.router)
app.include_router(system_router.router)
app.include_router(db_router.router)
app.include_router(logic_router.router)


@app.get("/health")
def health():
    return {"app": "autopi", "version": APP_VERSION, "mode": settings.deployment_mode}
