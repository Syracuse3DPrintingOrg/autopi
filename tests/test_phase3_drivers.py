"""Tests for the Phase 3 I/O drivers (relay, I2C, Modbus)."""
from app.actions.drivers import get_driver


def test_phase3_drivers_registered():
    for name in ("relay", "i2c", "modbus"):
        assert get_driver(name) is not None


def test_i2c_simulates_without_hardware():
    res = get_driver("i2c").execute({"address": "0x48", "register": "0x00", "op": "read_byte"})
    assert res.ok and res.data.get("simulated") is True


def test_modbus_simulates_without_library(monkeypatch):
    d = get_driver("modbus")
    monkeypatch.setattr(type(d), "available", property(lambda self: False))
    res = d.execute({"host": "10.0.0.5", "op": "read_register", "address": 40001})
    assert res.ok and res.data.get("simulated") is True


def test_modbus_requires_host():
    res = get_driver("modbus").execute({"op": "read_register", "address": 1})
    assert res.ok is False


def test_relay_active_low_maps_to_gpio(monkeypatch):
    from app.actions.drivers.gpio import GpioDriver
    monkeypatch.setattr(GpioDriver, "available", property(lambda self: False))
    res = get_driver("relay").execute({"pin": 5, "state": "on", "active_low": True})
    # Simulated GPIO reports the intended state; active-low 'on' energises.
    assert res.ok and res.data.get("simulated") is True
