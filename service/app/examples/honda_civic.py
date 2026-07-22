"""Honda Civic (2022 EX, Bosch) live sample, on the real opendbc Honda DBC.

Uses the real `honda_civic_ex_2022_can_generated.dbc` from comma.ai's opendbc
(MIT), covering the Bosch-radar Civic's powertrain, steering, and body buses.
Monitoring is fully real: connect over the Waveshare HAT, open the Monitor
page, and the actual wheel speeds, vehicle speed, engine RPM, gear, and
steering-wheel cruise buttons decode from the bus.

Honda messages carry a rolling 2-bit COUNTER and a 4-bit CHECKSUM packed into
the same trailing byte (the checksum is a nibble, not a whole byte, unlike
Chrysler/Toyota). AutoPi computes it (the exact opendbc `honda_checksum`
algorithm, written through the DBC's own CHECKSUM signal so it lands in the
right bits) for the messages that set their checksum to `honda` below, so a
frame it sends carries a valid counter and checksum and a real module accepts
it. This DBC does not include proprietary infotainment/radio messages.

One vendoring note: this snapshot of the DBC (from a since-restructured point
in opendbc's history) has a few upstream typos, a missing semicolon and two
malformed `CM_` comment lines, that block a strict DBC parse. They are
corrected in the vendored copy (comment text and provenance preserved); see
`service/app/examples/data/NOTICE.md`.
"""
from __future__ import annotations

import os

from ..actions.registry import ActionSpec, upsert_action
from ..can import dbc as dbc_mod
from ..can import simulation
from ..db import CanDatabase, session_scope
from ..services import layout as layout_svc
from ..services import profiles as profiles_svc

NAME = "Honda Civic (2022 EX), real opendbc Bosch Civic"
DESCRIPTION = ("A live Honda Civic sample on the real honda_civic_ex_2022_can_generated.dbc "
               "(opendbc, MIT): monitor real wheel speeds, vehicle speed, engine RPM, gear, "
               "and steering-wheel cruise buttons, with a speed/RPM/gear cluster simulation. "
               "Reading is fully real; the checksum'd messages send a valid Honda "
               "counter/nibble checksum so a real module accepts them.")

CHANNEL = "can0"
DB_NAME = "Honda Bosch Civic (2022 EX, opendbc MIT)"
_DBC_PATH = os.path.join(os.path.dirname(__file__), "data", "honda_civic_ex_2022_can_generated.dbc")

WHEEL_SPEEDS = 0x1D0    # 464
CAR_SPEED = 0x309       # 777, counter + nibble checksum
ENGINE_DATA = 0x158     # 344, counter + nibble checksum
GEARBOX = 0x191         # 401, counter + nibble checksum
SCM_BUTTONS = 0x296     # 662, counter + nibble checksum


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


def _cmd(db_id, aid, label, message, signals, icon, color, category):
    upsert_action(ActionSpec(id=aid, label=label, driver="can_command", icon=icon, color=color,
                             category=category,
                             params={"channel": CHANNEL, "database_id": db_id,
                                     "message": message, "signals": signals,
                                     "checksum": "honda"}))


def load() -> dict:
    text = _dbc_text()
    with session_scope() as s:
        existing = s.query(CanDatabase).filter_by(name=DB_NAME).first()
        if existing is not None:
            db_id = existing.id
            existing.dbc_text = text
        else:
            d = dbc_mod.import_dbc(s, name=DB_NAME, dbc_text=text, source="opendbc",
                                   license="MIT", make="Honda", model="Civic", year=2022)
            s.flush()
            db_id = d.id

    prof = next((p for p in profiles_svc.list_profiles() if p.get("name") == "Civic"), None)
    if prof is None:
        prof = profiles_svc.create_profile(
            name="Civic", year=2022, make="Honda", model="Civic EX", vin="",
            config={"platform": "Bosch", "can_interfaces": ["can0", "can1"],
                    "can_database_ids": [db_id],
                    "notes": "Real opendbc Bosch Civic. Set your VIN. Monitor decodes real signals."})
    profiles_svc.set_active_profile(prof["id"])

    _seed_sim(db_id)
    _seed_actions(db_id)
    _seed_layout()

    from ..services import profile_bundle
    profile_bundle.capture(prof["id"])
    return {"ok": True, "profile_id": prof["id"], "database_id": db_id,
            "message": "Honda Civic loaded (real opendbc DBC). Open Monitor to decode a real "
                       "bus, or Simulate to drive a bench cluster."}


def _seed_sim(db_id: int) -> None:
    wanted = {
        "Wheel speeds (WHEEL_SPEEDS)": {"arbitration_id": hex(WHEEL_SPEEDS), "message": "WHEEL_SPEEDS",
                                        "signals": {"WHEEL_SPEED_FL": 0, "WHEEL_SPEED_FR": 0,
                                                    "WHEEL_SPEED_RL": 0, "WHEEL_SPEED_RR": 0}, "period_ms": 50},
        "Speed (CAR_SPEED)": {"arbitration_id": hex(CAR_SPEED), "message": "CAR_SPEED", "checksum": "honda",
                              "signals": {"CAR_SPEED": 0}, "period_ms": 50},
        "Engine (ENGINE_DATA)": {"arbitration_id": hex(ENGINE_DATA), "message": "ENGINE_DATA", "checksum": "honda",
                                 "signals": {"ENGINE_RPM": 800, "XMISSION_SPEED": 0}, "period_ms": 100},
        "Gear (GEARBOX)": {"arbitration_id": hex(GEARBOX), "message": "GEARBOX", "checksum": "honda",
                           "signals": {"GEAR_SHIFTER": 1, "GEAR": 1}, "period_ms": 100},  # P
    }
    existing = {e.get("name"): e for e in simulation.list_entries()}
    for name, spec in wanted.items():
        entry = {"name": name, "channel": CHANNEL, "backend": "socketcan",
                 "database_id": db_id, "is_fd": False, "enabled": True, **spec}
        if name in existing:
            simulation.update_entry(existing[name]["id"], entry)
        else:
            simulation.create_entry(entry)


def _seed_actions(db_id: int) -> None:
    # Vehicle speed (CAR_SPEED.CAR_SPEED is km/h, checksum'd real message).
    for kph in (0, 30, 60, 100):
        _sel(f"speed_{kph}", f"Speed {kph}", "Speed (CAR_SPEED)", {"CAR_SPEED": kph},
             "bi-speedometer2", "#0e7490", "Speed")
    _sel("speed_up", "Speed +5", "Speed (CAR_SPEED)", {"CAR_SPEED": 5}, "bi-plus-lg", "#0e7490", "Speed",
         mode="add", min=0, max=180)
    _sel("speed_down", "Speed -5", "Speed (CAR_SPEED)", {"CAR_SPEED": -5}, "bi-dash-lg", "#0e7490", "Speed",
         mode="add", min=0, max=180)
    # Wheel speeds together (kph).
    def wheels(kph):
        return {"WHEEL_SPEED_FL": kph, "WHEEL_SPEED_FR": kph, "WHEEL_SPEED_RL": kph, "WHEEL_SPEED_RR": kph}
    for kph in (0, 30, 60, 100):
        _sel(f"wheels_{kph}", f"Wheels {kph}", "Wheel speeds (WHEEL_SPEEDS)", wheels(kph),
             "bi-record-circle", "#0e7490", "Speed")
    # Engine RPM.
    _sel("rpm_idle", "Idle", "Engine (ENGINE_DATA)", {"ENGINE_RPM": 800}, "bi-activity", "#334155", "Engine")
    _sel("rpm_rev", "Rev", "Engine (ENGINE_DATA)", {"ENGINE_RPM": 4000}, "bi-fire", "#334155", "Engine")
    # Gear. GEARBOX carries two overlapping gear signals with different enums
    # (real DBC quirk): GEAR_SHIFTER (1=P,2=R,4=N,8=D,16=S,32=L) and GEAR
    # (1=P,2=R,3=N,4=D,7=L,10=S). Set both correctly so either decodes right.
    gears = [("gear_p", "P", 1, 1, "bi-p-circle"), ("gear_r", "R", 2, 2, "bi-arrow-counterclockwise"),
             ("gear_n", "N", 4, 3, "bi-n-circle"), ("gear_d", "D", 8, 4, "bi-arrow-up-circle"),
             ("gear_s", "S", 16, 10, "bi-lightning")]
    for aid, label, shifter_val, gear_val, icon in gears:
        _sel(aid, label, "Gear (GEARBOX)", {"GEAR_SHIFTER": shifter_val, "GEAR": gear_val},
             icon, "#b45309", "Gear")
    # Steering-wheel cruise buttons (real SCM_BUTTONS.CRUISE_BUTTONS enum,
    # checksum'd command so a real module accepts it).
    swc = [("swc_main", "Main", 1, "bi-power"), ("swc_cancel", "Cancel", 2, "bi-x-lg"),
           ("swc_set_minus", "Set -", 3, "bi-dash-lg"), ("swc_res_plus", "Res +", 4, "bi-plus-lg")]
    for aid, label, val, icon in swc:
        _cmd(db_id, aid, label, "SCM_BUTTONS", {"CRUISE_BUTTONS": val}, icon, "#7c3aed", "Steering wheel")
    _cmd(db_id, "swc_release", "Release", "SCM_BUTTONS", {"CRUISE_BUTTONS": 0}, "bi-arrow-counterclockwise",
         "#7c3aed", "Steering wheel")


def _seed_layout() -> None:
    deck = ["speed_0", "speed_30", "speed_60", "speed_100", "speed_up", "speed_down",
            "gear_p", "gear_r", "gear_n", "gear_d", "rpm_idle", "rpm_rev",
            "swc_main", "swc_res_plus", "swc_set_minus"]
    start = deck + ["gear_s", "swc_cancel", "swc_release", "wheels_0", "wheels_30", "wheels_60", "wheels_100"]
    layout_svc.set_layout("streamdeck", deck)
    layout_svc.set_layout("start", start)
