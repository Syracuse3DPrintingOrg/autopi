"""The live-capture path explains an empty result instead of a bare "nothing":
link_stats reads the interface's sysfs state, and _explain_empty_capture turns a
before/after snapshot into a bench-readable reason (idle port vs a port whose
kernel rx moved but the socket read nothing). Pure/offline.
"""
from __future__ import annotations

from app.can import registry
from app.routers.reverse import _explain_empty_capture


def _write_link(root, name, *, mtu=16, rx=0, operstate="up"):
    d = root / name
    d.mkdir()
    (d / "mtu").write_text(f"{mtu}\n")
    (d / "operstate").write_text(f"{operstate}\n")
    stats = d / "statistics"
    stats.mkdir()
    (stats / "rx_packets").write_text(f"{rx}\n")


def test_link_stats_reads_sysfs(tmp_path):
    _write_link(tmp_path, "can0", mtu=72, rx=1234, operstate="up")
    s = registry.link_stats("can0", sysfs_root=str(tmp_path))
    assert s == {"present": True, "operstate": "up", "mtu": 72, "fd": True, "rx_packets": 1234}


def test_link_stats_absent_interface(tmp_path):
    assert registry.link_stats("can9", sysfs_root=str(tmp_path)) == {}


def test_explain_absent():
    assert "not present" in _explain_empty_capture("can1", {}, {})


def test_explain_down():
    after = {"present": True, "operstate": "down", "mtu": 16, "fd": False, "rx_packets": 0}
    assert "not up" in _explain_empty_capture("can1", {"rx_packets": 0}, after)


def test_explain_idle_port_points_at_other_channel():
    before = {"rx_packets": 100}
    after = {"present": True, "operstate": "up", "mtu": 16, "fd": False, "rx_packets": 100}
    msg = _explain_empty_capture("can0", before, after)
    assert "idle" in msg and "other" in msg.lower()


def test_explain_fd_mode_mismatch():
    before = {"rx_packets": 100}
    after = {"present": True, "operstate": "up", "mtu": 72, "fd": True, "rx_packets": 5100}
    msg = _explain_empty_capture("can1", before, after)
    assert "CAN-FD" in msg and "+5000" in msg


def test_explain_rx_climbed_classic():
    before = {"rx_packets": 0}
    after = {"present": True, "operstate": "up", "mtu": 16, "fd": False, "rx_packets": 50}
    msg = _explain_empty_capture("can1", before, after)
    assert "+50" in msg and "socket/mode" in msg
