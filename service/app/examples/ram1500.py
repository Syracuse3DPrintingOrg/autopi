"""RAM 1500 (2024) live sample, built on a real open-source DBC.

Unlike the DT15 example (whose DBC is a placeholder), this uses the real
`chrysler_cusw.dbc` from comma.ai's opendbc (MIT), which covers the RAM 1500
(2019-2024) powertrain, steering, body, and driver-assist buses. That means:

- MONITORING is fully real: connect to a RAM 1500 over the Waveshare HAT, open
  the Monitor page, and the real speed, gear (PRNDL), steering angle, wheel
  speeds, doors, and seatbelt decode from the actual bus.
- The steering-wheel CRUISE/ACC buttons are the real messages the truck uses.

One honest caveat for SENDING: Chrysler messages carry a rolling COUNTER and a
CHECKSUM that receiving modules validate. This sample encodes structurally-correct
frames, but a real cluster/ECU may ignore a sent frame until that checksum is
computed (opendbc has the algorithm; wiring it in is a follow-up). Reading and
decoding are unaffected. It does not include proprietary infotainment/radio
messages, those are not in any open dataset and must be captured from the vehicle.
"""
from __future__ import annotations

import os

from ..actions.registry import ActionSpec, upsert_action
from ..can import dbc as dbc_mod
from ..can import simulation
from ..db import CanDatabase, session_scope
from ..services import layout as layout_svc
from ..services import profiles as profiles_svc

NAME = "RAM 1500 (2024) — real opendbc CUSW"
DESCRIPTION = ("A live RAM 1500 sample on the real chrysler_cusw.dbc (opendbc, MIT): "
               "monitor real speed/gear/steering/doors, a PRNDL and turn-signal selector, "
               "real steering-wheel cruise/ACC buttons, and a cluster simulation. "
               "Reading is fully real; sending to checksum-validated modules needs the "
               "Chrysler counter/checksum computed.")

CHANNEL = "can0"
DB_NAME = "Chrysler CUSW (RAM 1500 2019-2024, opendbc MIT)"
_DBC_PATH = os.path.join(os.path.dirname(__file__), "data", "chrysler_cusw.dbc")


def _dbc_text() -> str:
    with open(_DBC_PATH, encoding="utf-8") as f:
        return f.read()


def is_loaded() -> bool:
    try:
        with session_scope() as s:
            return s.query(CanDatabase).filter_by(name=DB_NAME).first() is not None
    except Exception:
        return False


def _cmd(db_id, aid, label, message, signals, icon, color, category):
    upsert_action(ActionSpec(id=aid, label=label, driver="can_command", icon=icon, color=color,
                             category=category,
                             params={"channel": CHANNEL, "database_id": db_id,
                                     "message": message, "signals": signals}))


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
                                   license="MIT", make="Stellantis", model="RAM 1500", year=2024)
            s.flush()
            db_id = d.id

    prof = next((p for p in profiles_svc.list_profiles() if p.get("name") == "RAM1500"), None)
    if prof is None:
        prof = profiles_svc.create_profile(
            name="RAM1500", year=2024, make="Stellantis", model="RAM 1500", vin="",
            config={"platform": "CUSW", "can_interfaces": ["can0", "can1"],
                    "can_database_ids": [db_id],
                    "notes": "Real opendbc CUSW. Set your VIN. Monitor decodes real signals."})
    profiles_svc.set_active_profile(prof["id"])

    _seed_sim(db_id)
    _seed_actions(db_id)
    _seed_layout()

    from ..services import profile_bundle
    profile_bundle.capture(prof["id"])
    return {"ok": True, "profile_id": prof["id"], "database_id": db_id,
            "message": "RAM 1500 loaded (real opendbc DBC). Open Monitor to decode a real bus, "
                       "or Simulate to drive a bench cluster."}


def _seed_sim(db_id: int) -> None:
    # Periodic broadcast for a bench cluster. Real message ids/signals; the
    # selectors below update these live. (See the checksum caveat in the docstring.)
    wanted = {
        "Speed (CLUSTER_1)": {"arbitration_id": "0x1F0", "message": "CLUSTER_1",
                              "signals": {"SPEEDOMETER": 0, "TACHOMETER": 0}, "period_ms": 100},
        "Gear (GEAR)": {"arbitration_id": "0x4EE", "message": "GEAR", "signals": {"PRNDL": 1}, "period_ms": 100},
        "Turn signals": {"arbitration_id": "0x4F0", "message": "STEERING_LEVERS",
                         "signals": {"TURN_SIGNALS": 0}, "period_ms": 200},
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
    # Steering-wheel cruise / ACC buttons (real CRUISE_BUTTONS message).
    swc = [("swc_cruise_onoff", "Cruise On/Off", "Cruise_OnOff", "bi-power"),
           ("swc_acc_onoff", "ACC On/Off", "ACC_OnOff", "bi-toggle-on"),
           ("swc_resume", "Resume", "ACC_Resume", "bi-play-fill"),
           ("swc_set_plus", "Set +", "ACC_Accel", "bi-plus-lg"),
           ("swc_set_minus", "Set -", "ACC_Decel", "bi-dash-lg"),
           ("swc_cancel", "Cancel", "ACC_Cancel", "bi-x-lg"),
           ("swc_dist_inc", "Gap +", "ACC_Distance_Inc", "bi-chevron-double-up"),
           ("swc_dist_dec", "Gap -", "ACC_Distance_Dec", "bi-chevron-double-down")]
    for aid, label, sig, icon in swc:
        _cmd(db_id, aid, label, "CRUISE_BUTTONS", {sig: 1}, icon, "#7c3aed", "Steering wheel")

    # PRNDL selector (real GEAR.PRNDL enum: 1=P,2=R,3=N,4=D,5=S).
    for aid, label, val, icon in [("gear_p", "P", 1, "bi-p-circle"), ("gear_r", "R", 2, "bi-arrow-counterclockwise"),
                                  ("gear_n", "N", 3, "bi-n-circle"), ("gear_d", "D", 4, "bi-arrow-up-circle"),
                                  ("gear_s", "S", 5, "bi-lightning")]:
        _sel(aid, label, "Gear (GEAR)", {"PRNDL": val}, icon, "#b45309", "Gear")

    # Turn signals (STEERING_LEVERS.TURN_SIGNALS).
    _sel("turn_left", "Turn L", "Turn signals", {"TURN_SIGNALS": 1}, "bi-arrow-left", "#166534", "Signals")
    _sel("turn_right", "Turn R", "Turn signals", {"TURN_SIGNALS": 2}, "bi-arrow-right", "#166534", "Signals")
    _sel("turn_off", "Signals Off", "Turn signals", {"TURN_SIGNALS": 0}, "bi-x", "#166534", "Signals")

    # Speed (CLUSTER_1.SPEEDOMETER is m/s; label in km/h).
    for aid, kph in [("speed_0", 0), ("speed_30", 30), ("speed_60", 60), ("speed_100", 100)]:
        _sel(aid, f"Speed {kph}", "Speed (CLUSTER_1)", {"SPEEDOMETER": round(kph / 3.6, 3)},
             "bi-speedometer2", "#0e7490", "Speed")
    _sel("speed_up", "Speed +5", "Speed (CLUSTER_1)", {"SPEEDOMETER": 1.389}, "bi-plus-lg", "#0e7490", "Speed", mode="add", min=0, max=70)
    _sel("speed_down", "Speed -5", "Speed (CLUSTER_1)", {"SPEEDOMETER": -1.389}, "bi-dash-lg", "#0e7490", "Speed", mode="add", min=0, max=70)
    # Tach (RPM idle / rev).
    _sel("rpm_idle", "Idle", "Speed (CLUSTER_1)", {"TACHOMETER": 800}, "bi-activity", "#334155", "Engine")
    _sel("rpm_rev", "Rev", "Speed (CLUSTER_1)", {"TACHOMETER": 3000}, "bi-fire", "#334155", "Engine")


def _seed_layout() -> None:
    deck = ["swc_cruise_onoff", "swc_resume", "swc_set_plus", "swc_set_minus", "swc_cancel",
            "gear_p", "gear_r", "gear_n", "gear_d", "turn_left",
            "turn_right", "speed_0", "speed_60", "speed_down", "speed_up"]
    start = deck + ["swc_acc_onoff", "swc_dist_inc", "swc_dist_dec", "gear_s", "turn_off",
                    "speed_30", "speed_100", "rpm_idle", "rpm_rev"]
    layout_svc.set_layout("streamdeck", deck)
    layout_svc.set_layout("start", start)
