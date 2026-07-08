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
