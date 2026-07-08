"""The Honda Civic sample on the real opendbc Bosch DBC + its nibble checksum."""
import random

import pytest

from app.can import checksum as ck
from app.can import dbc as dbc_mod
from app.db import CanDatabase, init_db, session_scope

skip_no_cantools = pytest.mark.skipif(not dbc_mod.available(), reason="cantools not installed")


def _ref_honda(address, d):
    s = 0
    extended = address > 0x7FF
    addr = address
    while addr:
        s += addr & 0xF
        addr >>= 4
    for i in range(len(d)):
        x = d[i]
        if i == len(d) - 1:
            x >>= 4
        s += (x & 0xF) + (x >> 4)
    s = 8 - s
    if extended:
        s += 3
    return s & 0xF


def test_honda_checksum_matches_opendbc_reference():
    for _ in range(1000):
        addr = random.choice([0x309, 0x158, 0x191, 0x296, random.randrange(2048), random.randrange(2048, 0x4000)])
        d = bytes(random.randrange(256) for _ in range(random.choice([3, 4, 5, 7, 8])))
        assert ck.honda_checksum(addr, d) == _ref_honda(addr, d)


def test_honda_checksum_extended_id_adds_offset():
    d = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x00])
    # Same data, standard vs extended id must differ (the +3 extended offset).
    assert ck.honda_checksum(0x100, d) != ck.honda_checksum(0x100 | 0x80000000, d)


@skip_no_cantools
def test_honda_loads_real_dbc_and_encodes_with_nibble_checksum():
    from app.examples import honda_civic
    from app.actions.registry import all_actions
    from app.can import simulation
    init_db()
    res = honda_civic.load()
    assert res["ok"]
    with session_scope() as s:
        db = s.query(CanDatabase).filter_by(name=honda_civic.DB_NAME).first()
        assert db is not None and db.license == "MIT"
        text = db.dbc_text
    # Real CAR_SPEED encode/decode with a valid Honda counter + nibble checksum.
    data = dbc_mod.encode(text, "CAR_SPEED", {"CAR_SPEED": 55.0}, counter=2, checksum="honda")
    decoded = dbc_mod.decode(text, 0x309, bytes(data))
    assert round(decoded["CAR_SPEED"], 1) == 55.0
    assert decoded["COUNTER"] == 2
    assert decoded["CHECKSUM"] == ck.honda_checksum(0x309, bytes(data))
    for key in ("speed_60", "gear_d", "rpm_idle", "swc_res_plus"):
        assert key in all_actions()
    names = {e["name"] for e in simulation.list_entries()}
    assert "Speed (CAR_SPEED)" in names


@skip_no_cantools
def test_honda_checksum_does_not_clobber_neighboring_bits():
    # The checksum is a 4-bit nibble sharing byte 7 with a 2-bit COUNTER;
    # writing it must not corrupt the counter bits (unlike a whole-byte splice).
    from app.examples import honda_civic
    text = honda_civic._dbc_text()
    data = dbc_mod.encode(text, "CAR_SPEED", {"CAR_SPEED": 10.0}, counter=3, checksum="honda")
    decoded = dbc_mod.decode(text, 0x309, bytes(data))
    assert decoded["COUNTER"] == 3


@skip_no_cantools
def test_honda_dbc_extended_id_quirk_parses():
    from app.examples import honda_civic
    msgs = dbc_mod.parse_dbc(honda_civic._dbc_text())
    assert any(m["name"] == "LKAS_HUD_A" for m in msgs)
    assert any(m["name"] == "LKAS_HUD_2" for m in msgs)
