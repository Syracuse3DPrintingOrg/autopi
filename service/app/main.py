import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import APP_NAME, APP_VERSION, settings
from .routers import actions as actions_router
from .routers import can_dbc as can_dbc_router
from .routers import can_interfaces as can_interfaces_router
from .routers import can_monitor as can_monitor_router
from .routers import can_sim as can_sim_router
from .routers import cockpit as cockpit_router
from .routers import db as db_router
from .routers import diagnostics as diagnostics_router
from .routers import examples as examples_router
from .routers import layout as layout_router
from .routers import logs as logs_router
from .routers import logic as logic_router
from .routers import network as network_router
from .routers import profiles as profiles_router
from .routers import setup as setup_router
from .routers import streamdeck as streamdeck_router
from .routers import sync as sync_router
from .routers import system as system_router
from .routers import tests as tests_router
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
    # Seed the starter vehicle profiles: same best-effort, never-clobber policy.
    try:
        from .services.seed_profiles import seed_profiles_if_empty
        seed_profiles_if_empty()
    except Exception:
        pass
    yield


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=secrets.token_hex(32))


@app.middleware("http")
async def _refresh_settings(request, call_next):
    # Re-read settings.json from disk before handling each request. The settings
    # object is a module-level singleton loaded once at import, so without this a
    # second uvicorn worker (or a process that did not do the write) would serve
    # stale values and saved settings would appear not to stick. The file is
    # tiny and load_saved degrades silently if it is missing or unreadable.
    settings.load_saved()
    return await call_next(request)

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
app.include_router(can_dbc_router.router)
app.include_router(can_sim_router.router)
app.include_router(can_monitor_router.router)
app.include_router(can_interfaces_router.router)
app.include_router(diagnostics_router.router)
app.include_router(examples_router.router)
app.include_router(logs_router.router)
app.include_router(tests_router.router)
app.include_router(sync_router.router)
app.include_router(profiles_router.router)
app.include_router(network_router.router)
app.include_router(cockpit_router.router)


def _data_dir_writable() -> bool:
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        probe = settings.data_dir / ".write-probe"
        probe.write_text("ok")
        probe.unlink()
        return True
    except OSError:
        return False


@app.get("/health")
def health():
    # data_dir_writable is here on purpose: if settings and layouts appear not
    # to save on a device, this shows whether the data directory can be written.
    return {
        "app": "autopi",
        "version": APP_VERSION,
        "mode": settings.deployment_mode,
        "data_dir": str(settings.data_dir),
        "data_dir_writable": _data_dir_writable(),
    }
