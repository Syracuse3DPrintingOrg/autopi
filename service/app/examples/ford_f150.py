"""Ford F-150 (2024) live sample, on the real opendbc Ford DBC.

Uses the real `ford_lincoln_base_pt.dbc` from comma.ai's opendbc (MIT), the
modern Ford CAN-FD powertrain database that covers the F-150 (2021+), Mustang
Mach-E, Explorer, Bronco Sport, Escape, Maverick, and more. Monitoring is fully
real: connect over the Waveshare HAT, open the Monitor page, and the actual
vehicle speed, gear, engine RPM, wheel speeds, and steering angle decode from the
bus.

Sending caveat: Ford protects most messages with a per-message rolling counter
and checksum (the signals suffixed `_No_Cnt` and `_No_Cs`). Unlike the Chrysler
and Giorgio samples, Ford's checksum is computed per message and is not a single
shared algorithm, so this sample is built for reading. The cluster simulation
below broadcasts the real messages and they decode correctly on a monitor, but a
real cluster that validates the checksum may ignore them until the per-message
checksum is wired in. If you have FORScan definitions or captures for a specific
truck, import them on the CAN page to extend this. This DBC does not include
proprietary infotainment/radio messages.
"""
from __future__ import annotations

import os

from ..actions.registry import ActionSpec, upsert_action
from ..can import dbc as dbc_mod
from ..can import simulation
from ..db import CanDatabase, session_scope
from ..services import layout as layout_svc
from ..services import profiles as profiles_svc

NAME = "Ford F-150 (2024) — real opendbc Ford CAN-FD"
DESCRIPTION = ("A live Ford F-150 sample on the real ford_lincoln_base_pt.dbc (opendbc, MIT, "
               "covers F-150/Mach-E/Explorer/Bronco/Maverick): monitor real speed, gear, engine "
               "RPM, wheel speeds, and steering angle, with a speed/gear/RPM cluster simulation. "
               "Reading is fully real; Ford's per-message checksums mean sends are read-focused.")

CHANNEL = "can0"
DB_NAME = "Ford CAN-FD base (F-150/Mach-E/Explorer, opendbc MIT)"
_DBC_PATH = os.path.join(os.path.dirname(__file__), "data", "ford_lincoln_base_pt.dbc")

BRAKE = 0x415    # 1045 BrakeSysFeatures (Veh_V_ActlBrk, kph)
GEAR = 0x230     # 560 TransGearData (GearLvrPos_D_Actl)
ENGINE = 0x42F   # 1071 Engine_Clutch_Data (EngAout_N_Dsply, rpm)


def _dbc_text() -> str:
    with open(_DBC_PATH, encoding="utf-8") as f:
        return f.read()


def is_loaded() -> bool:
    try:
        with session_scope() as s:
            return s.query(CanDatabase).filter_by(name=DB_NAME).first() is not None
    except Exception:
        return False


def _sel(aid, label, entry, signals, icon, color, category, mode="set", **extra):
    params = {"entry": entry, "signals": signals, "mode": mode}
    params.update(extra)
    upsert_action(ActionSpec(id=aid, label=label, driver="sim_set", icon=icon, color=color,
                             category=category, params=params))


def load() -> dict:
    text = _dbc_text()
    with session_scope() as s:
        existing = s.query(CanDatabase).filter_by(name=DB_NAME).first()
        if existing is not None:
            db_id = existing.id
            existing.dbc_text = text
        else:
            d = dbc_mod.import_dbc(s, name=DB_NAME, dbc_text=text, source="opendbc",
                                   license="MIT", make="Ford", model="F-150", year=2024)
            s.flush()
            db_id = d.id

    prof = next((p for p in profiles_svc.list_profiles() if p.get("name") == "F150"), None)
    if prof is None:
        prof = profiles_svc.create_profile(
            name="F150", year=2024, make="Ford", model="F-150", vin="",
            config={"platform": "Ford CAN-FD", "can_interfaces": ["can0", "can1"],
                    "can_database_ids": [db_id],
                    "notes": "Real opendbc Ford. Set your VIN. Monitor decodes real signals."})
    profiles_svc.set_active_profile(prof["id"])

    _seed_sim(db_id)
    _seed_actions()
    _seed_layout()

    from ..services import profile_bundle
    profile_bundle.capture(prof["id"])
    return {"ok": True, "profile_id": prof["id"], "database_id": db_id,
            "message": "Ford F-150 loaded (real opendbc DBC). Open Monitor to decode a real bus. "
                       "Sends are read-focused (Ford per-message checksums)."}


def _seed_sim(db_id: int) -> None:
    wanted = {
        "Speed (BrakeSysFeatures)": {"arbitration_id": hex(BRAKE), "message": "BrakeSysFeatures",
                                     "signals": {"Veh_V_ActlBrk": 0}, "period_ms": 50},
        "Gear (TransGearData)": {"arbitration_id": hex(GEAR), "message": "TransGearData",
                                 "signals": {"GearLvrPos_D_Actl": 0}, "period_ms": 100},
        "Engine (Engine_Clutch_Data)": {"arbitration_id": hex(ENGINE), "message": "Engine_Clutch_Data",
                                        "signals": {"EngAout_N_Dsply": 800}, "period_ms": 100},
    }
    existing = {e.get("name"): e for e in simulation.list_entries()}
    for name, spec in wanted.items():
        entry = {"name": name, "channel": CHANNEL, "backend": "socketcan",
                 "database_id": db_id, "is_fd": True, "enabled": True, **spec}
        if name in existing:
            simulation.update_entry(existing[name]["id"], entry)
        else:
            simulation.create_entry(entry)


def _seed_actions() -> None:
    # Vehicle speed (Veh_V_ActlBrk is kph directly).
    for kph in (0, 30, 60, 100):
        _sel(f"speed_{kph}", f"Speed {kph}", "Speed (BrakeSysFeatures)", {"Veh_V_ActlBrk": kph},
             "bi-speedometer2", "#0e7490", "Speed")
    _sel("speed_up", "Speed +5", "Speed (BrakeSysFeatures)", {"Veh_V_ActlBrk": 5},
         "bi-plus-lg", "#0e7490", "Speed", mode="add", min=0, max=200)
    _sel("speed_down", "Speed -5", "Speed (BrakeSysFeatures)", {"Veh_V_ActlBrk": -5},
         "bi-dash-lg", "#0e7490", "Speed", mode="add", min=0, max=200)
    # Gear (GearLvrPos_D_Actl: 0 Park, 1 Reverse, 2 Neutral, 3 Drive).
    for aid, label, val, icon in [("gear_p", "P", 0, "bi-p-circle"), ("gear_r", "R", 1, "bi-arrow-counterclockwise"),
                                  ("gear_n", "N", 2, "bi-n-circle"), ("gear_d", "D", 3, "bi-arrow-up-circle")]:
        _sel(aid, label, "Gear (TransGearData)", {"GearLvrPos_D_Actl": val}, icon, "#b45309", "Gear")
    # Engine RPM.
    _sel("rpm_idle", "Idle", "Engine (Engine_Clutch_Data)", {"EngAout_N_Dsply": 800}, "bi-activity", "#334155", "Engine")
    _sel("rpm_rev", "Rev", "Engine (Engine_Clutch_Data)", {"EngAout_N_Dsply": 4000}, "bi-fire", "#334155", "Engine")


def _seed_layout() -> None:
    deck = ["speed_0", "speed_30", "speed_60", "speed_100", "speed_up",
            "speed_down", "gear_p", "gear_r", "gear_n", "gear_d",
            "rpm_idle", "rpm_rev", "speed_0", "gear_d", "gear_p"]
    start = ["speed_0", "speed_30", "speed_60", "speed_100", "speed_up", "speed_down",
             "gear_p", "gear_r", "gear_n", "gear_d", "rpm_idle", "rpm_rev"]
    layout_svc.set_layout("streamdeck", deck)
    layout_svc.set_layout("start", start)
