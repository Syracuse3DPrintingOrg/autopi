"""Live CAN bus monitor: pure ring-buffer/decode logic, the background
reader driven with a fake provider (no real thread timing dependency beyond
start/stop), and the router, all without real CAN hardware.
"""
from __future__ import annotations

import queue
import time
from collections import deque

import pytest
from starlette.testclient import TestClient

from app.can import monitor as mon
from app.can.base import Frame
from app.can.monitor import MonitorChannel, decode_record, ingest_frame
from app.main import app


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    mon.reset_monitors()


# -- ring buffer update (pure) -----------------------------------------------

def test_ingest_frame_appends_record_with_hex_and_count():
    buffer: deque = deque(maxlen=10)
    counts: dict[int, int] = {}
    frame = Frame(arbitration_id=0x100, data=[1, 2, 0xFF])
    record = ingest_frame(buffer, counts, frame, timestamp=123.0)
    assert record["arbitration_id"] == 0x100
    assert record["data"] == [1, 2, 0xFF]
    assert record["hex"] == "01 02 FF"
    assert record["timestamp"] == 123.0
    assert record["count"] == 1
    assert len(buffer) == 1


def test_ingest_frame_bumps_count_per_id():
    buffer: deque = deque(maxlen=10)
    counts: dict[int, int] = {}
    ingest_frame(buffer, counts, Frame(arbitration_id=0x100, data=[1]), timestamp=1.0)
    ingest_frame(buffer, counts, Frame(arbitration_id=0x100, data=[2]), timestamp=2.0)
    record = ingest_frame(buffer, counts, Frame(arbitration_id=0x100, data=[3]), timestamp=3.0)
    assert record["count"] == 3
    assert counts[0x100] == 3


def test_ingest_frame_tracks_separate_ids_independently():
    buffer: deque = deque(maxlen=10)
    counts: dict[int, int] = {}
    ingest_frame(buffer, counts, Frame(arbitration_id=0x100, data=[1]), timestamp=1.0)
    record = ingest_frame(buffer, counts, Frame(arbitration_id=0x200, data=[2]), timestamp=2.0)
    assert record["count"] == 1
    assert counts == {0x100: 1, 0x200: 1}


def test_ingest_frame_ring_buffer_drops_oldest_past_maxlen():
    buffer: deque = deque(maxlen=3)
    counts: dict[int, int] = {}
    for i in range(5):
        ingest_frame(buffer, counts, Frame(arbitration_id=i, data=[]), timestamp=float(i))
    assert len(buffer) == 3
    assert [r["arbitration_id"] for r in buffer] == [2, 3, 4]
    # Counts are not trimmed with the ring: they reflect everything seen.
    assert len(counts) == 5


def test_ingest_frame_defaults_timestamp_to_now():
    buffer: deque = deque(maxlen=10)
    counts: dict[int, int] = {}
    before = time.time()
    record = ingest_frame(buffer, counts, Frame(arbitration_id=0x100, data=[]))
    after = time.time()
    assert before <= record["timestamp"] <= after


def test_ingest_frame_empty_data_has_empty_hex():
    buffer: deque = deque(maxlen=10)
    counts: dict[int, int] = {}
    record = ingest_frame(buffer, counts, Frame(arbitration_id=0x100, data=[]), timestamp=1.0)
    assert record["hex"] == ""


# -- decode (pure) ------------------------------------------------------------

def test_decode_record_returns_none_without_dbc_text():
    record = {"arbitration_id": 0x100, "data": [1, 2]}
    assert decode_record(record, None) is None


def test_decode_record_returns_decoded_signals(monkeypatch):
    def fake_decode(dbc_text, arbitration_id, data):
        assert dbc_text == "fake dbc"
        assert arbitration_id == 0x100
        assert data == b"\x01\x02"
        return {"SPEED": 42}

    monkeypatch.setattr("app.can.dbc.decode", fake_decode)
    record = {"arbitration_id": 0x100, "data": [1, 2]}
    assert decode_record(record, "fake dbc") == {"SPEED": 42}


def test_decode_record_returns_none_when_id_not_in_database(monkeypatch):
    def fake_decode(dbc_text, arbitration_id, data):
        raise KeyError("unknown message id")

    monkeypatch.setattr("app.can.dbc.decode", fake_decode)
    record = {"arbitration_id": 0x999, "data": [1]}
    assert decode_record(record, "fake dbc") is None


# -- MonitorChannel background reader (fake provider, no hardware) ----------

class _FakeProvider:
    """Provider double: recv() drains an injected queue, degrades to None on
    an empty timeout exactly like a real provider does on a quiet bus."""

    def __init__(self, available: bool = True) -> None:
        self._available = available
        self._queue: queue.Queue = queue.Queue()

    @property
    def available(self) -> bool:
        return self._available

    def push(self, frame: Frame) -> None:
        self._queue.put(frame)

    def recv(self, timeout: float | None = None):
        try:
            return self._queue.get(timeout=timeout or 0.05)
        except queue.Empty:
            return None


def test_monitor_channel_status_when_not_started():
    fake = _FakeProvider(available=True)
    monitor = MonitorChannel("can0")
    import app.can.monitor as monitor_mod
    monitor_original = monitor_mod.get_channel
    monitor_mod.get_channel = lambda *a, **k: fake
    try:
        status = monitor.status()
        assert status["running"] is False
        assert status["live"] is True
        assert status["frame_count"] == 0
    finally:
        monitor_mod.get_channel = monitor_original


def test_monitor_channel_reports_not_live_when_unavailable():
    fake = _FakeProvider(available=False)
    monitor = MonitorChannel("can0")
    import app.can.monitor as monitor_mod
    monitor_original = monitor_mod.get_channel
    monitor_mod.get_channel = lambda *a, **k: fake
    try:
        assert monitor.status()["live"] is False
    finally:
        monitor_mod.get_channel = monitor_original


def test_monitor_channel_start_stop_toggles_running():
    fake = _FakeProvider(available=True)
    monitor = MonitorChannel("can0")
    import app.can.monitor as monitor_mod
    monitor_original = monitor_mod.get_channel
    monitor_mod.get_channel = lambda *a, **k: fake
    try:
        assert monitor.is_running() is False
        assert monitor.start() is True
        assert monitor.is_running() is True
        assert monitor.start() is False  # already running
        assert monitor.stop() is True
        assert monitor.is_running() is False
        assert monitor.stop() is False  # already stopped
    finally:
        monitor_mod.get_channel = monitor_original


def test_monitor_channel_collects_pushed_frames():
    fake = _FakeProvider(available=True)
    monitor = MonitorChannel("can0")
    import app.can.monitor as monitor_mod
    monitor_original = monitor_mod.get_channel
    monitor_mod.get_channel = lambda *a, **k: fake
    try:
        monitor.start()
        fake.push(Frame(arbitration_id=0x123, data=[1, 2, 3]))
        fake.push(Frame(arbitration_id=0x123, data=[4, 5, 6]))
        deadline = time.time() + 2.0
        while time.time() < deadline and len(monitor.frames()) < 2:
            time.sleep(0.02)
        frames = monitor.frames()
        assert len(frames) == 2
        assert frames[-1]["arbitration_id"] == 0x123
        assert frames[-1]["count"] == 2
    finally:
        monitor.stop()
        monitor_mod.get_channel = monitor_original


# -- router -------------------------------------------------------------------

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_router_start_stop_status(client):
    resp = client.post("/can/monitor/start", json={"channel": "can0", "backend": "socketcan"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["started"] is True
    # No real can0 interface on the test host: the reader starts fine but the
    # provider degrades to "not live" instead of erroring.
    assert body["status"]["live"] is False

    status = client.get("/can/monitor/status").json()
    assert any(c["channel"] == "can0" for c in status["channels"])

    stop = client.post("/can/monitor/stop", json={"channel": "can0", "backend": "socketcan"})
    assert stop.status_code == 200
    assert stop.json()["stopped"] is True


def test_router_stop_unknown_channel_reports_not_stopped(client):
    resp = client.post("/can/monitor/stop", json={"channel": "canX", "backend": "socketcan"})
    assert resp.status_code == 200
    assert resp.json()["stopped"] is False


def test_router_frames_empty_by_default(client):
    resp = client.get("/can/monitor/frames", params={"channel": "can0"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["frames"] == []
    assert body["status"]["channel"] == "can0"


def test_router_frames_unknown_database_id_404s(client):
    resp = client.get("/can/monitor/frames", params={"channel": "can0", "database_id": 999})
    assert resp.status_code == 404


def test_ui_page_renders(client):
    resp = client.get("/ui/can-monitor")
    assert resp.status_code == 200
    assert "CAN Bus Monitor" in resp.text
