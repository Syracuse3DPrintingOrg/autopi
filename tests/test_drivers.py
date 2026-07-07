from app.actions.drivers import DRIVERS, get_driver
from app.actions.drivers.can import _parse_frame
from app.actions.drivers.gpio import GpioDriver


def test_drivers_auto_discovered():
    # Every concrete driver module is picked up by name without hard-coding.
    for name in ("gpio", "shell", "http", "can"):
        assert name in DRIVERS
        assert get_driver(name) is not None


def test_gpio_simulates_when_unavailable(monkeypatch):
    driver = GpioDriver()
    monkeypatch.setattr(GpioDriver, "available", property(lambda self: False))
    res = driver.execute({"pin": 17, "mode": "on"})
    assert res.ok
    assert res.data["simulated"] is True
    assert res.data["state"] is True


def test_gpio_toggle_tracks_state_when_simulated(monkeypatch):
    driver = GpioDriver()
    monkeypatch.setattr(GpioDriver, "available", property(lambda self: False))
    first = driver.execute({"pin": 5, "mode": "toggle"})
    second = driver.execute({"pin": 5, "mode": "toggle"})
    assert first.data["state"] != second.data["state"]


def test_shell_runs_and_reports_output():
    res = get_driver("shell").execute({"command": "echo hi"})
    assert res.ok
    assert "hi" in res.message


def test_shell_missing_command_fails():
    res = get_driver("shell").execute({"command": ""})
    assert res.ok is False


def test_can_frame_parsing_is_pure():
    frame = _parse_frame({"channel": "can0", "arbitration_id": "0x7DF", "data": "02 01 0C"})
    assert frame["arbitration_id"] == 0x7DF
    assert frame["data"] == [0x02, 0x01, 0x0C]


def test_can_frame_parsing_rejects_bad_id():
    assert isinstance(_parse_frame({"arbitration_id": "nothex"}), str)


def test_can_driver_unavailable_without_hardware():
    # No can0/can1 SocketCAN interface on a dev machine, so the driver
    # reports itself unavailable and execute() falls back to simulating.
    assert get_driver("can").available is False


def test_can_execute_simulates_when_unavailable():
    res = get_driver("can").execute(
        {"channel": "can0", "arbitration_id": "0x7DF", "data": "02 01 0C"})
    assert res.ok
    assert res.data["simulated"] is True
    assert res.data["arbitration_id"] == 0x7DF


def test_can_execute_rejects_invalid_frame():
    # 9 data bytes is not a valid classic CAN length (max 8).
    res = get_driver("can").execute(
        {"channel": "can0", "arbitration_id": "0x123",
         "data": "01 02 03 04 05 06 07 08 09"})
    assert res.ok is False
