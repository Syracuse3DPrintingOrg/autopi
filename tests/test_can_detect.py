"""Detecting the CAN interfaces present on the device (pure, fake /sys tree)."""
import os

import pytest
from starlette.testclient import TestClient

from app.can.detect import list_can_interfaces


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def _make_iface(root, name, type_val, driver=None, operstate="down"):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "type"), "w") as f:
        f.write(f"{type_val}\n")
    with open(os.path.join(d, "operstate"), "w") as f:
        f.write(f"{operstate}\n")
    if driver:
        drv = os.path.join(root, "_drivers", driver)
        os.makedirs(drv, exist_ok=True)
        os.makedirs(os.path.join(d, "device"), exist_ok=True)
        os.symlink(drv, os.path.join(d, "device", "driver"))


def test_lists_can_interfaces_with_driver_and_state(tmp_path):
    root = str(tmp_path)
    _make_iface(root, "eth0", 1, driver="cdc_ether")               # not CAN
    _make_iface(root, "can0", 280, driver="peak_usb", operstate="up")
    _make_iface(root, "can1", 280, driver="mcp251xfd", operstate="up")
    _make_iface(root, "can2", 280, driver="mcp251xfd", operstate="down")
    ifaces = list_can_interfaces(sysfs_root=root)
    names = [i["name"] for i in ifaces]
    assert names == ["can0", "can1", "can2"]  # eth0 excluded, sorted
    by = {i["name"]: i for i in ifaces}
    assert "PEAK" in by["can0"]["description"] and by["can0"]["up"] is True
    assert "MCP2518FD" in by["can1"]["description"]
    assert by["can2"]["up"] is False


def test_vcan_flagged_virtual(tmp_path):
    root = str(tmp_path)
    _make_iface(root, "vcan0", 280, driver="vcan")
    out = list_can_interfaces(sysfs_root=root)
    assert out and out[0]["is_virtual"] is True


def test_missing_tree_returns_empty():
    assert list_can_interfaces(sysfs_root="/no/such/path") == []


def test_router_detected_endpoint(client):
    r = client.get("/can/interfaces/detected")
    assert r.status_code == 200
    assert "interfaces" in r.json()
