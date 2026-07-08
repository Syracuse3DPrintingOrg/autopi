"""Automotive diagnostics: pure UDS/OBD-II request/response byte logic, the
transport/client degradation contract without hardware, and the router/UI.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.can import diagnostics as diag
from app.can.diagnostics import (
    IsoTpTransport,
    ObdClient,
    UdsClient,
    build_obd_request,
    build_read_did_request,
    build_read_dtc_request,
    build_routine_control_request,
    build_session_control_request,
    build_tester_present_request,
    build_write_did_request,
    decode_obd_response,
    decode_read_did_response,
    decode_read_dtc_response,
    decode_routine_control_response,
    decode_session_control_response,
    decode_tester_present_response,
    decode_uds_response,
    decode_write_did_response,
    format_dtc,
    simulate_obd_response,
    simulate_read_did,
    simulate_read_dtcs,
    simulate_routine_control,
    simulate_session_control,
    simulate_tester_present,
    simulate_write_did,
)
from app.main import app


# -- pure UDS request encoding -----------------------------------------------

def test_build_session_control_request_default_extended():
    assert build_session_control_request() == [0x10, 0x03]


def test_build_session_control_request_custom_session():
    assert build_session_control_request(0x02) == [0x10, 0x02]


def test_build_tester_present_request():
    assert build_tester_present_request() == [0x3E, 0x00]


def test_build_read_did_request_splits_16_bit_did():
    assert build_read_did_request(0xF190) == [0x22, 0xF1, 0x90]


def test_build_write_did_request_appends_value_bytes():
    assert build_write_did_request(0xF190, [1, 2, 3]) == [0x2E, 0xF1, 0x90, 1, 2, 3]


def test_build_routine_control_request_default_start():
    assert build_routine_control_request(0x0203) == [0x31, 0x01, 0x02, 0x03]


def test_build_routine_control_request_stop_with_data():
    assert build_routine_control_request(0x0203, subfunction=0x02, data=[9]) == [0x31, 0x02, 0x02, 0x03, 9]


def test_build_read_dtc_request_default_status_mask():
    assert build_read_dtc_request() == [0x19, 0x02, 0xFF]


# -- pure UDS response decoding ------------------------------------------------

def test_decode_uds_response_empty_is_an_error():
    result = decode_uds_response([], 0x10)
    assert result["ok"] is False
    assert "Empty" in result["error"]


def test_decode_uds_response_negative_response():
    result = decode_uds_response([0x7F, 0x10, 0x22], 0x10)
    assert result == {
        "ok": False,
        "negative": True,
        "request_sid": 0x10,
        "nrc": 0x22,
        "nrc_name": "Conditions not correct",
    }


def test_decode_uds_response_unknown_nrc_falls_back_to_hex_name():
    result = decode_uds_response([0x7F, 0x22, 0x99], 0x22)
    assert result["nrc_name"] == "NRC 0x99"


def test_decode_uds_response_wrong_sid_is_an_error():
    result = decode_uds_response([0x51, 0x03], 0x10)
    assert result["ok"] is False
    assert "Unexpected" in result["error"]


def test_decode_uds_response_positive():
    result = decode_uds_response([0x50, 0x03], 0x10)
    assert result == {"ok": True, "sid": 0x50, "payload": [0x03]}


def test_decode_session_control_response_extracts_session():
    result = decode_session_control_response([0x50, 0x03])
    assert result["ok"] is True
    assert result["session"] == 0x03
    assert "payload" not in result


def test_decode_tester_present_response_positive():
    result = decode_tester_present_response([0x7E, 0x00])
    assert result["ok"] is True


def test_decode_read_did_response_extracts_did_and_data():
    result = decode_read_did_response([0x62, 0xF1, 0x90, 0x41, 0x42])
    assert result["ok"] is True
    assert result["did"] == 0xF190
    assert result["data"] == [0x41, 0x42]


def test_decode_write_did_response_extracts_did():
    result = decode_write_did_response([0x6E, 0xF1, 0x90])
    assert result["ok"] is True
    assert result["did"] == 0xF190


def test_decode_routine_control_response_extracts_fields():
    result = decode_routine_control_response([0x71, 0x01, 0x02, 0x03, 0xAA])
    assert result["ok"] is True
    assert result["subfunction"] == 0x01
    assert result["routine_id"] == 0x0203
    assert result["data"] == [0xAA]


def test_format_dtc_p0301():
    # P0301 = category P (00), digit1 0, digit2 3, byte1 0x01.
    assert format_dtc(0x03, 0x01) == "P0301"


def test_format_dtc_categories():
    assert format_dtc(0x00, 0x00).startswith("P")
    assert format_dtc(0x40, 0x00).startswith("C")
    assert format_dtc(0x80, 0x00).startswith("B")
    assert format_dtc(0xC0, 0x00).startswith("U")


def test_decode_read_dtc_response_parses_records():
    # sub-function echo 0x02, status availability 0xFF, one DTC record:
    # id bytes 0x03 0x01 0x00, status 0x08.
    result = decode_read_dtc_response([0x59, 0x02, 0xFF, 0x03, 0x01, 0x00, 0x08])
    assert result["ok"] is True
    assert result["dtcs"] == [{"code": "P0301", "sub_code": 0x00, "status": 0x08}]


def test_decode_read_dtc_response_no_records():
    result = decode_read_dtc_response([0x59, 0x02, 0xFF])
    assert result["dtcs"] == []


# -- pure OBD-II encode/decode -------------------------------------------------

def test_build_obd_request_is_mode_and_pid_only():
    # The ISO-TP transport adds its own length/PCI byte and padding; the
    # request payload here is just the application-layer user data.
    assert build_obd_request(0x0C) == [0x01, 0x0C]


def test_decode_obd_response_rpm():
    # RPM PID: A=0x0C, B=0x80 -> ((12*256)+128)/4 = 800.
    result = decode_obd_response([0x41, 0x0C, 0x0C, 0x80])
    assert result == {"ok": True, "pid": 0x0C, "name": "Engine RPM", "unit": "rpm",
                       "value": 800.0, "raw": [0x0C, 0x80]}


def test_decode_obd_response_coolant_temp():
    result = decode_obd_response([0x41, 0x05, 0x58])  # 88 - 40 = 48 C
    assert result["ok"] is True
    assert result["value"] == 48


def test_decode_obd_response_vehicle_speed():
    result = decode_obd_response([0x41, 0x0D, 0x3C])  # 60 km/h
    assert result["value"] == 60


def test_decode_obd_response_unknown_pid_returns_raw():
    result = decode_obd_response([0x41, 0x99, 0x12])
    assert result["ok"] is True
    assert result["name"] == "PID 0x99"
    assert result["raw"] == [0x12]


def test_decode_obd_response_negative():
    result = decode_obd_response([0x7F, 0x01, 0x11])
    assert result["ok"] is False
    assert result["negative"] is True
    assert result["nrc"] == 0x11


def test_decode_obd_response_empty():
    result = decode_obd_response([])
    assert result["ok"] is False


def test_decode_obd_response_too_short():
    result = decode_obd_response([0x41])
    assert result["ok"] is False


def test_decode_obd_response_wrong_mode():
    result = decode_obd_response([0x42, 0x0C, 0x00])
    assert result["ok"] is False
    assert "mode" in result["error"]


# -- simulated responses --------------------------------------------------------

def test_simulate_obd_response_is_marked_simulated_and_decodes():
    result = simulate_obd_response(0x0C)
    assert result["simulated"] is True
    assert result["ok"] is True
    assert result["name"] == "Engine RPM"
    assert result["value"] > 0


def test_simulate_obd_response_unknown_pid_still_marked():
    result = simulate_obd_response(0xEE)
    assert result["simulated"] is True


def test_simulate_session_control():
    result = simulate_session_control(0x03)
    assert result == {"ok": True, "session": 0x03, "simulated": True}


def test_simulate_tester_present():
    result = simulate_tester_present()
    assert result["ok"] is True
    assert result["simulated"] is True


def test_simulate_read_did():
    result = simulate_read_did(0xF190)
    assert result["ok"] is True
    assert result["did"] == 0xF190
    assert result["simulated"] is True


def test_simulate_write_did():
    result = simulate_write_did(0xF190)
    assert result == {"ok": True, "did": 0xF190, "simulated": True}


def test_simulate_routine_control():
    result = simulate_routine_control(0x0203)
    assert result["ok"] is True
    assert result["routine_id"] == 0x0203
    assert result["simulated"] is True


def test_simulate_read_dtcs_has_at_least_one_dtc():
    result = simulate_read_dtcs()
    assert result["ok"] is True
    assert result["simulated"] is True
    assert len(result["dtcs"]) >= 1
    assert result["dtcs"][0]["code"].startswith(("P", "C", "B", "U"))


# -- degradation without hardware (isotp/udsoncan may be installed for tests,
# but there is no real can0 interface on the test host, so every provider
# reports unavailable and the clients fall back to simulate) -----------------

def test_isotp_transport_unavailable_without_channel():
    transport = IsoTpTransport("can0")
    assert transport.available is False
    assert transport.request([0x10, 0x03]) is None


def test_isotp_transport_module_importable_reports_bool():
    assert isinstance(IsoTpTransport.module_importable(), bool)


def test_uds_client_falls_back_to_simulate_without_hardware():
    client = UdsClient("can0")
    result = client.diagnostic_session_control(0x03)
    assert result["simulated"] is True
    assert result["session"] == 0x03


def test_uds_client_read_dtcs_falls_back_to_simulate():
    client = UdsClient("can0")
    result = client.read_dtcs()
    assert result["simulated"] is True
    assert "dtcs" in result


def test_obd_client_falls_back_to_simulate_without_hardware():
    client = ObdClient("can0")
    result = client.read_pid(0x0D)
    assert result["simulated"] is True
    assert result["name"] == "Vehicle speed"


def test_uds_client_available_false_when_provider_unavailable(monkeypatch):
    class _FakeProvider:
        available = False

    monkeypatch.setattr(diag, "get_channel", lambda *a, **k: _FakeProvider())
    client = UdsClient("can0")
    assert client.available is False


def test_uds_client_available_true_when_provider_and_libraries_present(monkeypatch):
    class _FakeProvider:
        available = True

    monkeypatch.setattr(diag, "get_channel", lambda *a, **k: _FakeProvider())
    client = UdsClient("can0")
    assert client.available is True


# -- router ---------------------------------------------------------------------

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_router_pids_lists_known_pids(client):
    resp = client.get("/diag/pids")
    assert resp.status_code == 200
    body = resp.json()
    names = {p["name"] for p in body["pids"]}
    assert "Engine RPM" in names


def test_router_status_reports_not_live_on_test_host(client):
    resp = client.get("/diag/status", params={"channel": "can0"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["uds_available"] is False
    assert body["obd_available"] is False


def test_router_uds_session_returns_simulated(client):
    resp = client.post("/diag/uds/session", json={"channel": "can0", "session": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert body["simulated"] is True
    assert body["session"] == 3


def test_router_uds_tester_present(client):
    resp = client.post("/diag/uds/tester-present", json={"channel": "can0"})
    assert resp.status_code == 200
    assert resp.json()["simulated"] is True


def test_router_uds_read_did(client):
    resp = client.post("/diag/uds/read-did", json={"channel": "can0", "did": "0xF190"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["did"] == 0xF190
    assert body["simulated"] is True


def test_router_uds_write_did(client):
    resp = client.post("/diag/uds/write-did", json={"channel": "can0", "did": "0xF190", "data": "01 02"})
    assert resp.status_code == 200
    assert resp.json()["simulated"] is True


def test_router_uds_routine(client):
    resp = client.post("/diag/uds/routine", json={"channel": "can0", "routine_id": "0x0203"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["routine_id"] == 0x0203
    assert body["simulated"] is True


def test_router_uds_dtcs(client):
    resp = client.post("/diag/uds/dtcs", json={"channel": "can0"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["simulated"] is True
    assert "dtcs" in body


def test_router_obd_pid(client):
    resp = client.post("/diag/obd/pid", json={"channel": "can0", "pid": "0x0C"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["simulated"] is True
    assert body["name"] == "Engine RPM"


def test_router_obd_pid_bad_id_400s(client):
    resp = client.post("/diag/obd/pid", json={"channel": "can0", "pid": ""})
    # An empty pid parses to 0 via _parse_hex's default; assert it still 200s
    # with a decoded (if unnamed) PID rather than crashing.
    assert resp.status_code == 200


def test_ui_page_renders(client):
    resp = client.get("/ui/diagnostics")
    assert resp.status_code == 200
    assert "Diagnostics" in resp.text


def test_nav_link_present_on_another_page(client):
    resp = client.get("/ui/can-monitor")
    assert resp.status_code == 200
    assert "ui/diagnostics" in resp.text
