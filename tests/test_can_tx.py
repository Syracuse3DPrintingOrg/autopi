"""Periodic CAN transmit toggle: start/stop, no real bus needed."""
from __future__ import annotations

import time

from app.services import can_tx


def test_toggle_starts_and_stops(monkeypatch):
    from app import can as can_pkg
    sent = []

    class _Fake:
        def send(self, frame):
            sent.append(frame)
            return True

    monkeypatch.setattr(can_pkg, "get_channel", lambda ch, **kw: _Fake())
    try:
        assert can_tx.is_running("can0", 0x100) is False
        assert can_tx.toggle("can0", 0x100, [1, 2], period_ms=10) is True   # now on
        assert can_tx.is_running("can0", 0x100) is True
        time.sleep(0.05)
        assert len(sent) >= 1                                                # it is sending
        assert can_tx.toggle("can0", 0x100, [1, 2], period_ms=10) is False  # now off
        assert can_tx.is_running("can0", 0x100) is False
    finally:
        can_tx.stop_all()


def test_start_is_idempotent(monkeypatch):
    from app import can as can_pkg
    monkeypatch.setattr(can_pkg, "get_channel", lambda ch, **kw: type("F", (), {"send": lambda self, f: True})())
    try:
        assert can_tx.start("can1", 0x200, [0], period_ms=50) is True
        assert can_tx.start("can1", 0x200, [0], period_ms=50) is False   # already running
        assert can_tx.stop("can1", 0x200) is True
    finally:
        can_tx.stop_all()


def test_burst_sends_multiple_then_stops(monkeypatch):
    from app import can as can_pkg
    sent = []

    class _Fake:
        available = True
        def send(self, frame):
            sent.append(frame)
            return True

    monkeypatch.setattr(can_pkg, "get_channel", lambda ch, **kw: _Fake())
    n = can_tx.burst("can0", 0x100, [1, 2], period_ms=10, duration_ms=60)
    assert n >= 3                    # ~6 sends in 60ms at 10ms; several, bounded
    assert len(sent) == n
    assert can_tx.is_running("can0", 0x100) is False  # burst does not linger in the registry


def test_burst_unavailable_channel_sends_nothing(monkeypatch):
    from app import can as can_pkg

    class _Down:
        available = False
        def send(self, frame):
            raise AssertionError("must not send on an unavailable channel")

    monkeypatch.setattr(can_pkg, "get_channel", lambda ch, **kw: _Down())
    assert can_tx.burst("can0", 0x100, [1], period_ms=10, duration_ms=50) == 0


def test_fuzz_randomizes_selected_bytes_and_holds_others(monkeypatch):
    import random as _random
    from app import can as can_pkg
    sent = []

    class _Fake:
        available = True
        def send(self, frame):
            sent.append(list(frame.data))
            return True

    monkeypatch.setattr(can_pkg, "get_channel", lambda ch, **kw: _Fake())
    frames = can_tx.fuzz("can0", 0x100, [0xAA, 0xBB, 0xCC], [0, 2],
                         count=20, period_ms=2, rng=_random.Random(42))
    assert len(frames) == 20 and len(sent) == 20
    # Byte 1 was NOT in the fuzz set, so it is held at the template value.
    assert all(row[1] == 0xBB for row in sent)
    # Bytes 0 and 2 were fuzzed, so they take more than one value across frames.
    assert len({row[0] for row in sent}) > 1
    assert len({row[2] for row in sent}) > 1


def test_fuzz_unavailable_channel_sends_nothing(monkeypatch):
    from app import can as can_pkg
    class _Down:
        available = False
        def send(self, frame):
            raise AssertionError("must not send")
    monkeypatch.setattr(can_pkg, "get_channel", lambda ch, **kw: _Down())
    assert can_tx.fuzz("can0", 0x100, [0], [0], count=10) == []


def test_replay_sends_frames_in_order(monkeypatch):
    from app import can as can_pkg
    sent = []
    class _Fake:
        available = True
        def send(self, frame):
            sent.append(frame.arbitration_id)
            return True
    monkeypatch.setattr(can_pkg, "get_channel", lambda ch, **kw: _Fake())
    frames = [
        {"arbitration_id": 0x30, "data": [1], "timestamp": 0.20},
        {"arbitration_id": 0x10, "data": [2], "timestamp": 0.00},
        {"arbitration_id": 0x20, "data": [3], "timestamp": 0.05},
    ]
    n = can_tx.replay("can0", frames, speed=100.0)  # fast so the test is quick
    assert n == 3
    assert sent == [0x10, 0x20, 0x30]  # replayed in timestamp order


def test_replay_unavailable_channel_sends_nothing(monkeypatch):
    from app import can as can_pkg
    class _Down:
        available = False
        def send(self, frame):
            raise AssertionError("must not send")
    monkeypatch.setattr(can_pkg, "get_channel", lambda ch, **kw: _Down())
    assert can_tx.replay("can0", [{"arbitration_id": 1, "data": [0], "timestamp": 0.0}]) == 0
