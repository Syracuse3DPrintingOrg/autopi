"""Inhale/exhale: pure record shape and replay-timing math, the background
inhale/exhale sessions driven with a fake provider/clock (no real hardware or
real waiting), buffer persistence, and the router.
"""
from __future__ import annotations

import queue
import time

import pytest
from starlette.testclient import TestClient

from app.can import capture as cap
from app.can import firewall as fw
from app.can.base import Frame
from app.can.capture import (
    ExhaleSession,
    InhaleSession,
    compute_replay_delays,
    frame_to_record,
    record_to_frame,
    replay_records,
)
from app.main import app


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    cap.reset_inhale_sessions()
    cap.exhale.stop()


# -- record shape (pure) --------------------------------------------------

def test_frame_to_record_roundtrips_through_record_to_frame():
    frame = Frame(arbitration_id=0x123, data=[1, 2, 3], is_extended_id=True)
    record = frame_to_record(frame, timestamp=42.0)
    assert record["arbitration_id"] == 0x123
    assert record["timestamp"] == 42.0
    rebuilt = record_to_frame(record)
    assert rebuilt.arbitration_id == 0x123
    assert rebuilt.data == [1, 2, 3]
    assert rebuilt.is_extended_id is True


def test_record_to_frame_accepts_hex_string_data():
    record = {"arbitration_id": 0x100, "data": "01 02 03"}
    frame = record_to_frame(record)
    assert frame.data == [1, 2, 3]


# -- replay timing math (pure) --------------------------------------------

def test_compute_replay_delays_first_frame_has_no_wait():
    records = [{"timestamp": 5.0}, {"timestamp": 6.0}]
    delays = compute_replay_delays(records)
    assert delays == [0.0, 1.0]


def test_compute_replay_delays_scales_by_speed():
    records = [{"timestamp": 0.0}, {"timestamp": 2.0}]
    delays = compute_replay_delays(records, speed=2.0)
    assert delays == [0.0, 1.0]


def test_compute_replay_delays_never_negative_on_out_of_order_timestamps():
    records = [{"timestamp": 5.0}, {"timestamp": 3.0}]
    delays = compute_replay_delays(records)
    assert delays == [0.0, 0.0]


def test_compute_replay_delays_zero_or_negative_speed_treated_as_realtime():
    records = [{"timestamp": 0.0}, {"timestamp": 1.0}]
    assert compute_replay_delays(records, speed=0) == compute_replay_delays(records, speed=1.0)
    assert compute_replay_delays(records, speed=-5) == compute_replay_delays(records, speed=1.0)


def test_compute_replay_delays_empty_list():
    assert compute_replay_delays([]) == []


# -- replay_records driver (fake sender/sleep, no real hardware or waiting) --

def test_replay_records_sends_each_record_and_sleeps_the_gap():
    records = [
        {"arbitration_id": 0x100, "data": [1], "timestamp": 0.0},
        {"arbitration_id": 0x100, "data": [2], "timestamp": 0.5},
    ]
    sent = []
    slept = []
    stats = replay_records(
        records, "can1", "socketcan",
        sender=lambda b, c, f: sent.append((b, c, f)) or True,
        sleep_fn=lambda s: slept.append(s),
    )
    assert stats == {"sent": 2, "blocked": 0, "rewritten": 0, "injected": 0, "errors": 0}
    assert [f.data for _, _, f in sent] == [[1], [2]]
    assert slept == [0.5]  # the first record's zero delay never calls sleep


def test_replay_records_counts_send_failures_as_errors():
    records = [{"arbitration_id": 0x100, "data": [1], "timestamp": 0.0}]
    stats = replay_records(records, "can1", "socketcan", sender=lambda b, c, f: False, sleep_fn=lambda s: None)
    assert stats["errors"] == 1
    assert stats["sent"] == 0


def test_replay_records_applies_rules_block():
    records = [{"arbitration_id": 0x100, "data": [1], "timestamp": 0.0}]
    rules = [{"id": "r1", "action": "block", "direction": "both", "match": {"arbitration_id": 0x100}}]
    sent = []
    stats = replay_records(
        records, "can1", "socketcan", rules=rules,
        sender=lambda b, c, f: sent.append(f) or True, sleep_fn=lambda s: None,
    )
    assert stats["blocked"] == 1
    assert sent == []


def test_replay_records_applies_rules_rewrite(monkeypatch):
    monkeypatch.setattr("app.can.dbc.decode", lambda *a: {"SPEED": 1})
    monkeypatch.setattr("app.can.dbc.encode", lambda *a, **k: [9, 9])
    records = [{"arbitration_id": 0x200, "data": [1, 2], "timestamp": 0.0}]
    rules = [{
        "id": "r1", "action": "rewrite", "direction": "both", "match": {"arbitration_id": 0x200},
        "rewrite": {"database_id": 1, "message": "M", "signals": {"SPEED": 5}},
    }]
    sent = []
    stats = replay_records(
        records, "can1", "socketcan", rules=rules, dbc_lookup=lambda d: "fake dbc",
        sender=lambda b, c, f: sent.append(f) or True, sleep_fn=lambda s: None,
    )
    assert stats["rewritten"] == 1
    assert sent[0].data == [9, 9]


def test_replay_records_rule_scoped_to_a_direction_does_not_apply_during_replay():
    # Replay uses direction "replay"; only rules scoped to "both" apply.
    records = [{"arbitration_id": 0x100, "data": [1], "timestamp": 0.0}]
    rules = [{"id": "r1", "action": "block", "direction": "a_to_b", "match": {"arbitration_id": 0x100}}]
    sent = []
    stats = replay_records(
        records, "can1", "socketcan", rules=rules,
        sender=lambda b, c, f: sent.append(f) or True, sleep_fn=lambda s: None,
    )
    assert stats["blocked"] == 0
    assert stats["sent"] == 1


def test_replay_records_should_continue_stops_early():
    records = [
        {"arbitration_id": 0x100, "data": [1], "timestamp": 0.0},
        {"arbitration_id": 0x100, "data": [2], "timestamp": 0.1},
    ]
    sent = []
    stats = replay_records(
        records, "can1", "socketcan",
        sender=lambda b, c, f: sent.append(f) or True, sleep_fn=lambda s: None,
        should_continue=lambda: len(sent) < 1,
    )
    assert len(sent) == 1
    assert stats["sent"] == 1


# -- capture persistence -------------------------------------------------

def test_save_and_get_capture_roundtrip():
    saved = cap.save_capture("run1", "can0", "socketcan", [{"arbitration_id": 1, "data": [], "timestamp": 0.0}])
    assert saved["id"]
    fetched = cap.get_capture(saved["id"])
    assert fetched["name"] == "run1"
    assert len(fetched["frames"]) == 1


def test_list_captures_omits_frames_but_reports_count():
    cap.save_capture("run1", "can0", "socketcan", [{"arbitration_id": 1, "data": [], "timestamp": 0.0}] * 3)
    listed = cap.list_captures()
    assert len(listed) == 1
    assert "frames" not in listed[0]
    assert listed[0]["frame_count"] == 3


def test_delete_capture_removes_it():
    saved = cap.save_capture("run1", "can0", "socketcan", [])
    assert cap.delete_capture(saved["id"]) is True
    assert cap.get_capture(saved["id"]) is None


def test_delete_missing_capture_returns_false():
    assert cap.delete_capture("nope") is False


# -- InhaleSession (fake provider, no hardware) ---------------------------

class _FakeProvider:
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


def test_inhale_session_start_stop_toggles_running():
    fake = _FakeProvider()
    session = InhaleSession("can0", channel_factory=lambda *a, **k: fake)
    assert session.is_running() is False
    assert session.start("run1") is True
    assert session.is_running() is True
    assert session.start("run1") is False  # already running
    saved = session.stop()
    assert saved is not None
    assert session.is_running() is False
    assert session.stop() is None


def test_inhale_session_captures_pushed_frames_and_saves_on_stop():
    fake = _FakeProvider()
    session = InhaleSession("can0", channel_factory=lambda *a, **k: fake)
    session.start("run1")
    fake.push(Frame(arbitration_id=0x100, data=[1]))
    fake.push(Frame(arbitration_id=0x100, data=[2]))
    deadline = time.time() + 2.0
    while time.time() < deadline and session.status()["frame_count"] < 2:
        time.sleep(0.02)
    saved = session.stop()
    assert saved["name"] == "run1"
    assert len(saved["frames"]) == 2
    assert cap.get_capture(saved["id"]) is not None


def test_inhale_session_stops_itself_at_max_frames():
    fake = _FakeProvider()
    session = InhaleSession("can0", channel_factory=lambda *a, **k: fake)
    session.start("run1", max_frames=2)
    for i in range(5):
        fake.push(Frame(arbitration_id=0x100, data=[i]))
    deadline = time.time() + 2.0
    while time.time() < deadline and session.is_running():
        time.sleep(0.02)
    assert session.is_running() is False
    saved = session.stop()
    # The session persisted its capture on its own once the limit was hit;
    # stop() hands back that already-saved result.
    assert saved is not None
    assert len(saved["frames"]) == 2
    captures = cap.list_captures()
    assert captures[0]["frame_count"] == 2


def test_get_inhale_session_returns_same_instance_for_same_channel():
    a = cap.get_inhale_session("can0", backend="socketcan")
    b = cap.get_inhale_session("can0", backend="socketcan")
    assert a is b


# -- ExhaleSession (fake sender/sleep, no real hardware or waiting) --------

def test_exhale_session_replays_capture_and_reports_status():
    saved = cap.save_capture("run1", "can0", "socketcan", [
        {"arbitration_id": 0x100, "data": [1], "timestamp": 0.0},
        {"arbitration_id": 0x100, "data": [2], "timestamp": 0.01},
    ])
    sent = []
    session = ExhaleSession(sender=lambda b, c, f: sent.append(f) or True, sleep_fn=lambda s: None)
    assert session.start(saved, "can1", "socketcan") is True
    deadline = time.time() + 2.0
    while time.time() < deadline and session.is_running():
        time.sleep(0.02)
    status = session.status()
    assert status["running"] is False
    assert status["stats"]["sent"] == 2
    assert len(sent) == 2


def test_exhale_session_refuses_concurrent_replay():
    saved = cap.save_capture("run1", "can0", "socketcan", [
        {"arbitration_id": 0x100, "data": [1], "timestamp": 0.0},
    ] * 20)
    session = ExhaleSession(sender=lambda b, c, f: True, sleep_fn=lambda s: time.sleep(0.05))
    assert session.start(saved, "can1", "socketcan") is True
    assert session.start(saved, "can1", "socketcan") is False
    session.stop()


def test_exhale_session_stop_cancels_early():
    saved = cap.save_capture("run1", "can0", "socketcan", [
        {"arbitration_id": 0x100, "data": [1], "timestamp": float(i)} for i in range(50)
    ])
    sent = []
    session = ExhaleSession(sender=lambda b, c, f: sent.append(f) or True, sleep_fn=lambda s: time.sleep(0.05))
    session.start(saved, "can1", "socketcan")
    time.sleep(0.1)
    assert session.stop() is True
    assert len(sent) < 50


# -- router ---------------------------------------------------------------

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_router_inhale_start_stop_status(client):
    resp = client.post("/firewall/inhale/start", json={"name": "run1", "channel": "can0"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["started"] is True

    status = client.get("/firewall/inhale/status", params={"channel": "can0"}).json()
    assert status["running"] is True

    stop = client.post("/firewall/inhale/stop", params={"channel": "can0"})
    assert stop.status_code == 200
    assert stop.json()["capture"]["name"] == "run1"


def test_router_inhale_stop_when_not_running_400s(client):
    resp = client.post("/firewall/inhale/stop", params={"channel": "can9"})
    assert resp.status_code == 400


def test_router_captures_list_get_delete(client):
    cap.save_capture("run1", "can0", "socketcan", [{"arbitration_id": 1, "data": [], "timestamp": 0.0}])
    listed = client.get("/firewall/captures").json()
    assert len(listed["captures"]) == 1
    capture_id = listed["captures"][0]["id"]

    got = client.get(f"/firewall/captures/{capture_id}")
    assert got.status_code == 200
    assert got.json()["frames"]

    deleted = client.delete(f"/firewall/captures/{capture_id}")
    assert deleted.status_code == 200
    assert client.get(f"/firewall/captures/{capture_id}").status_code == 404


def test_router_get_missing_capture_404s(client):
    assert client.get("/firewall/captures/nope").status_code == 404


def test_router_exhale_start_missing_capture_404s(client):
    resp = client.post("/firewall/captures/nope/exhale", json={"channel": "can1"})
    assert resp.status_code == 404


def test_router_exhale_start_stop_status(client):
    saved = cap.save_capture("run1", "can0", "socketcan", [
        {"arbitration_id": 0x100, "data": [1], "timestamp": float(i)} for i in range(10)
    ])
    resp = client.post(f"/firewall/captures/{saved['id']}/exhale", json={"channel": "can1", "speed": 100.0})
    assert resp.status_code == 200, resp.text

    deadline = time.time() + 2.0
    while time.time() < deadline and client.get("/firewall/exhale/status").json()["running"]:
        time.sleep(0.05)
    status = client.get("/firewall/exhale/status").json()
    assert status["running"] is False


def test_router_exhale_stop_when_idle(client):
    resp = client.post("/firewall/exhale/stop")
    assert resp.status_code == 200
    assert resp.json()["stopped"] is False
