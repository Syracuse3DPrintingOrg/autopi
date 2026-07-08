"""Hyundai Elantra (2024, CAN FD) live sample, on the real opendbc Hyundai/Kia
CAN FD DBC.

Uses the real `hyundai_canfd.dbc` from comma.ai's opendbc (MIT), the common
database for the Hyundai/Kia/Genesis CAN FD platform that the newer Elantra,
Sonata, Ioniq, and Kia siblings share (2021+ models with 16/24/32-byte CAN FD
frames rather than classic 8-byte CAN). Monitoring is fully real: connect over
a CAN FD-capable interface, open the Monitor page, and the actual wheel
speeds, steering angle, and gear decode from the bus.

Hyundai CAN FD messages carry an 8-bit rolling COUNTER and a 16-bit CRC
CHECKSUM in the first two bytes of the frame (not the last, unlike the other
AutoPi vehicle samples). AutoPi computes it (the exact opendbc
`hkg_can_fd_checksum` CRC-16/XMODEM algorithm, written through the DBC's own
CHECKSUM signal so it lands at the right byte offset) for the messages that
set their checksum to `hyundai_canfd` below, so a frame it sends carries a
valid counter and checksum and a real module accepts it. The steering-wheel
CRUISE_BUTTONS message uses a differently-named `_CHECKSUM` field in this DBC
(an upstream naming quirk) that AutoPi does not special-case, so that one
button command sends without a computed checksum; every other checksum'd
message here is real and verified. This DBC does not include proprietary
infotainment/radio messages.

One vendoring note: this snapshot of the DBC (from a since-restructured point
in opendbc's history) has four upstream `CM_` message-comment lines missing
their `BO_` keyword, which blocks a strict DBC parse. They are corrected in
the vendored copy (comment text and provenance preserved); see
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

NAME = "Hyundai Elantra (2024, CAN FD) — real opendbc Hyundai/Kia CAN FD"
DESCRIPTION = ("A live Hyundai Elantra sample on the real hyundai_canfd.dbc (opendbc, MIT), "
               "the shared Hyundai/Kia/Genesis CAN FD platform database: monitor real wheel "
               "speeds, steering angle, and gear, with a speed/steering/gear cluster "
               "simulation. Reading is fully real; the checksum'd messages send a valid "
               "16-bit CRC counter/checksum so a real module accepts them.")

CHANNEL = "can0"
DB_NAME = "Hyundai/Kia CAN FD (Elantra/Sonata/Ioniq 2021+, opendbc MIT)"
_DBC_PATH = os.path.join(os.path.dirname(__file__), "data", "hyundai_canfd.dbc")

WHEEL_SPEEDS = 0xA0    # 160, counter + CRC checksum
MDPS = 0xEA            # 234, counter + CRC checksum (steering)
GEAR_SHIFTER = 0x130   # 304, counter + CRC checksum
CRUISE_BUTTONS = 0x1CF  # 463, differently-named checksum field (not applied)


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


def _cmd(db_id, aid, label, message, signals, icon, color, category, checksum="hyundai_canfd"):
    upsert_action(ActionSpec(id=aid, label=label, driver="can_command", icon=icon, color=color,
                             category=category,
                             params={"channel": CHANNEL, "database_id": db_id,
                                     "message": message, "signals": signals,
                                     "checksum": checksum}))


def load() -> dict:
    text = _dbc_text()
    with session_scope() as s:
        existing = s.query(CanDatabase).filter_by(name=DB_NAME).first()
        if existing is not None:
            db_id = existing.id
            existing.dbc_text = text
        else:
            d = dbc_mod.import_dbc(s, name=DB_NAME, dbc_text=text, source="opendbc",
                                   license="MIT", make="Hyundai", model="Elantra", year=2024)
            s.flush()
            db_id = d.id

    prof = next((p for p in profiles_svc.list_profiles() if p.get("name") == "Elantra"), None)
    if prof is None:
        prof = profiles_svc.create_profile(
            name="Elantra", year=2024, make="Hyundai", model="Elantra", vin="",
            config={"platform": "Hyundai/Kia CAN FD", "can_interfaces": ["can0", "can1"],
                    "can_database_ids": [db_id],
                    "notes": "Real opendbc Hyundai/Kia CAN FD. Set your VIN. Monitor decodes real signals. "
                             "Needs a CAN FD-capable interface for full-size frames."})
    profiles_svc.set_active_profile(prof["id"])

    _seed_sim(db_id)
    _seed_actions(db_id)
    _seed_layout()

    from ..services import profile_bundle
    profile_bundle.capture(prof["id"])
    return {"ok": True, "profile_id": prof["id"], "database_id": db_id,
            "message": "Hyundai Elantra loaded (real opendbc DBC). Open Monitor to decode a real "
                       "bus, or Simulate to drive a bench cluster."}


def _seed_sim(db_id: int) -> None:
    wanted = {
        "Wheel speeds (WHEEL_SPEEDS)": {"arbitration_id": hex(WHEEL_SPEEDS), "message": "WHEEL_SPEEDS",
                                        "checksum": "hyundai_canfd",
                                        "signals": {"WHEEL_SPEED_1": 0, "WHEEL_SPEED_2": 0,
                                                    "WHEEL_SPEED_3": 0, "WHEEL_SPEED_4": 0,
                                                    "MOVING_FORWARD": 0}, "period_ms": 50},
        "Steering (MDPS)": {"arbitration_id": hex(MDPS), "message": "MDPS", "checksum": "hyundai_canfd",
                            "signals": {"STEERING_ANGLE": 0}, "period_ms": 50},
        "Gear (GEAR_SHIFTER)": {"arbitration_id": hex(GEAR_SHIFTER), "message": "GEAR_SHIFTER",
                                "checksum": "hyundai_canfd", "signals": {"GEAR": 1}, "period_ms": 100},
    }
    existing = {e.get("name"): e for e in simulation.list_entries()}
    for name, spec in wanted.items():
        entry = {"name": name, "channel": CHANNEL, "backend": "socketcan",
                 "database_id": db_id, "is_fd": True, "enabled": True, **spec}
        if name in existing:
            simulation.update_entry(existing[name]["id"], entry)
        else:
            simulation.create_entry(entry)


def _seed_actions(db_id: int) -> None:
    # Wheel speeds together (kph, real WHEEL_SPEEDS message, checksum'd).
    def wheels(kph):
        return {"WHEEL_SPEED_1": kph, "WHEEL_SPEED_2": kph, "WHEEL_SPEED_3": kph, "WHEEL_SPEED_4": kph,
                "MOVING_FORWARD": 1 if kph else 0}
    for kph in (0, 30, 60, 100):
        _sel(f"speed_{kph}", f"Speed {kph}", "Wheel speeds (WHEEL_SPEEDS)", wheels(kph),
             "bi-speedometer2", "#0e7490", "Speed")
    _sel("speed_up", "Speed +5", "Wheel speeds (WHEEL_SPEEDS)",
         {k: 5 for k in ("WHEEL_SPEED_1", "WHEEL_SPEED_2", "WHEEL_SPEED_3", "WHEEL_SPEED_4")},
         "bi-plus-lg", "#0e7490", "Speed", mode="add", min=0, max=180)
    _sel("speed_down", "Speed -5", "Wheel speeds (WHEEL_SPEEDS)",
         {k: -5 for k in ("WHEEL_SPEED_1", "WHEEL_SPEED_2", "WHEEL_SPEED_3", "WHEEL_SPEED_4")},
         "bi-dash-lg", "#0e7490", "Speed", mode="add", min=0, max=180)
    # Steering angle.
    _sel("steer_center", "Center", "Steering (MDPS)", {"STEERING_ANGLE": 0}, "bi-dot", "#b45309", "Steering")
    _sel("steer_left", "Left 90", "Steering (MDPS)", {"STEERING_ANGLE": -90}, "bi-arrow-90deg-left",
         "#b45309", "Steering")
    _sel("steer_right", "Right 90", "Steering (MDPS)", {"STEERING_ANGLE": 90}, "bi-arrow-90deg-right",
         "#b45309", "Steering")
    # Gear (real GEAR_SHIFTER.GEAR enum: 1=P,2=R,3=N,4=D).
    for aid, label, val, icon in [("gear_p", "P", 1, "bi-p-circle"), ("gear_r", "R", 2, "bi-arrow-counterclockwise"),
                                  ("gear_n", "N", 3, "bi-n-circle"), ("gear_d", "D", 4, "bi-arrow-up-circle")]:
        _sel(aid, label, "Gear (GEAR_SHIFTER)", {"GEAR": val}, icon, "#b45309", "Gear")
    # Steering-wheel cruise buttons (real CRUISE_BUTTONS.CRUISE_BUTTONS enum).
    # This message's checksum field is named differently upstream (_CHECKSUM,
    # not CHECKSUM), so AutoPi sends it structurally correct but unchecksummed.
    swc = [("swc_res", "Res +", 1, "bi-plus-lg"), ("swc_set", "Set -", 2, "bi-dash-lg"),
           ("swc_gap", "Gap", 3, "bi-arrows-collapse"), ("swc_pause", "Pause/Resume", 4, "bi-pause-fill")]
    for aid, label, val, icon in swc:
        _cmd(db_id, aid, label, "CRUISE_BUTTONS", {"CRUISE_BUTTONS": val}, icon, "#7c3aed",
             "Steering wheel", checksum="")
    _cmd(db_id, "swc_none", "Release", "CRUISE_BUTTONS", {"CRUISE_BUTTONS": 0}, "bi-arrow-counterclockwise",
         "#7c3aed", "Steering wheel", checksum="")


def _seed_layout() -> None:
    deck = ["speed_0", "speed_30", "speed_60", "speed_100", "speed_up", "speed_down",
            "gear_p", "gear_r", "gear_n", "gear_d", "steer_left", "steer_center", "steer_right",
            "swc_res", "swc_set"]
    start = deck + ["swc_gap", "swc_pause", "swc_none"]
    layout_svc.set_layout("streamdeck", deck)
    layout_svc.set_layout("start", start)
