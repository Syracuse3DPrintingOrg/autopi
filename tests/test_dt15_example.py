"""Tests for the DT15 case study, profile bundles, and the sim_set driver."""
import pytest

from app.actions.drivers import get_driver
from app.can import dbc as dbc_mod
from app.db import init_db

cantools_missing = not dbc_mod.available()
skip_no_cantools = pytest.mark.skipif(cantools_missing, reason="cantools not installed")


@skip_no_cantools
def test_dt15_loads_profile_actions_sim_and_bundle():
    from app.examples import dt15
    from app.services import profiles as profiles_svc
    from app.can import simulation
    from app.actions.registry import all_actions
    from app.services import profile_bundle
    init_db()
    res = dt15.load()
    assert res["ok"]
    prof = next(p for p in profiles_svc.list_profiles() if p["name"] == "DT15")
    assert prof["vin"] == "1C6RRFFG9SN513894"
    assert prof["make"] == "Stellantis" and prof["model"] == "RAM DT" and prof["year"] == 2025
    assert profiles_svc.get_active_profile_id() == prof["id"]
    acts = all_actions()
    for key in ("media_playpause", "swc_volup", "gear_d", "ign_run", "speed_up"):
        assert key in acts
    names = {e["name"] for e in simulation.list_entries()}
    assert {"Speed", "Gear", "Ignition"} <= names
    assert profile_bundle.has_bundle(prof["id"])


@skip_no_cantools
def test_dt15_is_idempotent():
    from app.examples import dt15
    from app.services import profiles as profiles_svc
    init_db()
    dt15.load()
    dt15.load()
    dt15_profiles = [p for p in profiles_svc.list_profiles() if p["name"] == "DT15"]
    assert len(dt15_profiles) == 1


def test_sim_set_updates_a_simulation_entry():
    from app.can import simulation
    simulation.create_entry({"name": "Gear", "arbitration_id": "0x101",
                             "signals": {"Gear": 0}, "period_ms": 100, "enabled": True})
    res = get_driver("sim_set").execute({"entry": "Gear", "signals": {"Gear": 3}})
    assert res.ok
    entry = next(e for e in simulation.list_entries() if e["name"] == "Gear")
    assert entry["signals"]["Gear"] == 3


def test_sim_set_add_mode_with_clamp():
    from app.can import simulation
    simulation.create_entry({"name": "Speed", "arbitration_id": "0x100",
                             "signals": {"Speed": 8}, "period_ms": 100, "enabled": True})
    d = get_driver("sim_set")
    d.execute({"entry": "Speed", "signals": {"Speed": 5}, "mode": "add", "min": 0, "max": 10})
    entry = next(e for e in simulation.list_entries() if e["name"] == "Speed")
    assert entry["signals"]["Speed"] == 10  # 8 + 5, clamped to 10


def test_sim_set_missing_entry_fails():
    res = get_driver("sim_set").execute({"entry": "nope", "signals": {"x": 1}})
    assert res.ok is False


@skip_no_cantools
def test_profile_bundle_capture_and_apply_roundtrip():
    from app.examples import dt15
    from app.services import profiles as profiles_svc, profile_bundle
    from app.actions.registry import save_user_actions
    from app.can import simulation
    init_db()
    dt15.load()
    prof = next(p for p in profiles_svc.list_profiles() if p["name"] == "DT15")
    # Wipe the live setup, then recall it from the bundle.
    save_user_actions([])
    for e in list(simulation.list_entries()):
        simulation.delete_entry(e["id"])
    out = profile_bundle.apply(prof["id"])
    assert out["ok"]
    from app.actions.registry import all_actions
    assert "gear_d" in all_actions()
    assert any(e["name"] == "Gear" for e in simulation.list_entries())
