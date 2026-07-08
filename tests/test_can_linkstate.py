"""Pure parsing tests for `ip -details -json link show` output and the bus
health classification built on it. No hardware, root, or bridge needed."""
from __future__ import annotations

from app.can.linkstate import classify_health, parse_link_show

_UP_ACTIVE = [{
    "ifname": "can0",
    "flags": ["UP", "LOWER_UP"],
    "linkinfo": {
        "info_kind": "can",
        "info_data": {
            "state": "ERROR-ACTIVE",
            "restart_ms": 0,
            "bittiming": {"bitrate": 500000},
            "berr_counter": {"tx": 0, "rx": 0},
        },
    },
}]

_UP_WARNING = [{
    "ifname": "can0",
    "flags": ["UP", "LOWER_UP"],
    "linkinfo": {"info_data": {
        "state": "ERROR-WARNING",
        "bittiming": {"bitrate": 500000},
        "berr_counter": {"tx": 12, "rx": 3},
    }},
}]

_BUS_OFF = [{
    "ifname": "can0",
    "flags": ["UP", "LOWER_UP"],
    "linkinfo": {"info_data": {
        "state": "BUS-OFF",
        "bittiming": {"bitrate": 500000},
        "berr_counter": {"tx": 255, "rx": 128},
    }},
}]

_DOWN = [{
    "ifname": "can0",
    "flags": ["NO-CARRIER"],
    "linkinfo": {"info_data": {"state": "STOPPED", "bittiming": {"bitrate": 500000}}},
}]

_FD = [{
    "ifname": "can1",
    "flags": ["UP", "LOWER_UP"],
    "linkinfo": {"info_data": {
        "state": "ERROR-ACTIVE",
        "bittiming": {"bitrate": 500000},
        "data_bittiming": {"bitrate": 2000000},
        "berr_counter": {"tx": 0, "rx": 0},
    }},
}]


def test_parse_link_show_unwraps_the_ip_json_list():
    parsed = parse_link_show(_UP_ACTIVE)
    assert parsed["name"] == "can0"
    assert parsed["up"] is True
    assert parsed["state"] == "ERROR-ACTIVE"
    assert parsed["bitrate"] == 500000
    assert parsed["rx_errors"] == 0
    assert parsed["tx_errors"] == 0


def test_parse_link_show_accepts_bare_dict():
    parsed = parse_link_show(_UP_ACTIVE[0])
    assert parsed["name"] == "can0"


def test_parse_link_show_reads_fd_data_bitrate():
    parsed = parse_link_show(_FD)
    assert parsed["data_bitrate"] == 2000000


def test_parse_link_show_empty_input_is_empty_dict():
    assert parse_link_show([]) == {}
    assert parse_link_show(None) == {}
    assert parse_link_show("garbage") == {}


def test_parse_link_show_down_interface():
    parsed = parse_link_show(_DOWN)
    assert parsed["up"] is False


def test_classify_health_ok_when_error_active():
    h = classify_health(parse_link_show(_UP_ACTIVE))
    assert h["status"] == "ok"


def test_classify_health_warning_on_error_counters():
    h = classify_health(parse_link_show(_UP_WARNING))
    assert h["status"] == "warning"
    assert "rx=3" in h["message"]


def test_classify_health_error_on_bus_off():
    h = classify_health(parse_link_show(_BUS_OFF))
    assert h["status"] == "error"
    assert "off" in h["message"].lower()


def test_classify_health_down_when_link_is_down():
    h = classify_health(parse_link_show(_DOWN))
    assert h["status"] == "down"


def test_classify_health_unknown_for_empty_link():
    assert classify_health({})["status"] == "unknown"
