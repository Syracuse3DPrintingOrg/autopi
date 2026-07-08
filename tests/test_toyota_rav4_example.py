"""The Toyota RAV4 sample on the real opendbc dsu-less DBC + its checksum."""
import random

import pytest

from app.can import checksum as ck
from app.can import dbc as dbc_mod
from app.db import CanDatabase, init_db, session_scope

skip_no_cantools = pytest.mark.skipif(not dbc_mod.available(), reason="cantools not installed")


def _ref_toyota(address, d):
    s = len(d)
    addr = address
    while addr:
        s += addr & 0xFF
        addr >>= 8
    for i in range(len(d) - 1):
        s += d[i]
    return s & 0xFF


def test_toyota_checksum_matches_opendbc_reference():
    for _ in range(1000):
        addr = random.choice([0x2E4, 0xB4, 0x1D2, 0xAA, random.randrange(2048)])
        d = bytes(random.randrange(256) for _ in range(random.choice([5, 6, 7, 8])))
        assert ck.toyota_checksum(addr, d) == _ref_toyota(addr, d)


@skip_no_cantools
def test_toyota_loads_real_dbc_and_encodes_with_checksum():
    from app.examples import toyota_rav4
    from app.actions.registry import all_actions
    from app.can import simulation
    init_db()
    res = toyota_rav4.load()
    assert res["ok"]
    with session_scope() as s:
        db = s.query(CanDatabase).filter_by(name=toyota_rav4.DB_NAME).first()
        assert db is not None and db.license == "MIT"
        text = db.dbc_text
    # Real SPEED encode/decode with a valid Toyota checksum in the last byte.
    data = dbc_mod.encode(text, "SPEED", {"SPEED": 42.0}, checksum="toyota")
    assert data[-1] == ck.toyota_checksum(0xB4, bytes(data))
    assert round(dbc_mod.decode(text, 180, bytes(data))["SPEED"], 1) == 42.0
    for key in ("speed_60", "gear_d", "rpm_idle", "cruise_on", "lka_request_on"):
        assert key in all_actions()
    names = {e["name"] for e in simulation.list_entries()}
    assert "Speed (SPEED)" in names


@skip_no_cantools
def test_toyota_dbc_parses_and_real_gear_encodes():
    from app.examples import toyota_rav4
    msgs = dbc_mod.parse_dbc(toyota_rav4._dbc_text())
    assert any(m["name"] == "GEAR_PACKET" for m in msgs)
    text = toyota_rav4._dbc_text()
    # Real GEAR_PACKET.GEAR encoding: Park = 32.
    data = dbc_mod.encode(text, "GEAR_PACKET", {"GEAR": 32})
    assert dbc_mod.decode(text, 956, bytes(data))["GEAR"] == 32


@skip_no_cantools
def test_toyota_steering_lka_counter_and_checksum():
    from app.examples import toyota_rav4
    text = toyota_rav4._dbc_text()
    data = dbc_mod.encode(text, "STEERING_LKA", {"STEER_REQUEST": 1, "STEER_TORQUE_CMD": 100},
                          counter=5, checksum="toyota")
    decoded = dbc_mod.decode(text, 0x2E4, bytes(data))
    assert decoded["COUNTER"] == 5
    assert decoded["STEER_REQUEST"] == 1
    assert data[-1] == ck.toyota_checksum(0x2E4, bytes(data))
