"""The Hyundai Elantra sample on the real opendbc CAN FD DBC + its CRC checksum."""
import random

import pytest

from app.can import checksum as ck
from app.can import dbc as dbc_mod
from app.db import CanDatabase, init_db, session_scope

skip_no_cantools = pytest.mark.skipif(not dbc_mod.available(), reason="cantools not installed")


def _ref_crc16_table(poly):
    table = []
    for i in range(256):
        crc = i << 8
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
        table.append(crc)
    return table


_LUT = _ref_crc16_table(0x1021)


def _ref_hkg(address, d):
    crc = 0
    for i in range(2, len(d)):
        crc = ((crc << 8) ^ _LUT[(crc >> 8) ^ d[i]]) & 0xFFFF
    crc = ((crc << 8) ^ _LUT[(crc >> 8) ^ (address & 0xFF)]) & 0xFFFF
    crc = ((crc << 8) ^ _LUT[(crc >> 8) ^ ((address >> 8) & 0xFF)]) & 0xFFFF
    xor = {8: 0x5F29, 16: 0x041D, 24: 0x819D, 32: 0x9F5B}.get(len(d), 0)
    return crc ^ xor


def test_hyundai_canfd_checksum_matches_opendbc_reference():
    for _ in range(1000):
        addr = random.choice([0xA0, 0xEA, 0x130, random.randrange(2048)])
        n = random.choice([8, 16, 24, 32])
        d = bytes(random.randrange(256) for _ in range(n))
        assert ck.hyundai_canfd_checksum(addr, d) == _ref_hkg(addr, d)


def test_hyundai_canfd_checksum_length_selects_xor_constant():
    d16 = bytes(16)
    d24 = bytes(24)
    # Same all-zero payload at different frame lengths must differ (the
    # length-keyed final XOR is the only thing distinguishing them here).
    assert ck.hyundai_canfd_checksum(0x1, d16) != ck.hyundai_canfd_checksum(0x1, d24)


@skip_no_cantools
def test_hyundai_loads_real_dbc_and_encodes_with_crc_checksum():
    from app.examples import hyundai_elantra
    from app.actions.registry import all_actions
    from app.can import simulation
    init_db()
    res = hyundai_elantra.load()
    assert res["ok"]
    with session_scope() as s:
        db = s.query(CanDatabase).filter_by(name=hyundai_elantra.DB_NAME).first()
        assert db is not None and db.license == "MIT"
        text = db.dbc_text
    # Real GEAR_SHIFTER encode/decode with a valid CAN FD CRC checksum (first
    # two bytes, little-endian), not a trailing byte.
    data = dbc_mod.encode(text, "GEAR_SHIFTER", {"GEAR": 4}, counter=7, checksum="hyundai_canfd")
    decoded = dbc_mod.decode(text, 0x130, bytes(data))
    assert decoded["GEAR"] == 4
    assert decoded["COUNTER"] == 7
    assert decoded["CHECKSUM"] == ck.hyundai_canfd_checksum(0x130, bytes(data))
    # The checksum is genuinely in the first two bytes, not the last.
    computed = ck.hyundai_canfd_checksum(0x130, bytes(data))
    assert data[0] == (computed & 0xFF)
    assert data[1] == (computed >> 8) & 0xFF
    for key in ("speed_60", "gear_d", "steer_left", "swc_res"):
        assert key in all_actions()
    names = {e["name"] for e in simulation.list_entries()}
    assert "Gear (GEAR_SHIFTER)" in names


@skip_no_cantools
def test_hyundai_wheel_speeds_real_signal_round_trip():
    from app.examples import hyundai_elantra
    text = hyundai_elantra._dbc_text()
    data = dbc_mod.encode(text, "WHEEL_SPEEDS", {"WHEEL_SPEED_1": 64.0}, checksum="hyundai_canfd")
    assert round(dbc_mod.decode(text, 0xA0, bytes(data))["WHEEL_SPEED_1"], 1) == 64.0


@skip_no_cantools
def test_hyundai_dbc_parses_and_message_comment_quirk_fixed():
    from app.examples import hyundai_elantra
    msgs = dbc_mod.parse_dbc(hyundai_elantra._dbc_text())
    assert any(m["name"] == "GEAR_SHIFTER" for m in msgs)
    assert any(m["name"] == "LKAS_ALT" for m in msgs)
