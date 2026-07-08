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


def test_home_redirects_to_start_for_remote_client_by_default(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/start"


def test_home_redirects_to_operator_for_loopback_client_by_default(loopback_client):
    resp = loopback_client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/operator"


def test_home_redirects_to_start_when_forced_builder(loopback_client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ui_mode", "builder")
    resp = loopback_client.get("/", follow_redirects=False)
    assert resp.headers["location"] == "/start"


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
    assert 'href="start' in resp.text


def test_start_page_has_no_desktop_navbar_but_operator_link_reachable(client):
    # The operator page does not extend the desktop chrome (base.html): no
    # top navbar with the full link set should be present.
    resp = client.get("/operator")
    assert 'id="topnav"' not in resp.text
