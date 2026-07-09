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
