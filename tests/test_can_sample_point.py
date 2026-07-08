"""Sample-point config + the CAN error-counter parse for the live error meter."""
from app.can.linkstate import parse_can_stats
from app.services import can_interfaces


IP_S_D = """4: can1: <NOARP,UP,LOWER_UP,ECHO> mtu 72 qdisc pfifo_fast state UP mode DEFAULT group default qlen 10
    link/can  promiscuity 0 allmulti 0 minmtu 72 maxmtu 72
    can state ERROR-ACTIVE (berr-counter tx 0 rx 0) restart-ms 1000
          bitrate 500000 sample-point 0.875
          dbitrate 2000000 dsample-point 0.750
          clock 40000000
          re-started bus-errors arbit-lost error-warn error-pass bus-off
          0          0          0          590        1126       0         numtxqueues 1
"""


def test_parse_can_stats_reads_error_counters():
    c = parse_can_stats(IP_S_D)
    assert c["error_warn"] == 590 and c["error_pass"] == 1126
    assert c["bus_off"] == 0 and c["restarts"] == 0


def test_parse_can_stats_empty_when_absent():
    assert parse_can_stats("no counters here") == {}
    assert parse_can_stats("") == {}


def test_sample_point_normalized_and_persisted():
    can_interfaces.save_interface({
        "id": "can1", "backend": "socketcan", "channel": "can1",
        "bitrate": 500000, "data_bitrate": 2000000, "fd": True,
        "sample_point": 0.8, "data_sample_point": 0.8,
    })
    got = can_interfaces.get_interface("can1")
    assert got["sample_point"] == 0.8 and got["data_sample_point"] == 0.8


def test_sample_point_out_of_range_dropped():
    can_interfaces.save_interface({
        "id": "canx", "backend": "socketcan", "channel": "canx",
        "sample_point": 1.5, "data_sample_point": "abc",
    })
    got = can_interfaces.get_interface("canx")
    assert got["sample_point"] is None and got["data_sample_point"] is None
