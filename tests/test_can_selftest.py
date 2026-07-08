"""Loopback self-test logic (app.can.selftest), driven against an injected
fake provider so it needs no hardware, no python-can, and no bridge."""
from __future__ import annotations

from app.can.base import Frame
from app.can.selftest import build_test_frame, frames_match, run_loopback_test


class _FakeProvider:
    def __init__(self, available=True, send_ok=True, echo=True):
        self.available = available
        self._send_ok = send_ok
        self._echo = echo
        self._last_sent = None

    def send(self, frame):
        self._last_sent = frame
        return self._send_ok

    def recv(self, timeout=None):
        if self._echo and self._last_sent is not None:
            return self._last_sent
        return None


def test_build_test_frame_is_a_fixed_recognizable_frame():
    frame = build_test_frame()
    assert frame.arbitration_id == 0x7A5
    assert frame.data == [0xDE, 0xAD, 0xBE, 0xEF]
    assert frame.is_fd is False


def test_frames_match_true_for_identical_frames():
    a = Frame(arbitration_id=0x100, data=[1, 2])
    b = Frame(arbitration_id=0x100, data=[1, 2])
    assert frames_match(a, b) is True


def test_frames_match_false_when_received_is_none():
    a = Frame(arbitration_id=0x100, data=[1, 2])
    assert frames_match(a, None) is False


def test_frames_match_false_on_different_id():
    a = Frame(arbitration_id=0x100, data=[1, 2])
    b = Frame(arbitration_id=0x101, data=[1, 2])
    assert frames_match(a, b) is False


def test_run_loopback_test_unavailable_provider():
    result = run_loopback_test(_FakeProvider(available=False))
    assert result["ok"] is False
    assert result["passed"] is False


def test_run_loopback_test_send_failure():
    result = run_loopback_test(_FakeProvider(send_ok=False))
    assert result["ok"] is False
    assert result["passed"] is False


def test_run_loopback_test_passes_when_frame_echoes_back():
    result = run_loopback_test(_FakeProvider())
    assert result["ok"] is True
    assert result["passed"] is True


def test_run_loopback_test_fails_when_nothing_comes_back():
    result = run_loopback_test(_FakeProvider(echo=False))
    assert result["ok"] is True
    assert result["passed"] is False
