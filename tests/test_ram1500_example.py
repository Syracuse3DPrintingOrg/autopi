"""The RAM 1500 sample is built on the real opendbc CUSW DBC."""
import pytest

from app.can import dbc as dbc_mod
from app.db import CanDatabase, init_db, session_scope

skip_no_cantools = pytest.mark.skipif(not dbc_mod.available(), reason="cantools not installed")


@skip_no_cantools
def test_ram1500_loads_real_dbc_and_encodes_real_messages():
    from app.examples import ram1500
    from app.actions.registry import all_actions
    init_db()
    res = ram1500.load()
    assert res["ok"]
    with session_scope() as s:
        db = s.query(CanDatabase).filter_by(name=ram1500.DB_NAME).first()
        assert db is not None and db.license == "MIT"
        db_id, dbc_text = db.id, db.dbc_text
    # Real GEAR.PRNDL encoding: Drive = 4 -> byte 1 = 0x04 (from the actual DBC).
    data = dbc_mod.encode(dbc_text, "GEAR", {"PRNDL": 4})
    assert data[1] == 0x04
    assert dbc_mod.decode(dbc_text, 1262, bytes(data))["PRNDL"] == 4
    # Real steering-wheel + gear + speed keys exist.
    acts = all_actions()
    for key in ("swc_resume", "swc_cruise_onoff", "gear_d", "turn_left", "speed_60"):
        assert key in acts


@skip_no_cantools
def test_ram1500_encode_fills_unset_signals():
    # CRUISE_BUTTONS has many signals; setting one must still encode (others 0).
    from app.examples import ram1500
    text = ram1500._dbc_text()
    data = dbc_mod.encode(text, "CRUISE_BUTTONS", {"ACC_Resume": 1})
    # ACC_Resume is bit 4 of byte 0 -> 0x10.
    assert data[0] == 0x10


def test_tolerant_parse_of_extended_id_quirk():
    # The vendored DBC has a >11-bit id flagged extended; it must still load.
    from app.examples import ram1500
    if not dbc_mod.available():
        pytest.skip("cantools not installed")
    msgs = dbc_mod.parse_dbc(ram1500._dbc_text())
    assert any(m["name"] == "GEAR" for m in msgs)
