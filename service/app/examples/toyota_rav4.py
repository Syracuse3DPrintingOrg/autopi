"""Toyota RAV4 (2024) live sample, on the real opendbc dsu-less Toyota DBC.

Uses the real `toyota_nodsu_pt_generated.dbc` from comma.ai's opendbc (MIT),
covering the powertrain bus of dsu-less (no Driving Support ECU) Toyota/Lexus
models from around 2020 on, RAV4 among them. Monitoring is fully real: connect
over the Waveshare HAT, open the Monitor page, and the actual wheel speeds,
vehicle speed, engine RPM, gear, and cruise state decode from the bus.

Toyota messages carry an 8-bit checksum in the last byte of the frame (some
also carry a rolling COUNTER). AutoPi computes the checksum (the exact opendbc
`toyota_checksum` algorithm) for the messages that set their checksum to
`toyota` below, so a frame it sends carries a valid checksum and a real module
accepts it. This DBC does not include proprietary infotainment/radio messages.
"""
from __future__ import annotations

import os

from ..actions.registry import ActionSpec, upsert_action
from ..can import dbc as dbc_mod
from ..can import simulation
from ..db import CanDatabase, session_scope
from ..services import layout as layout_svc
from ..services import profiles as profiles_svc

NAME = "Toyota RAV4 (2024), real opendbc dsu-less Toyota"
DESCRIPTION = ("A live Toyota RAV4 sample on the real toyota_nodsu_pt_generated.dbc "
               "(opendbc, MIT): monitor real wheel speeds, vehicle speed, engine RPM, "
               "gear, and cruise state, with a speed/RPM/gear cluster simulation. Reading "
               "is fully real; the checksum'd messages send a valid Toyota checksum so a "
               "real module accepts them.")

CHANNEL = "can0"
DB_NAME = "Toyota dsu-less powertrain (RAV4/Corolla 2020+, opendbc MIT)"
_DBC_PATH = os.path.join(os.path.dirname(__file__), "data", "toyota_nodsu_pt_generated.dbc")

WHEEL_SPEEDS = 0xAA   # 170, no checksum
SPEED = 0xB4          # 180, vehicle speed + checksum
ENGINE_RPM = 0x1C4    # 452, no checksum
GEAR_PACKET = 0x3BC   # 956, no checksum
PCM_CRUISE = 0x1D2    # 466, cruise state + checksum
STEERING_LKA = 0x2E4  # 740, counter + checksum


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
                                     "checksum": "toyota"}))


def load() -> dict:
    text = _dbc_text()
    with session_scope() as s:
        existing = s.query(CanDatabase).filter_by(name=DB_NAME).first()
        if existing is not None:
            db_id = existing.id
            existing.dbc_text = text
        else:
            d = dbc_mod.import_dbc(s, name=DB_NAME, dbc_text=text, source="opendbc",
                                   license="MIT", make="Toyota", model="RAV4", year=2024)
            s.flush()
            db_id = d.id

    prof = next((p for p in profiles_svc.list_profiles() if p.get("name") == "RAV4"), None)
    if prof is None:
        prof = profiles_svc.create_profile(
            name="RAV4", year=2024, make="Toyota", model="RAV4", vin="",
            config={"platform": "TNGA dsu-less", "can_interfaces": ["can0", "can1"],
                    "can_database_ids": [db_id],
                    "notes": "Real opendbc dsu-less Toyota. Set your VIN. Monitor decodes real signals."})
    profiles_svc.set_active_profile(prof["id"])

    _seed_sim(db_id)
    _seed_actions(db_id)
    _seed_layout()

    from ..services import profile_bundle
    profile_bundle.capture(prof["id"])
    return {"ok": True, "profile_id": prof["id"], "database_id": db_id,
            "message": "Toyota RAV4 loaded (real opendbc DBC). Open Monitor to decode a real "
                       "bus, or Simulate to drive a bench cluster."}


def _seed_sim(db_id: int) -> None:
    wanted = {
        "Wheel speeds (WHEEL_SPEEDS)": {"arbitration_id": hex(WHEEL_SPEEDS), "message": "WHEEL_SPEEDS",
                                        "signals": {"WHEEL_SPEED_FL": 0, "WHEEL_SPEED_FR": 0,
                                                    "WHEEL_SPEED_RL": 0, "WHEEL_SPEED_RR": 0}, "period_ms": 50},
        "Speed (SPEED)": {"arbitration_id": hex(SPEED), "message": "SPEED", "checksum": "toyota",
                          "signals": {"SPEED": 0}, "period_ms": 50},
        "Engine (ENGINE_RPM)": {"arbitration_id": hex(ENGINE_RPM), "message": "ENGINE_RPM",
                                "signals": {"RPM": 800, "ENGINE_RUNNING": 1}, "period_ms": 100},
        "Gear (GEAR_PACKET)": {"arbitration_id": hex(GEAR_PACKET), "message": "GEAR_PACKET",
                               "signals": {"GEAR": 0, "DRIVE_ENGAGED": 0}, "period_ms": 100},
        "Cruise (PCM_CRUISE)": {"arbitration_id": hex(PCM_CRUISE), "message": "PCM_CRUISE", "checksum": "toyota",
                                "signals": {"CRUISE_ACTIVE": 0, "CRUISE_STATE": 0}, "period_ms": 100},
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
    # Vehicle speed (SPEED.SPEED is km/h already).
    for kph in (0, 30, 60, 100):
        _sel(f"speed_{kph}", f"Speed {kph}", "Speed (SPEED)", {"SPEED": kph},
             "bi-speedometer2", "#0e7490", "Speed")
    _sel("speed_up", "Speed +5", "Speed (SPEED)", {"SPEED": 5}, "bi-plus-lg", "#0e7490", "Speed",
         mode="add", min=0, max=180)
    _sel("speed_down", "Speed -5", "Speed (SPEED)", {"SPEED": -5}, "bi-dash-lg", "#0e7490", "Speed",
         mode="add", min=0, max=180)
    # Wheel speeds together (km/h, matching the SPEED signal's scale).
    def wheels(kph):
        return {"WHEEL_SPEED_FL": kph, "WHEEL_SPEED_FR": kph, "WHEEL_SPEED_RL": kph, "WHEEL_SPEED_RR": kph}
    for kph in (0, 30, 60, 100):
        _sel(f"wheels_{kph}", f"Wheels {kph}", "Wheel speeds (WHEEL_SPEEDS)", wheels(kph),
             "bi-record-circle", "#0e7490", "Speed")
    # Engine RPM.
    _sel("rpm_idle", "Idle", "Engine (ENGINE_RPM)", {"RPM": 800, "ENGINE_RUNNING": 1},
         "bi-activity", "#334155", "Engine")
    _sel("rpm_rev", "Rev", "Engine (ENGINE_RPM)", {"RPM": 4000, "ENGINE_RUNNING": 1},
         "bi-fire", "#334155", "Engine")
    # Gear (real GEAR_PACKET.GEAR enum: 0=D,1=S,8=N,16=R,32=P).
    for aid, label, val, icon in [("gear_p", "P", 32, "bi-p-circle"), ("gear_r", "R", 16, "bi-arrow-counterclockwise"),
                                  ("gear_n", "N", 8, "bi-n-circle"), ("gear_d", "D", 0, "bi-arrow-up-circle")]:
        engaged = 1 if val == 0 else 0
        _sel(aid, label, "Gear (GEAR_PACKET)", {"GEAR": val, "DRIVE_ENGAGED": engaged}, icon, "#b45309", "Gear")
    # Cruise state (real PCM_CRUISE, checksum'd).
    _sel("cruise_off", "Cruise Off", "Cruise (PCM_CRUISE)", {"CRUISE_ACTIVE": 0, "CRUISE_STATE": 0},
         "bi-power", "#7c3aed", "Cruise")
    _sel("cruise_on", "Cruise On", "Cruise (PCM_CRUISE)", {"CRUISE_ACTIVE": 1, "CRUISE_STATE": 6},
         "bi-toggle-on", "#7c3aed", "Cruise")
    # Real STEERING_LKA command (checksum'd) to demonstrate a real send target.
    _cmd(db_id, "lka_request_on", "LKA Request", "STEERING_LKA",
         {"STEER_REQUEST": 1, "SET_ME_1": 1, "STEER_TORQUE_CMD": 0}, "bi-compass", "#7c3aed", "Steering")
    _cmd(db_id, "lka_request_off", "LKA Release", "STEERING_LKA",
         {"STEER_REQUEST": 0, "SET_ME_1": 1, "STEER_TORQUE_CMD": 0}, "bi-x-circle", "#7c3aed", "Steering")


def _seed_layout() -> None:
    deck = ["speed_0", "speed_30", "speed_60", "speed_100", "speed_up", "speed_down",
            "gear_p", "gear_r", "gear_n", "gear_d", "rpm_idle", "rpm_rev",
            "cruise_off", "cruise_on", "wheels_60"]
    start = deck + ["wheels_0", "wheels_30", "wheels_100", "lka_request_on", "lka_request_off"]
    layout_svc.set_layout("streamdeck", deck)
    layout_svc.set_layout("start", start)
