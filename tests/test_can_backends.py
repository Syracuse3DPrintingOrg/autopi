"""Multi-hardware CAN backend support: registry selection, provider
degradation for pcan/vector, the virtual loopback bus, and interface-config
persistence. No real hardware needed for any of it.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.can import get_channel, list_backends, reset_channels
from app.can.doip import DoipProvider
from app.can.lin import LinProvider
from app.can.pcan import PcanProvider
from app.can.registry import PROVIDER_CLASSES, create_provider
from app.can.socketcan import SocketCanProvider
from app.can.vector import VectorProvider
from app.can.virtual import VirtualProvider
from app.services import can_interfaces


@pytest.fixture(autouse=True)
def _clear_channel_cache():
    reset_channels()
    yield
    reset_channels()


# -- registry: backend selection ---------------------------------------------

def test_create_provider_selects_pcan():
    provider = create_provider("pcan", "PCAN_USBBUS1")
    assert isinstance(provider, PcanProvider)


def test_create_provider_selects_vector():
    provider = create_provider("vector", "0")
    assert isinstance(provider, VectorProvider)


def test_create_provider_selects_virtual():
    provider = create_provider("virtual", "virtual0")
    assert isinstance(provider, VirtualProvider)


def test_create_provider_selects_socketcan_explicitly():
    provider = create_provider("socketcan", "can0")
    assert isinstance(provider, SocketCanProvider)


def test_get_channel_defaults_to_socketcan():
    provider = get_channel("can0")
    assert isinstance(provider, SocketCanProvider)


def test_get_channel_selects_backend_and_caches_per_backend_and_channel():
    a = get_channel("0", backend="vector")
    b = get_channel("0", backend="vector")
    c = get_channel("0", backend="socketcan")
    assert a is b
    assert isinstance(a, VectorProvider)
    assert a is not c
    assert isinstance(c, SocketCanProvider)


def test_list_backends_reports_the_four_configurable_backends():
    names = {b["backend"] for b in list_backends()}
    assert names == {"socketcan", "pcan", "vector", "virtual"}


def test_lin_and_doip_are_registered_but_not_configurable():
    # Registered so create_provider/get_channel resolve them (the extension
    # point is real), but left out of the UI-facing configurable list since
    # they always report unavailable.
    assert PROVIDER_CLASSES["lin"] is LinProvider
    assert PROVIDER_CLASSES["doip"] is DoipProvider
    names = {b["backend"] for b in list_backends()}
    assert "lin" not in names
    assert "doip" not in names


# -- pcan / vector: unavailable without hardware or python-can ---------------

def test_pcan_provider_unavailable_without_python_can():
    provider = PcanProvider(channel="PCAN_USBBUS1")
    # python-can is not installed in the test environment, so this must
    # degrade rather than raise.
    assert provider.open() is False
    assert provider.available is False


def test_pcan_provider_send_recv_are_safe_no_ops_when_unavailable():
    provider = PcanProvider(channel="PCAN_USBBUS1")
    from app.can import Frame

    assert provider.send(Frame(arbitration_id=0x100, data=[1])) is False
    assert provider.recv(timeout=0.01) is None
    provider.set_filters([{"can_id": 0x100, "can_mask": 0x7FF}])  # must not raise
    provider.close()  # must not raise, even unopened
    provider.close()  # idempotent


def test_vector_provider_unavailable_without_python_can():
    provider = VectorProvider(channel="0")
    assert provider.open() is False
    assert provider.available is False


def test_vector_provider_channel_index_parses_numeric_string():
    provider = VectorProvider(channel="2")
    assert provider._channel_index() == 2


def test_vector_provider_channel_index_passes_through_non_numeric():
    provider = VectorProvider(channel="my-channel")
    assert provider._channel_index() == "my-channel"


def test_vector_provider_send_recv_are_safe_no_ops_when_unavailable():
    provider = VectorProvider(channel="0")
    from app.can import Frame

    assert provider.send(Frame(arbitration_id=0x100, data=[1])) is False
    assert provider.recv(timeout=0.01) is None
    provider.set_filters([])  # must not raise


# -- LIN / DoIP stubs: always unavailable, never raise -----------------------

def test_lin_provider_is_always_unavailable():
    provider = LinProvider()
    assert provider.available is False
    assert provider.open() is False
    from app.can import Frame

    assert provider.send(Frame(arbitration_id=0x100)) is False
    assert provider.recv() is None
    provider.set_filters([])
    provider.close()


def test_doip_provider_is_always_unavailable():
    provider = DoipProvider()
    assert provider.available is False
    assert provider.open() is False
    from app.can import Frame

    assert provider.send(Frame(arbitration_id=0x100)) is False
    assert provider.recv() is None
    provider.set_filters([])
    provider.close()


# -- virtual provider: unavailable without python-can, loopback when it's there

def test_virtual_provider_unavailable_when_python_can_is_not_importable(monkeypatch):
    provider = VirtualProvider(channel="test-loop")
    monkeypatch.setattr(VirtualProvider, "_module_importable", staticmethod(lambda: False))
    assert provider.available is False
    assert provider.open() is False


def test_virtual_provider_available_depends_only_on_python_can_being_importable():
    # Unlike socketcan/pcan/vector, virtual needs no external driver or
    # hardware, so availability tracks the module import alone.
    provider = VirtualProvider(channel="test-loop")
    assert provider.available is provider._module_importable()


def test_virtual_provider_loopback_send_recv_when_python_can_present():
    pytest.importorskip("can")
    from app.can import Frame

    tx = VirtualProvider(channel="test-loop-1")
    rx = VirtualProvider(channel="test-loop-1")
    try:
        assert tx.open() is True
        assert rx.open() is True
        assert tx.available is True
        frame = Frame(arbitration_id=0x123, data=[1, 2, 3])
        assert tx.send(frame) is True
        received = rx.recv(timeout=1.0)
        assert received is not None
        assert received.arbitration_id == 0x123
        assert received.data == [1, 2, 3]
    finally:
        tx.close()
        rx.close()


# -- interface config persistence (services/can_interfaces.py) --------------

def test_save_and_list_interface():
    can_interfaces.save_interface({
        "id": "can0", "backend": "socketcan", "channel": "can0", "bitrate": 500000,
    })
    entries = can_interfaces.list_interfaces()
    assert len(entries) == 1
    assert entries[0]["id"] == "can0"
    assert entries[0]["backend"] == "socketcan"


def test_save_interface_upserts_by_id():
    can_interfaces.save_interface({"id": "can0", "backend": "socketcan", "bitrate": 500000})
    can_interfaces.save_interface({"id": "can0", "backend": "virtual", "bitrate": 250000})
    entries = can_interfaces.list_interfaces()
    assert len(entries) == 1
    assert entries[0]["backend"] == "virtual"
    assert entries[0]["bitrate"] == 250000


def test_save_interface_requires_id():
    with pytest.raises(ValueError):
        can_interfaces.save_interface({"backend": "socketcan"})


def test_save_interface_defaults_channel_to_id_and_normalizes_types():
    entry = can_interfaces.save_interface({"id": "can1", "bitrate": "250000", "fd": "yes"})
    assert entry["channel"] == "can1"
    assert entry["bitrate"] == 250000
    assert entry["fd"] is True
    assert entry["data_bitrate"] is None


def test_get_interface_returns_none_when_missing():
    assert can_interfaces.get_interface("nope") is None


def test_delete_interface_removes_entry_and_reports_found():
    can_interfaces.save_interface({"id": "can0", "backend": "socketcan"})
    assert can_interfaces.delete_interface("can0") is True
    assert can_interfaces.list_interfaces() == []
    assert can_interfaces.delete_interface("can0") is False


def test_interfaces_persist_across_fresh_reads():
    can_interfaces.save_interface({"id": "can0", "backend": "pcan", "channel": "PCAN_USBBUS1"})
    can_interfaces.save_interface({"id": "can1", "backend": "vector", "channel": "0"})
    ids = {i["id"] for i in can_interfaces.list_interfaces()}
    assert ids == {"can0", "can1"}


# -- router: /can/interfaces/* config CRUD -----------------------------------

@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_router_lists_backends(client):
    resp = client.get("/can/interfaces/backends")
    assert resp.status_code == 200
    names = {b["backend"] for b in resp.json()["backends"]}
    assert names == {"socketcan", "pcan", "vector", "virtual"}


def test_router_create_list_delete_interface(client):
    resp = client.post("/can/interfaces/config", json={
        "id": "can0", "backend": "virtual", "channel": "virtual0", "bitrate": 500000,
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True

    listed = client.get("/can/interfaces/config").json()
    assert any(i["id"] == "can0" for i in listed["interfaces"])

    deleted = client.delete("/can/interfaces/config/can0")
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True

    missing = client.delete("/can/interfaces/config/can0")
    assert missing.status_code == 404


def test_router_rejects_blank_id(client):
    resp = client.post("/can/interfaces/config", json={"id": "   "})
    assert resp.status_code == 400


def test_router_status_for_unconfigured_interface_is_404(client):
    resp = client.get("/can/interfaces/config/nope/status")
    assert resp.status_code == 404


def test_router_status_reports_unavailable_without_hardware(client):
    client.post("/can/interfaces/config", json={
        "id": "can0", "backend": "socketcan", "channel": "can0",
    })
    resp = client.get("/can/interfaces/config/can0/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "can0" and body["available"] is False
    # SocketCAN explains a missing interface (the usual "not detected" case) so
    # the page can tell the user to enable the CAN HAT and reboot.
    assert body["error"] and "can0" in body["error"]
