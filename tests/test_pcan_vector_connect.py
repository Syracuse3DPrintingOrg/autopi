"""PEAK/Vector providers explain why they will not connect."""
import sys

import pytest

from app.can.pcan import PcanProvider
from app.can.vector import VectorProvider
from app.can import selftest


class _RaisingBus:
    def __init__(self, *a, **k):
        raise OSError("pcanbasic library not found")


def _patch_bus(monkeypatch, exc="pcanbasic library not found"):
    import can
    def boom(**kwargs):
        raise OSError(exc)
    monkeypatch.setattr(can.interface, "Bus", boom)


def test_pcan_unavailable_sets_actionable_error(monkeypatch):
    pytest.importorskip("can")
    _patch_bus(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    p = PcanProvider("PCAN_USBBUS1")
    assert p.available is False
    assert "socketcan" in p.last_error.lower()
    assert "can0" in p.last_error
    # cached: does not keep retrying / stays failed
    assert p.available is False


def test_pcan_non_linux_error_mentions_pcan_basic(monkeypatch):
    pytest.importorskip("can")
    _patch_bus(monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")
    p = PcanProvider("PCAN_USBBUS1")
    assert p.available is False
    assert "PCAN-Basic" in p.last_error


def test_selftest_surfaces_provider_last_error(monkeypatch):
    pytest.importorskip("can")
    _patch_bus(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    p = PcanProvider("PCAN_USBBUS1")
    result = selftest.run_loopback_test(p)
    assert result["ok"] is False
    assert "socketcan" in result["error"].lower()


def test_vector_unavailable_sets_error(monkeypatch):
    pytest.importorskip("can")
    _patch_bus(monkeypatch, "vxlapi not found")
    v = VectorProvider("0")
    assert v.available is False
    assert "Vector" in v.last_error
