"""User-facing pages: the start menu, the layout editor, and a home redirect."""
from __future__ import annotations

import math

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import testseq
from ..actions import registry
from ..config import settings
from ..services import can_interfaces, journal
from ..services import cockpit as cockpit_svc
from ..services import layout as layout_svc
from ..services import profiles as profiles_svc
from ..services import ui_mode as ui_mode_svc
from ..templating import templates, theme_context

router = APIRouter(tags=["ui"])

# Session key that latches operator mode once a kiosk browser has visited
# with ?kiosk=1, so later requests from the same browser (no query string,
# e.g. a link tap) stay on the operator screen. See services/ui_mode.py.
_KIOSK_SESSION_KEY = "kiosk_mode"


def resolve_ui_mode(request: Request) -> str:
    """The one place a real ``Request`` is read to pick a UI mode.

    Delegates the actual decision to :func:`ui_mode_svc.decide_ui_mode`,
    which is pure and unit-tested on its own.
    """
    kiosk_param = request.query_params.get("kiosk")
    if kiosk_param == "1":
        request.session[_KIOSK_SESSION_KEY] = True
    elif kiosk_param == "0":
        request.session[_KIOSK_SESSION_KEY] = False
    latched = bool(request.session.get(_KIOSK_SESSION_KEY, False))
    host = request.client.host if request.client else None
    return ui_mode_svc.decide_ui_mode(
        host=host, kiosk_latched=latched, ui_mode_setting=settings.ui_mode)


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
def home(request: Request):
    if resolve_ui_mode(request) == ui_mode_svc.OPERATOR:
        return RedirectResponse("/operator")
    return RedirectResponse("/overview")


@router.get("/operator", response_class=HTMLResponse)
def operator_page(request: Request):
    # Latch kiosk mode (if requested) before rendering, so the page's own
    # links (which carry no query string) still resolve to operator mode.
    resolve_ui_mode(request)
    keys = _render_slots("start")
    cols, rows = _grid_dims(len(keys))
    active_id = profiles_svc.get_active_profile_id()
    profile = profiles_svc.get_profile(active_id) if active_id is not None else None
    sequences = testseq.list_sequences(active_id) if active_id is not None else testseq.list_sequences()
    return templates.TemplateResponse(request, "operator.html", theme_context(
        request, keys=keys, cols=cols, rows=rows,
        enabled=settings.start_page_enabled, profile=profile, sequences=sequences,
        vehicle_label=_vehicle_label(profile)))


def _vehicle_label(profile: dict | None) -> str:
    """A short "year make model" string for the operator page header."""
    if not profile:
        return ""
    parts = [str(profile[k]) for k in ("year", "make", "model") if profile.get(k)]
    return " ".join(parts) or (profile.get("name") or "")


def _last_test_result() -> dict | None:
    """The most recent (or in-progress) test run, if any sequence has been
    run since the app started. Reads the module-level active runner, which
    stays set after a run finishes so its report survives until the next
    run replaces it."""
    runner = testseq.get_active()
    if runner is None:
        return None
    return runner.report()


@router.get("/overview", response_class=HTMLResponse)
def overview(request: Request):
    """The builder's home base: orients a new user to what's set up and what
    to do next, instead of dropping them straight on the key grid."""
    active_id = profiles_svc.get_active_profile_id()
    profile = profiles_svc.get_profile(active_id) if active_id is not None else None
    interfaces = can_interfaces.list_interfaces()
    recent_events = journal.recent(limit=8)
    last_result = _last_test_result()
    return templates.TemplateResponse(request, "overview.html", theme_context(
        request, profile=profile, vehicle_label=_vehicle_label(profile),
        interfaces=interfaces, recent_events=recent_events,
        last_result=last_result, start_page_enabled=settings.start_page_enabled))


@router.get("/start", response_class=HTMLResponse)
def start_page(request: Request):
    # A "Builder" link from the operator page can carry ?kiosk=0 to clear the
    # latch (see resolve_ui_mode); harmless when the param is absent.
    resolve_ui_mode(request)
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


@router.get("/ui/can-lab", response_class=HTMLResponse)
def can_lab_page(request: Request):
    # One hub that hosts the five CAN tools in tabbed iframes; each tool still
    # serves standalone at its own route (ui/reverse, ui/can-monitor, etc.).
    return templates.TemplateResponse(request, "can-lab.html", theme_context(request))


@router.get("/ui/vehicle-controls", response_class=HTMLResponse)
def vehicle_controls_page(request: Request):
    # The active vehicle's button set. Controls, the library, and the active
    # vehicle load over the API so the page reflects the nav selector live.
    return templates.TemplateResponse(request, "vehicle-controls.html", theme_context(request))


@router.get("/ui/can-sim", response_class=HTMLResponse)
def can_sim_page(request: Request):
    # The panel loads the transmit list and scheduler status over the API.
    return templates.TemplateResponse(request, "can_sim.html", theme_context(request))


@router.get("/ui/can-monitor", response_class=HTMLResponse)
def can_monitor_page(request: Request):
    # The panel loads databases and polls the frame buffer over the API.
    from ..config import settings
    return templates.TemplateResponse(request, "can_monitor.html", theme_context(request, s=settings))


@router.get("/ui/actions", response_class=HTMLResponse)
def actions_page(request: Request):
    # The library loads drivers, actions, and CAN databases over the API.
    return templates.TemplateResponse(request, "actions.html", theme_context(request))


@router.get("/ui/diagnostics", response_class=HTMLResponse)
def diagnostics_page(request: Request):
    # UDS and OBD-II reads, sent and decoded over the /diag API.
    return templates.TemplateResponse(request, "diagnostics.html", theme_context(request))


@router.get("/ui/firewall", response_class=HTMLResponse)
def firewall_page(request: Request):
    # The panel loads rules, gateway status, and captures over the API.
    return templates.TemplateResponse(request, "firewall.html", theme_context(request))


@router.get("/ui/reverse", response_class=HTMLResponse)
def reverse_page(request: Request):
    # Signal Finder: captures, survey, bitsearch, and save all load over the
    # /reverse API; this just serves the shell.
    return templates.TemplateResponse(request, "reverse.html", theme_context(request))


@router.get("/ui/logs", response_class=HTMLResponse)
def logs_page(request: Request):
    # The live event table and file list load and poll over the /logs API.
    return templates.TemplateResponse(request, "logs.html", theme_context(request))


@router.get("/ui/tests", response_class=HTMLResponse)
def tests_page(request: Request):
    # Sequences, the step builder, and a live run all load over the /tests API.
    return templates.TemplateResponse(request, "tests.html", theme_context(request))


@router.get("/ui/databases", response_class=HTMLResponse)
def databases_page(request: Request):
    # Loads installed databases, the open-source catalog, and vehicles over the API.
    return templates.TemplateResponse(request, "databases.html", theme_context(request))


@router.get("/ui/cockpit", response_class=HTMLResponse)
def cockpit_editor_page(request: Request):
    # The editor loads cockpits, actions, and CAN databases over the API.
    return templates.TemplateResponse(request, "cockpit_editor.html", theme_context(request))


@router.get("/ui/cockpit/{cockpit_id}", response_class=HTMLResponse)
def cockpit_operate_page(request: Request, cockpit_id: int):
    # Full-screen, no chrome: the operate view loads the cockpit and polls
    # live gauge values over the API itself.
    cockpit = cockpit_svc.get_cockpit(cockpit_id)
    return templates.TemplateResponse(request, "cockpit_operate.html", theme_context(
        request, cockpit_id=cockpit_id, cockpit=cockpit))
