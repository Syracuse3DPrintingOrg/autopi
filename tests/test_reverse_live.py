"""Live-bus additions to Signal Finder: the pure reference-free activity
summary (:func:`app.can.reverse.activity_survey`), and the
``/reverse/capture-live`` and ``/reverse/snapshot`` endpoints, which must
report a clean "unavailable" result off real hardware rather than crashing.
"""
from __future__ import annotations

import queue

import pytest
from starlette.testclient import TestClient

from app.can import capture as cap
from app.can import registry as can_registry
from app.can.base import Frame
from app.can.reverse import activity_survey
from app.main import app


@pytest.fixture(autouse=True)
def _reset_can_state():
    yield
    cap.reset_inhale_sessions()
    can_registry.reset_channels()


# --------------------------------------------------------------------------
# activity_survey: pure, reference-free summary
# --------------------------------------------------------------------------

def test_activity_survey_empty_input():
    assert activity_survey({}) == []


def test_activity_survey_skips_ids_with_no_records():
    assert activity_survey({0x10: []}) == []


def test_activity_survey_flags_a_changing_byte_and_leaves_a_static_one_out():
    records = [
        {"arbitration_id": 0x100, "data": [i % 4, 0xAA, 0, 0, 0, 0, 0, 0], "timestamp": i * 0.1}
        for i in range(20)
    ]
    ranked = activity_survey({0x100: records})
    assert len(ranked) == 1
    entry = ranked[0]
    assert entry["arbitration_id"] == 0x100
    assert entry["frame_count"] == 20
    assert 0 in entry["changing_bytes"]
    assert 1 not in entry["changing_bytes"]  # byte 1 is always 0xAA: static


def test_activity_survey_ranks_the_busiest_id_first():
    quiet = [{"arbitration_id": 0x10, "data": [0, 0], "timestamp": i * 0.1} for i in range(10)]
    busy = [{"arbitration_id": 0x20, "data": [i % 5, i % 7], "timestamp": i * 0.1} for i in range(10)]
    ranked = activity_survey({0x10: quiet, 0x20: busy})
    assert ranked[0]["arbitration_id"] == 0x20
    assert ranked[0]["changing_bytes"]
    assert ranked[1]["arbitration_id"] == 0x10
    assert ranked[1]["changing_bytes"] == []


def test_activity_survey_ties_break_on_arbitration_id():
    a = [{"arbitration_id": 0x30, "data": [i % 3], "timestamp": i * 0.1} for i in range(10)]
    b = [{"arbitration_id": 0x20, "data": [i % 3], "timestamp": i * 0.1} for i in range(10)]
    ranked = activity_survey({0x30: a, 0x20: b})
    assert [r["arbitration_id"] for r in ranked] == [0x20, 0x30]


# --------------------------------------------------------------------------
# /reverse/capture-live and /reverse/snapshot: gate on interface availability
# --------------------------------------------------------------------------

def test_capture_live_reports_unavailable_off_hardware():
    client = TestClient(app)
    resp = client.post("/reverse/capture-live", json={"channel": "vcan-does-not-exist", "backend": "socketcan"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "error" in body


def test_snapshot_reports_unavailable_off_hardware():
    client = TestClient(app)
    resp = client.post("/reverse/snapshot", json={"channel": "vcan-does-not-exist", "backend": "socketcan"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "error" in body


# --------------------------------------------------------------------------
# /reverse/capture-live and /reverse/snapshot: happy path with a fake provider
# --------------------------------------------------------------------------

class _FakeProvider:
    def __init__(self) -> None:
        self._queue: "queue.Queue" = queue.Queue()

    @property
    def available(self) -> bool:
        return True

    def push(self, frame: Frame) -> None:
        self._queue.put(frame)

    def recv(self, timeout: float = 0.5):
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def send(self, frame: Frame) -> bool:
        return True

    def close(self) -> None:
        pass


def test_capture_live_saves_and_returns_frames(monkeypatch):
    fake = _FakeProvider()
    monkeypatch.setattr("app.routers.reverse.get_channel", lambda channel, backend="socketcan", **kw: fake)
    monkeypatch.setattr(cap, "get_channel", lambda channel, backend="socketcan", **kw: fake)
    monkeypatch.setattr(cap, "open_channel", lambda channel, backend="socketcan", **kw: fake)
    monkeypatch.setattr("app.routers.reverse._capture_factory", lambda ch, be: (lambda *a, **k: fake))

    for i in range(3):
        fake.push(Frame(arbitration_id=0x100, data=[i]))

    client = TestClient(app)
    resp = client.post("/reverse/capture-live", json={"channel": "vcan0", "seconds": 0.5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["frame_count"] >= 3
    assert cap.get_capture(body["capture_id"]) is not None


def test_snapshot_summarizes_active_ids(monkeypatch):
    fake = _FakeProvider()
    monkeypatch.setattr("app.routers.reverse.get_channel", lambda channel, backend="socketcan", **kw: fake)
    monkeypatch.setattr(cap, "get_channel", lambda channel, backend="socketcan", **kw: fake)
    monkeypatch.setattr(cap, "open_channel", lambda channel, backend="socketcan", **kw: fake)
    monkeypatch.setattr("app.routers.reverse._capture_factory", lambda ch, be: (lambda *a, **k: fake))

    for i in range(10):
        fake.push(Frame(arbitration_id=0x200, data=[i % 3, 0xAA]))

    client = TestClient(app)
    resp = client.post("/reverse/snapshot", json={"channel": "vcan0", "seconds": 0.5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["capture_id"]
    ids = body["ids"]
    assert any(entry["arbitration_id"] == 0x200 for entry in ids)
    hit = next(entry for entry in ids if entry["arbitration_id"] == 0x200)
    assert 0 in hit["changing_bytes"]


def test_fire_opens_fd_channel_for_fd_frame(monkeypatch):
    # A CAN-FD frame (>8 data bytes) must be transmitted on an fd=True channel;
    # a classic socket rejects it and sends nothing.
    fake = _FakeProvider()
    seen: dict = {}

    def _get_channel(channel, backend="socketcan", **kw):
        seen["fd"] = kw.get("fd")
        return fake

    monkeypatch.setattr("app.routers.reverse.get_channel", _get_channel)
    monkeypatch.setattr("app.routers.reverse._capture_or_404",
                        lambda cid: {"backend": "socketcan", "channel": "vcan0"})
    monkeypatch.setattr("app.routers.reverse._frames_for_id",
                        lambda cap_, aid: [{"arbitration_id": 0x123,
                                            "data": list(range(12)), "is_fd": True,
                                            "timestamp": 0.0}])
    client = TestClient(app)
    resp = client.post("/reverse/fire",
                       json={"capture_id": "x", "arbitration_id": 0x123,
                             "channel": "vcan0", "byte": None})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert seen["fd"] is True


def test_fire_leaves_channel_mode_untouched_for_classic_frame(monkeypatch):
    # A classic frame must not force fd (fd=None leaves the channel's configured
    # mode alone), so classic sends keep working exactly as before.
    fake = _FakeProvider()
    seen: dict = {}

    def _get_channel(channel, backend="socketcan", **kw):
        seen["fd"] = kw.get("fd")
        return fake

    monkeypatch.setattr("app.routers.reverse.get_channel", _get_channel)
    monkeypatch.setattr("app.routers.reverse._capture_or_404",
                        lambda cid: {"backend": "socketcan", "channel": "vcan0"})
    monkeypatch.setattr("app.routers.reverse._frames_for_id",
                        lambda cap_, aid: [{"arbitration_id": 0x123,
                                            "data": [1, 2, 3], "is_fd": False,
                                            "timestamp": 0.0}])
    client = TestClient(app)
    resp = client.post("/reverse/fire",
                       json={"capture_id": "x", "arbitration_id": 0x123,
                             "channel": "vcan0", "byte": None})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert seen["fd"] is None


def test_verify_control_opens_fd_channel_for_fd_frame(monkeypatch):
    fake = _FakeProvider()
    seen: dict = {}

    def _get_channel(channel, backend="socketcan", **kw):
        seen["fd"] = kw.get("fd")
        return fake

    monkeypatch.setattr("app.routers.reverse.get_channel", _get_channel)
    monkeypatch.setattr(cap, "get_channel", lambda channel, backend="socketcan", **kw: fake)
    monkeypatch.setattr(cap, "open_channel", lambda channel, backend="socketcan", **kw: fake)
    monkeypatch.setattr("app.routers.reverse._capture_factory", lambda ch, be: (lambda *a, **k: fake))
    monkeypatch.setattr("app.can.detect.list_can_interfaces", lambda: [{"name": "vcan0", "up": True}])
    monkeypatch.setattr("app.routers.reverse._capture_or_404",
                        lambda cid: {"backend": "socketcan",
                                     "frames": [{"arbitration_id": 0x123,
                                                 "data": list(range(12)), "is_fd": True,
                                                 "timestamp": 0.0}]})
    client = TestClient(app)
    resp = client.post("/reverse/verify-control",
                       json={"capture_id": "x", "arbitration_id": 0x123, "channel": "vcan0",
                             "byte": None, "baseline_s": 0.02, "inject_s": 0.2, "period_ms": 10})
    assert resp.status_code == 200
    assert seen["fd"] is True


def test_can_tx_loop_opens_fd_channel_for_fd_frame(monkeypatch):
    # The periodic sender must also request an fd=True channel for an FD frame.
    from app.services import can_tx
    import threading

    seen: dict = {}
    fake = _FakeProvider()

    def _get_channel(channel, **kw):
        seen["fd"] = kw.get("fd")
        return fake

    monkeypatch.setattr("app.can.get_channel", _get_channel)
    stop_ev = threading.Event()
    stop_ev.set()  # stop immediately after the provider is resolved
    can_tx._loop("vcan0", 0x123, list(range(12)), 10, True, False, stop_ev)
    assert seen["fd"] is True

    stop_ev2 = threading.Event()
    stop_ev2.set()
    can_tx._loop("vcan0", 0x123, [1, 2, 3], 10, False, False, stop_ev2)
    assert seen["fd"] is None


def test_verify_control_reports_inject_failure_not_no_effect(monkeypatch):
    # Regression: a silent send failure used to be reported as "no effect", which
    # reads as "it is a status". It must instead say the injection failed.
    fake = _FakeProvider()
    fake.send = lambda frame: False  # every transmit fails
    monkeypatch.setattr("app.routers.reverse.get_channel", lambda channel, backend="socketcan", **kw: fake)
    monkeypatch.setattr(cap, "get_channel", lambda channel, backend="socketcan", **kw: fake)
    monkeypatch.setattr(cap, "open_channel", lambda channel, backend="socketcan", **kw: fake)
    monkeypatch.setattr("app.routers.reverse._capture_factory", lambda ch, be: (lambda *a, **k: fake))
    monkeypatch.setattr("app.can.detect.list_can_interfaces", lambda: [{"name": "vcan0", "up": True}])
    monkeypatch.setattr("app.routers.reverse._capture_or_404",
                        lambda cid: {"backend": "socketcan",
                                     "frames": [{"arbitration_id": 0x123, "data": [1, 2, 3], "timestamp": 0.0}]})
    client = TestClient(app)
    resp = client.post("/reverse/verify-control",
                       json={"capture_id": "x", "arbitration_id": 0x123, "channel": "vcan0",
                             "byte": None, "baseline_s": 0.02, "inject_s": 0.2, "period_ms": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["injected"] == 0
    assert "Could not inject" in body["error"]


def test_fire_flood_uses_burst(monkeypatch):
    fake = _FakeProvider()
    monkeypatch.setattr("app.routers.reverse.get_channel", lambda channel, backend="socketcan", **kw: fake)
    monkeypatch.setattr("app.routers.reverse._capture_or_404",
                        lambda cid: {"backend": "socketcan",
                                     "frames": [{"arbitration_id": 0x123, "data": [1, 2, 3], "timestamp": 0.0}]})
    calls = {}
    def fake_burst(channel, arb, data, **kw):
        calls.update({"channel": channel, "arb": arb, "period": kw.get("period_ms"), "duration": kw.get("duration_ms")})
        return 42
    monkeypatch.setattr("app.services.can_tx.burst", fake_burst)
    client = TestClient(app)
    resp = client.post("/reverse/fire", json={"capture_id": "x", "arbitration_id": 0x123,
                                              "channel": "vcan0", "byte": None, "burst_ms": 1000})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["mode"] == "burst" and body["injected"] == 42
    assert calls["arb"] == 0x123 and calls["duration"] == 1000 and calls["period"] == 10


def test_to_workbench_creates_sim_entry(monkeypatch):
    from app.can import simulation as sim
    monkeypatch.setattr("app.routers.reverse._capture_or_404",
                        lambda cid: {"backend": "socketcan", "channel": "can1",
                                     "frames": [{"arbitration_id": 0x5C6, "data": [1, 2, 3], "timestamp": 0.0}]})
    client = TestClient(app)
    before = len(sim.list_entries())
    resp = client.post("/reverse/to-workbench", json={"capture_id": "x", "arbitration_id": 0x5C6,
                                                      "channel": "can1", "byte": None, "name": "Mute"})
    assert resp.status_code == 200 and resp.json()["ok"] is True
    eid = resp.json()["entry_id"]
    entry = sim.get_entry(eid)
    assert entry is not None and entry["arbitration_id"] == 0x5C6 and entry["channel"] == "can1"
    assert entry["enabled"] is False  # added paused, user runs it deliberately
    sim.delete_entry(eid)
    assert len(sim.list_entries()) == before


def test_vision_frame_reads_and_marks(monkeypatch):
    from app.services import ref_recorder as rec
    rec.start("sweep")  # a sweep reference so mark() records
    monkeypatch.setattr("app.routers.reverse.llm.read_dashboard_value",
                        lambda raw, mime, what: {"value": 42.0})
    client = TestClient(app)
    resp = client.post("/reverse/reference/vision-frame",
                       json={"image": "data:image/jpeg;base64,QUJD", "what": "speed"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["value"] == 42.0 and body["recording"] is True
    rec.stop()


def test_vision_frame_handles_unreadable(monkeypatch):
    from app.services import ref_recorder as rec
    rec.start("sweep")
    monkeypatch.setattr("app.routers.reverse.llm.read_dashboard_value",
                        lambda raw, mime, what: {"value": None})
    client = TestClient(app)
    resp = client.post("/reverse/reference/vision-frame", json={"image": "rawbase64", "what": "rpm"})
    assert resp.json()["ok"] is True and resp.json()["value"] is None
    rec.stop()


def test_graph_endpoint_decodes_field_over_time(monkeypatch):
    monkeypatch.setattr("app.routers.reverse._capture_or_404",
                        lambda cid: {"frames": [
                            {"arbitration_id": 0x100, "data": [i, 0], "timestamp": float(i)} for i in range(5)]})
    client = TestClient(app)
    resp = client.post("/reverse/graph", json={"capture_id": "x", "arbitration_id": 0x100,
                                               "start_bit": 0, "length": 8, "scale": 2.0, "offset": 1.0})
    assert resp.status_code == 200
    pts = resp.json()["points"]
    assert len(pts) == 5
    assert pts[0] == {"t": 0.0, "value": 1.0}   # 0*2+1
    assert pts[3] == {"t": 3.0, "value": 7.0}   # 3*2+1
