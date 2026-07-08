"""CAN transmit simulation: pure frame building, scheduler ticks, persistence,
and the router, all without real threads or CAN hardware.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.can import simulation as sim
from app.can.simulation import SimEngine
from app.main import app


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    # The router tests drive the module-level `sim.engine` singleton, which
    # outlives any one test's temp data dir; make sure its background thread
    # never leaks into the next test.
    sim.engine.stop()
    sim.engine._next_due.clear()


# -- frame building (pure) ---------------------------------------------------

def test_build_frame_raw_hex_data():
    entry = {"arbitration_id": "0x100", "data": "01 02 03"}
    frame = sim.build_frame(entry)
    assert frame.arbitration_id == 0x100
    assert frame.data == [1, 2, 3]
    assert frame.is_extended_id is False


def test_build_frame_accepts_int_arbitration_id():
    entry = {"arbitration_id": 0x200, "data": "AA"}
    frame = sim.build_frame(entry)
    assert frame.arbitration_id == 0x200


def test_build_frame_defaults_extended_for_ids_above_standard_range():
    entry = {"arbitration_id": 0x1FFFFFFF, "data": ""}
    frame = sim.build_frame(entry)
    assert frame.is_extended_id is True


def test_build_frame_no_arbitration_id_raises():
    with pytest.raises(ValueError):
        sim.build_frame({"data": "01"})


def test_build_frame_invalid_frame_raises_with_validate_message():
    entry = {"arbitration_id": 0x100, "data": "00 " * 9}  # 9 bytes, classic CAN
    with pytest.raises(ValueError):
        sim.build_frame(entry)


def test_build_frame_uses_database_encoding_when_configured(monkeypatch):
    calls = []

    def fake_encode(dbc_text, message, signals):
        calls.append((dbc_text, message, signals))
        return [9, 9]

    monkeypatch.setattr("app.can.dbc.encode", fake_encode)
    entry = {
        "arbitration_id": "0x300",
        "database_id": 1,
        "message": "SPEED_MSG",
        "signals": {"SPEED": 42},
    }
    frame = sim.build_frame(entry, dbc_text="fake dbc text")
    assert frame.data == [9, 9]
    assert calls == [("fake dbc text", "SPEED_MSG", {"SPEED": 42})]


def test_build_frame_database_entry_without_dbc_text_raises():
    entry = {"arbitration_id": "0x300", "database_id": 1, "message": "M", "signals": {}}
    with pytest.raises(ValueError):
        sim.build_frame(entry, dbc_text=None)


def test_build_frame_falls_back_to_raw_data_when_message_missing():
    # database_id set but no message: not a "uses_database" entry, so the
    # raw data path is used instead of requiring dbc_text.
    entry = {"arbitration_id": "0x100", "database_id": 1, "data": "01"}
    frame = sim.build_frame(entry)
    assert frame.data == [1]


# -- persistence --------------------------------------------------------

def test_create_list_get_entry_roundtrip():
    created = sim.create_entry({"name": "a", "arbitration_id": 0x100, "data": "01"})
    assert created["id"]
    fetched = sim.get_entry(created["id"])
    assert fetched["name"] == "a"
    assert [e["id"] for e in sim.list_entries()] == [created["id"]]


def test_update_entry_merges_fields():
    created = sim.create_entry({"name": "a", "arbitration_id": 0x100, "data": "01"})
    updated = sim.update_entry(created["id"], {"name": "b"})
    assert updated["name"] == "b"
    assert updated["arbitration_id"] == 0x100


def test_update_missing_entry_returns_none():
    assert sim.update_entry("nope", {"name": "x"}) is None


def test_delete_entry_removes_it():
    created = sim.create_entry({"name": "a", "arbitration_id": 0x100, "data": "01"})
    assert sim.delete_entry(created["id"]) is True
    assert sim.get_entry(created["id"]) is None


def test_delete_missing_entry_returns_false():
    assert sim.delete_entry("nope") is False


def test_set_enabled_toggles():
    created = sim.create_entry({"name": "a", "arbitration_id": 0x100, "data": "01", "enabled": True})
    disabled = sim.set_enabled(created["id"], False)
    assert disabled["enabled"] is False


# -- scheduler tick (pure, synthetic clock, fake sender) ---------------------

def _engine_with_fake_sender():
    sent = []

    def sender(backend, channel, frame):
        sent.append((backend, channel, frame))
        return True

    engine = SimEngine(sender=sender)
    return engine, sent


def test_tick_sends_periodic_entry_on_first_call():
    engine, sent = _engine_with_fake_sender()
    entries = [{"id": "e1", "arbitration_id": 0x100, "data": "01", "period_ms": 1000, "enabled": True}]
    results = engine.tick(now=0.0, entries=entries)
    assert len(sent) == 1
    assert results == [{"id": "e1", "ok": True, "error": None}]


def test_tick_does_not_resend_before_period_elapses():
    engine, sent = _engine_with_fake_sender()
    entries = [{"id": "e1", "arbitration_id": 0x100, "data": "01", "period_ms": 1000, "enabled": True}]
    engine.tick(now=0.0, entries=entries)
    engine.tick(now=0.5, entries=entries)  # only 500ms later
    assert len(sent) == 1


def test_tick_resends_after_period_elapses():
    engine, sent = _engine_with_fake_sender()
    entries = [{"id": "e1", "arbitration_id": 0x100, "data": "01", "period_ms": 1000, "enabled": True}]
    engine.tick(now=0.0, entries=entries)
    engine.tick(now=1.2, entries=entries)
    assert len(sent) == 2


def test_tick_skips_disabled_entries():
    engine, sent = _engine_with_fake_sender()
    entries = [{"id": "e1", "arbitration_id": 0x100, "data": "01", "period_ms": 1000, "enabled": False}]
    engine.tick(now=0.0, entries=entries)
    assert sent == []


def test_tick_skips_one_shot_entries():
    engine, sent = _engine_with_fake_sender()
    entries = [{"id": "e1", "arbitration_id": 0x100, "data": "01", "period_ms": 0, "enabled": True}]
    engine.tick(now=0.0, entries=entries)
    assert sent == []


def test_tick_drops_bookkeeping_for_removed_entries():
    engine, sent = _engine_with_fake_sender()
    entries = [{"id": "e1", "arbitration_id": 0x100, "data": "01", "period_ms": 1000, "enabled": True}]
    engine.tick(now=0.0, entries=entries)
    assert "e1" in engine._next_due
    engine.tick(now=1.0, entries=[])
    assert "e1" not in engine._next_due


def test_send_entry_reports_error_on_bad_frame():
    engine, sent = _engine_with_fake_sender()
    entry = {"id": "e1", "data": "01"}  # no arbitration_id
    ok, error = engine.send_entry(entry)
    assert ok is False
    assert error
    assert sent == []


def test_send_entry_reports_failure_when_sender_returns_false():
    def failing_sender(backend, channel, frame):
        return False

    engine = SimEngine(sender=failing_sender)
    entry = {"id": "e1", "arbitration_id": 0x100, "data": "01"}
    ok, error = engine.send_entry(entry)
    assert ok is False
    assert error == "send failed"


def test_send_once_uses_persisted_entry():
    engine, sent = _engine_with_fake_sender()
    created = sim.create_entry({"name": "a", "arbitration_id": 0x100, "data": "01 02"})
    ok, error = engine.send_once(created["id"])
    assert ok is True
    assert error is None
    assert len(sent) == 1


def test_send_once_missing_entry():
    engine, sent = _engine_with_fake_sender()
    ok, error = engine.send_once("nope")
    assert ok is False
    assert error == "No such transmit entry"


def test_start_stop_scheduler_toggles_running():
    engine, sent = _engine_with_fake_sender()
    assert engine.is_running() is False
    assert engine.start() is True
    assert engine.is_running() is True
    assert engine.start() is False  # already running
    assert engine.stop() is True
    assert engine.is_running() is False
    assert engine.stop() is False  # already stopped


# -- router ---------------------------------------------------------------

@pytest.fixture
def client():
    # Use TestClient as a context manager so the app's lifespan runs and
    # creates the CAN database tables (see app.main.lifespan), matching the
    # pattern in test_db.py's router tests.
    with TestClient(app) as c:
        yield c


def test_router_create_list_and_get_entry(client):
    resp = client.post("/can/sim", json={"name": "Speed", "arbitration_id": "0x100", "data": "01 02"})
    assert resp.status_code == 200, resp.text
    entry_id = resp.json()["entry"]["id"]

    listed = client.get("/can/sim").json()
    assert listed["running"] is False
    assert any(e["id"] == entry_id for e in listed["entries"])

    got = client.get(f"/can/sim/{entry_id}")
    assert got.status_code == 200
    assert got.json()["name"] == "Speed"


def test_router_create_rejects_bad_arbitration_id(client):
    resp = client.post("/can/sim", json={"name": "Bad", "arbitration_id": "not-hex", "data": "01"})
    assert resp.status_code == 400


def test_router_create_rejects_invalid_frame(client):
    resp = client.post("/can/sim", json={
        "name": "TooLong", "arbitration_id": "0x100", "data": "00 " * 9,
    })
    assert resp.status_code == 400


def test_router_update_entry(client):
    created = client.post("/can/sim", json={"name": "A", "arbitration_id": "0x100", "data": "01"}).json()
    entry_id = created["entry"]["id"]
    resp = client.put(f"/can/sim/{entry_id}", json={"name": "B", "arbitration_id": "0x101", "data": "02"})
    assert resp.status_code == 200
    assert resp.json()["entry"]["name"] == "B"


def test_router_update_missing_entry_404(client):
    resp = client.put("/can/sim/nope", json={"name": "B", "arbitration_id": "0x101", "data": "02"})
    assert resp.status_code == 404


def test_router_delete_entry(client):
    created = client.post("/can/sim", json={"name": "A", "arbitration_id": "0x100", "data": "01"}).json()
    entry_id = created["entry"]["id"]
    resp = client.delete(f"/can/sim/{entry_id}")
    assert resp.status_code == 200
    assert client.get(f"/can/sim/{entry_id}").status_code == 404


def test_router_delete_missing_entry_404(client):
    assert client.delete("/can/sim/nope").status_code == 404


def test_router_enable_disable(client):
    created = client.post("/can/sim", json={"name": "A", "arbitration_id": "0x100", "data": "01"}).json()
    entry_id = created["entry"]["id"]
    resp = client.post(f"/can/sim/{entry_id}/disable")
    assert resp.json()["entry"]["enabled"] is False
    resp = client.post(f"/can/sim/{entry_id}/enable")
    assert resp.json()["entry"]["enabled"] is True


def test_router_send_one_shot(client):
    created = client.post("/can/sim", json={"name": "A", "arbitration_id": "0x100", "data": "01"}).json()
    entry_id = created["entry"]["id"]
    resp = client.post(f"/can/sim/{entry_id}/send")
    assert resp.status_code == 200
    body = resp.json()
    # No real can0 interface on the test host: send degrades to a safe False
    # rather than raising, exactly like the socketcan provider does directly.
    assert body["ok"] is False


def test_router_send_missing_entry_404(client):
    resp = client.post("/can/sim/nope/send")
    assert resp.status_code == 404


def test_router_scheduler_start_stop_status(client):
    assert client.get("/can/sim/scheduler/status").json()["running"] is False
    start = client.post("/can/sim/scheduler/start")
    assert start.json()["running"] is True
    assert client.get("/can/sim/scheduler/status").json()["running"] is True
    stop = client.post("/can/sim/scheduler/stop")
    assert stop.json()["running"] is False
    assert client.get("/can/sim/scheduler/status").json()["running"] is False


def test_router_create_with_unknown_database_id_404s(client):
    resp = client.post("/can/sim", json={
        "name": "A", "arbitration_id": "0x100", "database_id": 999,
        "message": "M", "signals": {},
    })
    assert resp.status_code == 404


def test_ui_page_renders(client):
    resp = client.get("/ui/can-sim")
    assert resp.status_code == 200
    assert "CAN Signal Simulation" in resp.text
