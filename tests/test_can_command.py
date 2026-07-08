"""Vehicle command (CAN) driver: pure frame building, simulated execute, and
the DB-backed lookup of a message's arbitration id."""
from __future__ import annotations

import pytest

from app.actions.drivers import DRIVERS, get_driver
from app.actions.drivers.can_command import CanCommandDriver, build_command_frame
from app.can import dbc
from app.db import CanDatabase, CanMessage, init_db, session_scope

# A tiny valid DBC: one message with two signals (mirrors tests/test_dbc.py).
SAMPLE_DBC = """VERSION ""

BU_: ECU RADIO

BO_ 512 VolumeControl: 8 RADIO
 SG_ VOLUME_UP : 0|8@1+ (1,0) [0|255] "" ECU
 SG_ VOLUME_DOWN : 8|8@1+ (1,0) [0|255] "" ECU
"""

cantools_missing = not dbc.available()
skip_no_cantools = pytest.mark.skipif(cantools_missing, reason="cantools not installed")


def test_driver_auto_discovered():
    assert "can_command" in DRIVERS
    assert get_driver("can_command") is not None
    assert get_driver("can_command").label == "Vehicle command (CAN)"


def test_driver_unavailable_without_hardware():
    assert get_driver("can_command").available is False


# -- raw mode (no database), pure ---------------------------------------------

def test_build_frame_raw_mode():
    built = build_command_frame({
        "channel": "can0", "arbitration_id": "0x3D1", "data": "01 00",
    })
    assert built["channel"] == "can0"
    assert built["frame"]["arbitration_id"] == 0x3D1
    assert built["frame"]["data"] == [0x01, 0x00]


def test_build_frame_raw_mode_missing_id_is_an_error():
    result = build_command_frame({"channel": "can0"})
    assert isinstance(result, str)


def test_build_frame_raw_mode_bad_data_is_an_error():
    result = build_command_frame({"arbitration_id": "0x100", "data": "zz"})
    assert isinstance(result, str)


# -- database mode, pure given dbc_text ---------------------------------------

@skip_no_cantools
def test_build_frame_database_mode_encodes_and_uses_resolved_id():
    built = build_command_frame(
        {"message": "VolumeControl", "signals": {"VOLUME_UP": 1, "VOLUME_DOWN": 0}},
        dbc_text=SAMPLE_DBC, resolved_arbitration_id=512,
    )
    assert built["frame"]["arbitration_id"] == 512
    assert built["frame"]["data"][0] == 1


@skip_no_cantools
def test_build_frame_database_mode_explicit_id_overrides_resolved():
    built = build_command_frame(
        {"message": "VolumeControl", "signals": {"VOLUME_UP": 1, "VOLUME_DOWN": 0},
         "arbitration_id": "0x999"},
        dbc_text=SAMPLE_DBC, resolved_arbitration_id=512,
    )
    assert built["frame"]["arbitration_id"] == 0x999


@skip_no_cantools
def test_build_frame_database_mode_without_resolved_id_is_an_error():
    result = build_command_frame(
        {"message": "VolumeControl", "signals": {"VOLUME_UP": 1, "VOLUME_DOWN": 0}},
        dbc_text=SAMPLE_DBC, resolved_arbitration_id=None,
    )
    assert isinstance(result, str)


@skip_no_cantools
def test_build_frame_database_mode_unknown_signal_is_an_error():
    result = build_command_frame(
        {"message": "VolumeControl", "signals": {"NOT_A_SIGNAL": 1}},
        dbc_text=SAMPLE_DBC, resolved_arbitration_id=512,
    )
    assert isinstance(result, str)


# -- execute(): simulated send, no hardware -----------------------------------

def test_execute_simulates_raw_frame_when_unavailable():
    driver = CanCommandDriver()
    res = driver.execute({"channel": "can0", "arbitration_id": "0x3D1", "data": "01"})
    assert res.ok
    assert res.data["simulated"] is True
    assert res.data["arbitration_id"] == 0x3D1


def test_execute_rejects_invalid_frame():
    res = get_driver("can_command").execute(
        {"arbitration_id": "0x123", "data": "01 02 03 04 05 06 07 08 09"})
    assert res.ok is False


def test_execute_with_no_database_and_no_message_or_id_fails_cleanly():
    res = get_driver("can_command").execute({"channel": "can0"})
    assert res.ok is False


@skip_no_cantools
def test_execute_resolves_database_message_and_simulates_send():
    init_db()
    with session_scope() as s:
        database = dbc.import_dbc(s, name="radio", dbc_text=SAMPLE_DBC, source="upload")
        s.flush()
        db_id = database.id

    driver = CanCommandDriver()
    res = driver.execute({
        "database_id": db_id, "message": "VolumeControl",
        "signals": {"VOLUME_UP": 1, "VOLUME_DOWN": 0},
    })
    assert res.ok, res.message
    assert res.data["simulated"] is True
    assert res.data["arbitration_id"] == 512
    assert res.data["data"][0] == 1


def test_execute_unknown_database_id_fails_cleanly():
    init_db()
    driver = CanCommandDriver()
    res = driver.execute({"database_id": 999999, "message": "Whatever", "signals": {}})
    assert res.ok is False
