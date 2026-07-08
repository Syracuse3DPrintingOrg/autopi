"""Interface purpose/label persistence, and the bring-up/down/health/self-test
routes' behavior when no host-bridge is reachable (the normal case off a Pi,
which is exactly what this test environment is)."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.can import reset_channels
from app.services import can_interfaces


@pytest.fixture(autouse=True)
def _clear_channel_cache():
    reset_channels()
    yield
    reset_channels()


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


# -- purpose / display label (services/can_interfaces.py) -------------------

def test_display_label_uses_purpose_when_set():
    entry = can_interfaces.save_interface({"id": "can0", "purpose": "powertrain", "label": "ignored"})
    assert can_interfaces.display_label(entry) == "Powertrain"


def test_display_label_falls_back_to_custom_label():
    entry = can_interfaces.save_interface({"id": "can0", "purpose": "custom", "label": "Rear body bus"})
    assert can_interfaces.display_label(entry) == "Rear body bus"


def test_display_label_falls_back_to_id_when_nothing_set():
    entry = can_interfaces.save_interface({"id": "can0"})
    assert can_interfaces.display_label(entry) == "can0"


def test_normalize_rejects_unknown_purpose():
    entry = can_interfaces.save_interface({"id": "can0", "purpose": "not-a-real-purpose"})
    assert entry["purpose"] == ""


def test_router_config_includes_purpose_label(client):
    client.post("/can/interfaces/config", json={"id": "can0", "purpose": "diagnostic"})
    listed = client.get("/can/interfaces/config").json()
    entry = next(i for i in listed["interfaces"] if i["id"] == "can0")
    assert entry["purpose_label"] == "Diagnostic"


# -- bring-up / bring-down / link-status / health: no bridge reachable ------

def test_bring_up_without_bridge_gives_manual_command(client):
    client.post("/can/interfaces/config", json={
        "id": "can0", "backend": "socketcan", "channel": "can0", "bitrate": 500000,
    })
    resp = client.post("/can/interfaces/config/can0/up")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "ip link set can0" in body["error"]
    assert "500000" in body["error"]


def test_bring_down_without_bridge_gives_manual_command(client):
    client.post("/can/interfaces/config", json={"id": "can0", "channel": "can0"})
    resp = client.post("/can/interfaces/config/can0/down")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "ip link set can0 down" in body["error"]


def test_link_status_without_bridge_is_a_clear_failure(client):
    client.post("/can/interfaces/config", json={"id": "can0", "channel": "can0"})
    resp = client.get("/can/interfaces/config/can0/link-status")
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


def test_health_without_bridge_is_a_clear_failure(client):
    client.post("/can/interfaces/config", json={"id": "can0", "channel": "can0"})
    resp = client.get("/can/interfaces/config/can0/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


def test_bring_up_rejects_non_link_backed_backend(client):
    client.post("/can/interfaces/config", json={"id": "v0", "backend": "virtual", "channel": "virtual0"})
    resp = client.post("/can/interfaces/config/v0/up")
    assert resp.status_code == 400


def test_bring_up_404_for_unknown_interface(client):
    resp = client.post("/can/interfaces/config/nope/up")
    assert resp.status_code == 404


# -- self-test / send-test-frame: work against the virtual backend ---------

def test_self_test_passes_on_virtual_backend(client):
    pytest.importorskip("can")
    client.post("/can/interfaces/config", json={
        "id": "loop0", "backend": "virtual", "channel": "autopi-selftest-loop",
    })
    resp = client.post("/can/interfaces/config/loop0/self-test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["passed"] is True


def test_send_test_frame_unavailable_reports_clear_error(client):
    client.post("/can/interfaces/config", json={"id": "can0", "backend": "socketcan", "channel": "can0"})
    resp = client.post("/can/interfaces/config/can0/send-test-frame")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False


def test_send_test_frame_404_for_unknown_interface(client):
    resp = client.post("/can/interfaces/config/nope/send-test-frame")
    assert resp.status_code == 404
