"""The Alfa Romeo Giulia sample on the real opendbc Giorgio DBC + its J1850 checksum."""
import random

import pytest

from app.can import checksum as ck
from app.can import dbc as dbc_mod
from app.db import CanDatabase, init_db, session_scope

skip_no_cantools = pytest.mark.skipif(not dbc_mod.available(), reason="cantools not installed")


def _ref_lut(poly):
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = ((c << 1) ^ poly) & 0xFF if c & 0x80 else (c << 1) & 0xFF
        t.append(c)
    return t


def _ref_giorgio(address, d):
    lut = _ref_lut(0x1D)
    crc = 0
    for i in range(len(d) - 1):
        crc ^= d[i]; crc = lut[crc]
    return crc ^ {0xDE: 0x10, 0x106: 0xF6, 0x122: 0xF1}.get(address, 0x0A)


def test_fca_giorgio_checksum_matches_opendbc_reference():
    for _ in range(500):
        addr = random.choice([0xDE, 0x106, 0x122, 0xEE, 0xFC, random.randrange(2048)])
        d = bytes(random.randrange(256) for _ in range(random.choice([6, 7, 8])))
        assert ck.fca_giorgio_checksum(addr, d) == _ref_giorgio(addr, d)


def test_giorgio_special_address_xor():
    # The three special addresses are the EPS messages.
    d = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x00])
    assert ck.fca_giorgio_checksum(0xDE, d) != ck.fca_giorgio_checksum(0x99, d)


@skip_no_cantools
def test_giorgio_loads_real_dbc_and_encodes_with_checksum():
    from app.examples import giorgio
    from app.actions.registry import all_actions
    from app.can import simulation
    init_db()
    res = giorgio.load()
    assert res["ok"]
    with session_scope() as s:
        db = s.query(CanDatabase).filter_by(name=giorgio.DB_NAME).first()
        assert db is not None and db.license == "MIT"
        text = db.dbc_text
    # Real ABS_1 wheel-speed encode/decode with a valid J1850 checksum.
    data = dbc_mod.encode(text, "ABS_1", {"WHEEL_SPEED_FL": 16.0}, counter=5, checksum="fca_giorgio")
    assert data[-1] == ck.fca_giorgio_checksum(0xEE, bytes(data))
    assert round(dbc_mod.decode(text, 238, bytes(data))["WHEEL_SPEED_FL"], 1) == 16.0
    for key in ("speed_60", "rpm_idle", "steer_left", "hud_60"):
        assert key in all_actions()
    names = {e["name"] for e in simulation.list_entries()}
    assert "Wheel speeds (ABS_1)" in names


@skip_no_cantools
def test_giorgio_dbc_extended_id_quirk_parses():
    from app.examples import giorgio
    msgs = dbc_mod.parse_dbc(giorgio._dbc_text())
    assert any(m["name"] == "ABS_1" for m in msgs)
