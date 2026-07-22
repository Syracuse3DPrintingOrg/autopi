"""Reference recorder tests: the pure pulse-train builder
(:func:`app.can.reverse.reference_from_events`), the recorder service's
start/mark/event/stop/get/clear roundtrip (deterministic via a monkeypatched
clock), an end-to-end recovery of a planted toggling bit fed a pulse
reference, and the ``/reverse/reference/*`` router endpoints.
"""
from __future__ import annotations

import queue
import threading

import pytest
from starlette.testclient import TestClient

from app.can import capture as cap
from app.can.base import Frame
from app.can.reverse import bitsearch, reference_from_events
from app.main import app
from app.services import ref_recorder as rec


@pytest.fixture(autouse=True)
def _reset_capture_state():
    yield
    cap.reset_inhale_sessions()


# --------------------------------------------------------------------------
# reference_from_events: pure pulse-train shape
# --------------------------------------------------------------------------

def test_reference_from_events_empty_is_empty():
    assert reference_from_events([]) == []


def test_reference_from_events_high_during_window_low_outside():
    ref = reference_from_events([5.0], window=0.4, span=(0.0, 10.0), samples=21)
    on = [p for p in ref if 5.0 <= p["t"] < 5.4]
    off_before = [p for p in ref if p["t"] < 5.0]
    off_after = [p for p in ref if p["t"] >= 5.4]
    assert on and all(p["value"] == 1.0 for p in on)
    assert off_before and all(p["value"] == 0.0 for p in off_before)
    assert off_after and all(p["value"] == 0.0 for p in off_after)


def test_reference_from_events_all_points_marked_available():
    ref = reference_from_events([1.0, 2.0], span=(0.0, 3.0))
    assert all(p["available"] for p in ref)


def test_reference_from_events_custom_high_value():
    ref = reference_from_events([1.0], span=(0.0, 2.0), window=0.5, high=5.0, samples=10)
    assert any(p["value"] == 5.0 for p in ref)
    assert any(p["value"] == 0.0 for p in ref)


def test_reference_from_events_default_span_brackets_first_and_last_press():
    ref = reference_from_events([2.0, 8.0], window=0.3)
    times = [p["t"] for p in ref]
    assert min(times) <= 2.0 - 0.3 + 1e-9
    assert max(times) >= 8.0 + 0.3 - 1e-9


def test_reference_from_events_every_press_produces_a_high_point():
    # A lone-point sample grid could in principle step over a short pulse;
    # explicit edge insertion must guarantee it never does.
    events = [1.0, 1.05, 1.1, 5.0, 9.9]
    ref = reference_from_events(events, span=(0.0, 10.0), window=0.05, samples=3)
    for t0 in events:
        assert any(p["value"] != 0.0 and t0 <= p["t"] < t0 + 0.05 + 1e-9 for p in ref), t0


def test_reference_from_events_swapped_span_is_normalized():
    ref = reference_from_events([1.0], span=(5.0, 0.0), window=0.2, samples=5)
    assert ref
    assert all(0.0 <= p["t"] <= 5.0 for p in ref)


# --------------------------------------------------------------------------
# ref_recorder service: start/mark/event/stop/get/clear roundtrip
# --------------------------------------------------------------------------

def _fake_clock(monkeypatch, times):
    it = iter(times)
    monkeypatch.setattr(rec.time, "time", lambda: next(it))


def test_start_rejects_unknown_mode():
    with pytest.raises(ValueError):
        rec.start("dial")


def test_sweep_roundtrip(monkeypatch):
    _fake_clock(monkeypatch, [100.0, 100.5, 101.0, 200.0])
    status = rec.start("sweep")
    assert status == {"recording": True, "mode": "sweep", "count": 0}
    rec.mark(10.0)
    rec.mark(20.0)
    status = rec.mark(30.0)
    assert status["count"] == 3
    stopped = rec.stop()
    assert stopped["recording"] is False
    assert stopped["count"] == 3
    data = rec.get()
    assert data["mode"] == "sweep"
    assert data["points"] == [
        {"t": 100.0, "value": 10.0},
        {"t": 100.5, "value": 20.0},
        {"t": 101.0, "value": 30.0},
    ]
    cleared = rec.clear()
    assert cleared == {"recording": False, "mode": None, "count": 0}
    assert rec.get() == {"mode": None, "points": [], "events": []}


def test_button_roundtrip(monkeypatch):
    _fake_clock(monkeypatch, [1.0, 2.0, 3.0])
    rec.start("button")
    rec.event()
    status = rec.event()
    assert status["mode"] == "button"
    assert status["count"] == 2
    data = rec.get()
    assert data["events"] == [1.0, 2.0]


def test_mark_is_a_noop_when_not_recording(monkeypatch):
    _fake_clock(monkeypatch, [1.0])
    rec.clear()
    status = rec.mark(5.0)
    assert status["count"] == 0
    assert rec.get()["points"] == []


def test_mark_is_a_noop_in_button_mode(monkeypatch):
    _fake_clock(monkeypatch, [1.0])
    rec.start("button")
    rec.mark(5.0)
    assert rec.get()["points"] == []


def test_mark_uses_explicit_grab_time_not_now(monkeypatch):
    # A vision read stamps the frame's grab time, not the (later, variable) moment
    # the AI answered, so the point lines up with the captured frames.
    _fake_clock(monkeypatch, [500.0, 999.0])   # start clock, then "now" at mark
    rec.start("sweep")
    rec.mark(42.0, t=512.5)                     # grabbed at 512.5, AI answered at 999.0
    points = rec.get()["points"]
    assert points == [{"t": 512.5, "value": 42.0}]  # stamped at grab time, not 999.0


def test_event_is_a_noop_in_sweep_mode(monkeypatch):
    _fake_clock(monkeypatch, [1.0])
    rec.start("sweep")
    rec.event()
    assert rec.get()["events"] == []


def test_starting_again_discards_the_previous_recording(monkeypatch):
    _fake_clock(monkeypatch, [1.0, 2.0])
    rec.start("sweep")
    rec.mark(1.0)
    rec.start("button")
    assert rec.get() == {"mode": "button", "points": [], "events": []}


def test_concurrent_marks_lose_no_points():
    # mark() is a read-append-write cycle; without the module lock two threads
    # can read the same document and the later write drops the earlier append.
    # Explicit t values keep the test deterministic without a fake clock.
    rec.start("sweep")
    n_threads, per_thread = 8, 25
    barrier = threading.Barrier(n_threads)

    def worker(base: int) -> None:
        barrier.wait()
        for i in range(per_thread):
            k = base * per_thread + i
            rec.mark(float(k), t=float(k))

    threads = [threading.Thread(target=worker, args=(b,)) for b in range(n_threads)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    points = rec.get()["points"]
    assert len(points) == n_threads * per_thread
    assert {p["t"] for p in points} == {float(k) for k in range(n_threads * per_thread)}


# --------------------------------------------------------------------------
# End-to-end: a planted toggling bit recovered via a pulse-train reference
# --------------------------------------------------------------------------

def test_bitsearch_recovers_a_planted_toggle_bit_from_a_button_reference():
    start_bit = 20
    byte_order = "little_endian"
    n = 200
    dt = 0.05
    events = [1.0, 3.0, 5.5, 8.0]
    window = 0.3

    records = []
    for i in range(n):
        t = i * dt
        data = [0] * 8
        active = any(t0 <= t < t0 + window for t0 in events)
        if active:
            byte_idx, bit_idx = divmod(start_bit, 8)
            data[byte_idx] |= (1 << bit_idx)
        records.append({"arbitration_id": 0x321, "data": data, "timestamp": t})

    reference = reference_from_events(events, span=(0.0, (n - 1) * dt), window=window)
    candidates = bitsearch(records, reference, {"lengths": [1], "max_candidates": 5})
    assert candidates, "expected at least one candidate"
    best = candidates[0]
    assert best["arbitration_id"] == 0x321
    assert best["start_bit"] == start_bit
    assert best["length"] == 1
    assert best["byte_order"] == byte_order
    assert abs(best["correlation"]) > 0.9 or best["r2"] > 0.9


# --------------------------------------------------------------------------
# Router: /reverse/reference/*
# --------------------------------------------------------------------------

class _FakeProvider:
    def __init__(self, available: bool = True) -> None:
        self._available = available
        self._queue: "queue.Queue" = queue.Queue()
        self.sent: list[Frame] = []

    @property
    def available(self) -> bool:
        return self._available

    def push(self, frame: Frame) -> None:
        self._queue.put(frame)

    def recv(self, timeout: float = 0.5):
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def send(self, frame: Frame) -> bool:
        self.sent.append(frame)
        return True

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _clear_recorder():
    rec.clear()
    yield
    rec.clear()


def test_reference_start_rejects_bad_mode():
    client = TestClient(app)
    resp = client.post("/reverse/reference/start", json={"mode": "dial"})
    assert resp.status_code == 400


def test_reference_start_mark_status_stop_without_a_channel():
    client = TestClient(app)
    resp = client.post("/reverse/reference/start", json={"mode": "sweep"})
    assert resp.status_code == 200
    assert resp.json()["capturing"] is False

    assert client.post("/reverse/reference/mark", json={"value": 12.5}).status_code == 200
    status = client.get("/reverse/reference/status").json()
    assert status["recording"] is True
    assert status["mode"] == "sweep"
    assert status["count"] == 1

    stopped = client.post("/reverse/reference/stop").json()
    assert stopped["capture_id"] is None
    assert stopped["mode"] == "sweep"
    assert stopped["reference"] == [{"t": pytest.approx(stopped["reference"][0]["t"]), "value": 12.5, "available": True}]

    status = client.get("/reverse/reference/status").json()
    assert status["recording"] is False


def test_reference_start_with_channel_also_starts_and_saves_a_capture(monkeypatch):
    fake = _FakeProvider()
    monkeypatch.setattr(cap, "get_channel", lambda channel, backend="socketcan", **kw: fake)

    client = TestClient(app)
    resp = client.post("/reverse/reference/start",
                        json={"mode": "button", "channel": "vcan0", "capture_name": "ref-test"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["capturing"] is True

    fake.push(Frame(arbitration_id=0x10, data=[1]))
    client.post("/reverse/reference/event")

    import time
    time.sleep(0.1)

    stopped = client.post("/reverse/reference/stop").json()
    assert stopped["capture_id"]
    assert stopped["mode"] == "button"
    assert isinstance(stopped["reference"], list)

    got = cap.get_capture(stopped["capture_id"])
    assert got is not None
    assert got["name"] == "ref-test"
    assert got["channel"] == "vcan0"


def test_reference_clear():
    client = TestClient(app)
    client.post("/reverse/reference/start", json={"mode": "sweep"})
    client.post("/reverse/reference/mark", json={"value": 1.0})
    resp = client.post("/reverse/reference/clear")
    assert resp.status_code == 200
    status = client.get("/reverse/reference/status").json()
    assert status == {"recording": False, "mode": None, "count": 0}
