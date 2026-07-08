"""The Ford F-150 sample on the real opendbc Ford CAN-FD DBC (monitor-focused)."""
import pytest

from app.can import dbc as dbc_mod
from app.db import CanDatabase, init_db, session_scope

skip_no_cantools = pytest.mark.skipif(not dbc_mod.available(), reason="cantools not installed")


@skip_no_cantools
def test_ford_loads_and_decodes_real_signals():
    from app.examples import ford_f150
    from app.actions.registry import all_actions
    from app.can import simulation
    init_db()
    res = ford_f150.load()
    assert res["ok"]
    with session_scope() as s:
        db = s.query(CanDatabase).filter_by(name=ford_f150.DB_NAME).first()
        assert db is not None and db.license == "MIT"
        text = db.dbc_text
    # Real speed / gear / rpm round-trip through the actual DBC.
    assert round(dbc_mod.decode(text, 1045, bytes(dbc_mod.encode(text, "BrakeSysFeatures",
                 {"Veh_V_ActlBrk": 60.0})))["Veh_V_ActlBrk"], 1) == 60.0
    assert dbc_mod.decode(text, 560, bytes(dbc_mod.encode(text, "TransGearData",
           {"GearLvrPos_D_Actl": 3})))["GearLvrPos_D_Actl"] == 3
    for key in ("speed_60", "gear_d", "rpm_idle", "speed_up"):
        assert key in all_actions()
    assert any(e["name"] == "Speed (BrakeSysFeatures)" for e in simulation.list_entries())


@skip_no_cantools
def test_encode_fills_offset_signals_without_overflow():
    # Ford has offset signals; encoding one signal must not overflow the others.
    from app.examples import ford_f150
    text = ford_f150._dbc_text()
    data = dbc_mod.encode(text, "SteeringPinion_Data", {"StePinRelInit_An_Sns": 10.0})
    assert len(data) == 8
