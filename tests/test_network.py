from starlette.testclient import TestClient

from app.main import app


def _client():
    return TestClient(app)


def test_network_status_no_op_off_pi():
    # The test host is not a Raspberry Pi, so this must degrade cleanly
    # instead of trying to reach a host-bridge that does not exist here.
    with _client() as c:
        r = c.get("/network/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["ssid"] is None
    assert body["ip"] is None


def test_network_scan_no_op_off_pi():
    with _client() as c:
        r = c.post("/network/wifi/scan")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "Raspberry Pi" in body["error"]


def test_network_connect_no_op_off_pi():
    with _client() as c:
        r = c.post("/network/wifi/connect", json={"ssid": "SomeNetwork", "psk": "hunter2"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "Raspberry Pi" in body["error"]


def test_network_connect_requires_ssid_on_pi(monkeypatch):
    from app.services import bridge
    monkeypatch.setattr(bridge, "is_raspberry_pi", lambda: True)
    with _client() as c:
        r = c.post("/network/wifi/connect", json={"psk": "hunter2"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "ssid" in body["error"]
