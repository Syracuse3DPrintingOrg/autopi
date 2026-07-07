from app.services import bridge


def test_decode_throttled_none_is_empty():
    d = bridge.decode_throttled(None)
    assert d == {"flags": {}, "warnings": []}


def test_decode_throttled_under_voltage_now():
    d = bridge.decode_throttled(0x1)
    assert d["flags"]["under_voltage_now"] is True
    assert any("Under-voltage" in w for w in d["warnings"])


def test_decode_throttled_sticky_since_boot():
    # 0x50000 = throttled-since-boot (0x40000) + under-voltage-since-boot (0x10000)
    d = bridge.decode_throttled(0x50000)
    assert d["flags"]["under_voltage_since_boot"] is True
    assert d["flags"]["throttled_since_boot"] is True
    assert d["flags"]["under_voltage_now"] is False


def test_health_summary_flags_hot_and_full():
    out = bridge.health_summary({"throttled": 0, "temp_c": 84.0, "disk_percent": 95.0})
    assert out["temp_c"] == 84.0
    assert any("temperature is high" in w for w in out["warnings"])
    assert any("Disk is 95" in w for w in out["warnings"])


def test_health_summary_clean_when_cool():
    out = bridge.health_summary({"throttled": 0, "temp_c": 45.0, "disk_percent": 30.0})
    assert out["warnings"] == []


def test_is_raspberry_pi_false_off_hardware():
    # This test host is not a Pi.
    assert bridge.is_raspberry_pi() is False
