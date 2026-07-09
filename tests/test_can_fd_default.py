"""When the app has no saved config for a channel, opening it should still use
CAN-FD mode if the live link is up in FD (MTU 72), so a capture on a bus brought
up outside the app is not a silent classic socket. Pure sysfs-read logic.
"""
from __future__ import annotations

from app.can import registry


def _write_link(root, name, mtu):
    d = root / name
    d.mkdir()
    (d / "mtu").write_text(f"{mtu}\n")


def test_link_is_fd_reads_mtu(tmp_path):
    _write_link(tmp_path, "can0", 72)   # CAN-FD
    _write_link(tmp_path, "can1", 16)   # classic
    assert registry._link_is_fd("can0", sysfs_root=str(tmp_path)) is True
    assert registry._link_is_fd("can1", sysfs_root=str(tmp_path)) is False
    assert registry._link_is_fd("can9", sysfs_root=str(tmp_path)) is False  # missing


def test_configured_settings_defaults_fd_from_live_link(monkeypatch):
    # No saved interface config, but the live link reports FD.
    monkeypatch.setattr(registry, "_link_is_fd", lambda ch, **kw: True)
    from app.services import can_interfaces
    monkeypatch.setattr(can_interfaces, "list_interfaces", lambda: [])
    assert registry._configured_settings("can1", "socketcan") == {"fd": True}


def test_configured_settings_live_fd_overrides_saved_classic(monkeypatch):
    # The interface is saved with fd disabled, but the live link is up in FD.
    # A classic socket would receive nothing, so FD must win.
    monkeypatch.setattr(registry, "_link_is_fd", lambda ch, **kw: True)
    from app.services import can_interfaces
    monkeypatch.setattr(can_interfaces, "list_interfaces", lambda: [
        {"channel": "can0", "backend": "socketcan", "fd": False, "bitrate": 500000},
    ])
    settings = registry._configured_settings("can0", "socketcan")
    assert settings["fd"] is True
    assert settings["bitrate"] == 500000


def test_configured_settings_no_fd_when_link_classic(monkeypatch):
    monkeypatch.setattr(registry, "_link_is_fd", lambda ch, **kw: False)
    from app.services import can_interfaces
    monkeypatch.setattr(can_interfaces, "list_interfaces", lambda: [])
    assert registry._configured_settings("can1", "socketcan") == {}


def test_configured_settings_fd_fallback_socketcan_only(monkeypatch):
    monkeypatch.setattr(registry, "_link_is_fd", lambda ch, **kw: True)
    from app.services import can_interfaces
    monkeypatch.setattr(can_interfaces, "list_interfaces", lambda: [])
    # A non-socketcan backend has no sysfs link to read; no fd default.
    assert registry._configured_settings("PCAN_USBBUS1", "pcan") == {}
