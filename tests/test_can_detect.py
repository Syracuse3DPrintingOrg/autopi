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


def _make_iface(root, name, type_val, driver=None, operstate="down",
                spi=None, rx=0, tx=0):
    d = os.path.join(root, name)
    os.makedirs(os.path.join(d, "statistics"), exist_ok=True)
    for f, v in (("type", type_val), ("operstate", operstate)):
        with open(os.path.join(d, f), "w") as fh:
            fh.write(f"{v}\n")
    for f, v in (("rx_packets", rx), ("tx_packets", tx), ("rx_errors", 0), ("rx_over_errors", 0)):
        with open(os.path.join(d, "statistics", f), "w") as fh:
            fh.write(f"{v}\n")
    if driver:
        devpath = os.path.join(root, "_dev", spi or name)
        os.makedirs(devpath, exist_ok=True)
        drv = os.path.join(root, "_drivers", driver)
        os.makedirs(drv, exist_ok=True)
        os.symlink(drv, os.path.join(devpath, "driver"))
        os.symlink(devpath, os.path.join(d, "device"))


def test_lists_can_interfaces_with_driver_and_state(tmp_path):
    root = str(tmp_path)
    _make_iface(root, "eth0", 1, driver="cdc_ether")
    _make_iface(root, "can0", 280, driver="peak_usb", operstate="up", rx=500, tx=2)
    _make_iface(root, "can1", 280, driver="mcp251xfd", operstate="up", spi="spi0.0", rx=1423, tx=10)
    _make_iface(root, "can2", 280, driver="mcp251xfd", operstate="up", spi="spi1.0", rx=0, tx=0)
    ifaces = list_can_interfaces(sysfs_root=root)
    by = {i["name"]: i for i in ifaces}
    assert list(by) == ["can0", "can1", "can2"]  # eth0 excluded
    assert "PEAK" in by["can0"]["description"]
    # The two HAT channels map to the board silkscreen ports by SPI order.
    assert by["can1"]["port_label"] == "CAN0" and by["can1"]["spi_device"] == "spi0.0"
    assert by["can2"]["port_label"] == "CAN1" and by["can2"]["spi_device"] == "spi1.0"
    assert "board port CAN0" in by["can1"]["description"]
    # Stats let you see which bus is actually carrying traffic.
    assert by["can1"]["stats"]["rx_packets"] == 1423
    assert by["can2"]["stats"]["rx_packets"] == 0
    assert by["can0"]["port_label"] is None  # USB adapter is not a HAT port


def test_missing_tree_returns_empty():
    assert list_can_interfaces(sysfs_root="/no/such/path") == []


def test_router_detected_endpoint(client):
    r = client.get("/can/interfaces/detected")
    assert r.status_code == 200
    assert "interfaces" in r.json()


def test_sniff_reports_no_frames_when_unavailable(client):
    client.post("/can/interfaces/config", json={
        "id": "can9", "backend": "socketcan", "channel": "can9",
    })
    r = client.post("/can/interfaces/config/can9/sniff")
    assert r.status_code == 200
    # No such interface on the test host, so it reports not available, not a crash.
    assert r.json()["ok"] is False
