"""Tests for the operator/builder mode decision (services/ui_mode.py) and
the routes that use it: the home redirect and the /operator page.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.services import ui_mode


# --- pure decision function --------------------------------------------------


def test_auto_mode_loopback_host_is_operator():
    for host in ("127.0.0.1", "::1", "localhost"):
        assert ui_mode.decide_ui_mode(
            host=host, kiosk_latched=False, ui_mode_setting="auto") == "operator"


def test_auto_mode_remote_host_is_builder():
    for host in ("192.168.1.50", "10.0.0.7", None):
        assert ui_mode.decide_ui_mode(
            host=host, kiosk_latched=False, ui_mode_setting="auto") == "builder"


def test_auto_mode_kiosk_latch_forces_operator_for_remote_host():
    assert ui_mode.decide_ui_mode(
        host="192.168.1.50", kiosk_latched=True, ui_mode_setting="auto") == "operator"


def test_explicit_operator_setting_wins_even_for_remote_host():
    assert ui_mode.decide_ui_mode(
        host="8.8.8.8", kiosk_latched=False, ui_mode_setting="operator") == "operator"


def test_explicit_builder_setting_wins_even_for_loopback_host():
    assert ui_mode.decide_ui_mode(
        host="127.0.0.1", kiosk_latched=True, ui_mode_setting="builder") == "builder"


def test_is_loopback_host():
    assert ui_mode.is_loopback_host("127.0.0.1")
    assert ui_mode.is_loopback_host("::1")
    assert ui_mode.is_loopback_host("localhost")
    assert not ui_mode.is_loopback_host("192.168.1.50")
    assert not ui_mode.is_loopback_host(None)


# --- routes: home redirect and /operator ------------------------------------


@pytest.fixture
def client():
    # TestClient's default synthetic client address ("testclient") is not a
    # loopback host, so this fixture stands in for a remote PC browser.
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def loopback_client():
    # A client address of 127.0.0.1 stands in for a Pi browsing its own server.
    from app.main import app
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        yield c


def test_home_redirects_to_overview_for_remote_client_by_default(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/overview"


def test_home_redirects_to_operator_for_loopback_client_by_default(loopback_client):
    resp = loopback_client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/operator"


def test_home_redirects_to_overview_when_forced_builder(loopback_client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ui_mode", "builder")
    resp = loopback_client.get("/", follow_redirects=False)
    assert resp.headers["location"] == "/overview"


def test_home_redirects_to_operator_when_forced_operator(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ui_mode", "operator")
    resp = client.get("/", follow_redirects=False)
    assert resp.headers["location"] == "/operator"


def test_kiosk_query_param_latches_operator_for_remote_client(client):
    resp = client.get("/?kiosk=1", follow_redirects=False)
    assert resp.headers["location"] == "/operator"
    # The latch persists across requests in the same session (a kiosk tab
    # navigating without the query string still resolves to operator mode).
    resp2 = client.get("/", follow_redirects=False)
    assert resp2.headers["location"] == "/operator"


def test_builder_link_from_operator_clears_the_kiosk_latch(client):
    # A remote browser latched into operator mode must be able to escape via the
    # operator screen's Builder link, which lands on /overview?kiosk=0.
    client.get("/?kiosk=1", follow_redirects=False)
    assert client.get("/", follow_redirects=False).headers["location"] == "/operator"  # latched
    # Visiting the Builder link clears the latch...
    assert client.get("/overview?kiosk=0", follow_redirects=False).status_code == 200
    # ...so the root now resolves back to the builder home, not operator.
    assert client.get("/", follow_redirects=False).headers["location"] == "/overview"


# --- /overview ---------------------------------------------------------------


def test_overview_page_renders(client):
    resp = client.get("/overview")
    assert resp.status_code == 200
    assert "What do you want to do?" in resp.text


def test_overview_page_shows_no_vehicle_selected_by_default(client):
    resp = client.get("/overview")
    assert "No vehicle selected" in resp.text


def test_overview_page_shows_active_profile(client):
    from app.db import init_db
    from app.services import profiles as profiles_svc
    init_db()
    profile = profiles_svc.create_profile(name="Bench car", year=2022, make="Ford", model="F-150")
    profiles_svc.set_active_profile(profile["id"])

    resp = client.get("/overview")
    assert resp.status_code == 200
    assert "Bench car" in resp.text
    assert "2022 Ford F-150" in resp.text


def test_overview_page_has_quick_action_links(client):
    resp = client.get("/overview")
    assert 'href="ui/can-monitor"' in resp.text
    assert 'href="can"' in resp.text
    assert 'href="layout-editor"' in resp.text
    assert 'href="ui/tests"' in resp.text
    assert 'href="ui/can-sim"' in resp.text
    assert 'href="operator"' in resp.text


def test_overview_nav_link_present(client):
    resp = client.get("/overview")
    assert 'href="overview"' in resp.text


def test_operator_page_renders(client):
    resp = client.get("/operator")
    assert resp.status_code == 200
    assert "Run test" in resp.text
    assert "No vehicle selected" in resp.text


def test_operator_page_shows_active_profile(client):
    from app.db import init_db
    from app.services import profiles as profiles_svc
    init_db()
    profile = profiles_svc.create_profile(name="Bench car", year=2022, make="Ford", model="F-150")
    profiles_svc.set_active_profile(profile["id"])

    resp = client.get("/operator")
    assert resp.status_code == 200
    assert "Bench car" in resp.text
    assert "2022 Ford F-150" in resp.text


def test_operator_page_has_gear_and_builder_links(client):
    resp = client.get("/operator")
    assert 'href="setup"' in resp.text
    # The builder escape hatch lands on the builder home, clearing the latch.
    assert 'href="overview?kiosk=0"' in resp.text


def test_operator_page_shows_active_vehicle_controls(client):
    """With a control mapped on the active vehicle, the operator screen leads
    with a big button that fires that control through the shared actions run
    path (POST /actions/{id}/run)."""
    from app.db import init_db
    from app.services import profiles as profiles_svc
    init_db()
    profile = profiles_svc.create_profile(name="Bench car", make="Ford", model="F-150")
    profiles_svc.set_active_profile(profile["id"])
    # Map a real CAN command onto the horn control slot.
    profiles_svc.set_control(
        profile["id"], "horn",
        {"channel": "can0", "arbitration_id": "0x3D1", "data": "01"},
        label="Horn")

    resp = client.get("/operator")
    assert resp.status_code == 200
    action_id = f"ctl_{profile['id']}_horn"
    # The control renders as a button wired to the shared run endpoint.
    assert f'data-action="{action_id}"' in resp.text
    assert "Horn" in resp.text
    # And that action actually resolves and runs (simulated with no bus in CI).
    run = client.post(f"/actions/{action_id}/run")
    body = run.json()
    assert body["ok"] is True

    # An unmapped slot is left off the operator screen (it is the "use" view).
    assert f'data-action="ctl_{profile["id"]}_unlock"' not in resp.text


def test_start_page_has_no_desktop_navbar_but_operator_link_reachable(client):
    # The operator page does not extend the desktop chrome (base.html): no
    # top navbar with the full link set should be present.
    resp = client.get("/operator")
    assert 'id="topnav"' not in resp.text


def test_static_css_is_cache_busted_by_version(client):
    # The stylesheet link must carry ?v=<version> so a browser fetches fresh CSS
    # after an update instead of serving a stale cached file (which hid the nav
    # dropdown z-index fix).
    from app.config import APP_VERSION
    html = client.get("/overview").text
    assert f"static/css/app.css?v={APP_VERSION}" in html
    assert "static/vendor/bootstrap.min.css\"" in html  # vendor stays unversioned
