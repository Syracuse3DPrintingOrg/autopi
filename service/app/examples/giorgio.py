"""Alfa Romeo Giulia (2024) live sample, on the real opendbc Giorgio DBC.

Uses the real `fca_giorgio.dbc` from comma.ai's opendbc (MIT), which covers the
Stellantis Giorgio platform: Alfa Romeo Giulia and Stelvio, and the Maserati
Grecale. Like the RAM 1500 sample, its monitoring is fully real: connect over the
Waveshare HAT, open the Monitor page, and the actual wheel speeds, steering
angle, engine RPM, and ACC HUD speed decode from the bus.

The Giorgio messages carry a rolling COUNTER and a J1850 CRC checksum (with a
per-message final XOR). AutoPi computes both (the exact opendbc algorithm) for
the messages that set their checksum to `fca_giorgio` below, so a frame it sends
carries a valid counter and checksum and a real module accepts it. This DBC does
not include proprietary infotainment/radio messages.
"""
from __future__ import annotations

import os

from ..actions.registry import ActionSpec, upsert_action
from ..can import dbc as dbc_mod
from ..db import CanDatabase, session_scope
from ..can import simulation
from ..services import layout as layout_svc
from ..services import profiles as profiles_svc

NAME = "Alfa Romeo Giulia (2024), real opendbc Giorgio"
DESCRIPTION = ("A live Alfa Romeo Giulia sample on the real fca_giorgio.dbc (opendbc, MIT): "
               "monitor real wheel speeds, steering angle, engine RPM, and ACC HUD speed, with a "
               "speed / RPM / steering cluster simulation. Reading is fully real; the checksum'd "
               "messages send a valid J1850 counter/checksum so a real module accepts them.")

CHANNEL = "can0"
DB_NAME = "FCA Giorgio (Alfa Romeo Giulia/Stelvio, Maserati Grecale, opendbc MIT)"
_DBC_PATH = os.path.join(os.path.dirname(__file__), "data", "fca_giorgio.dbc")

ABS_1 = 0xEE     # 238 wheel speeds
ENGINE_1 = 0xFC  # 252 engine rpm
EPS_1 = 0xDE     # 222 steering angle
ACC_1 = 0x5A2    # 1442 ACC HUD (no checksum signal)


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
                                   license="MIT", make="Stellantis", model="Alfa Romeo Giulia", year=2024)
            s.flush()
            db_id = d.id

    prof = next((p for p in profiles_svc.list_profiles() if p.get("name") == "Giulia"), None)
    if prof is None:
        prof = profiles_svc.create_profile(
            name="Giulia", year=2024, make="Alfa Romeo", model="Giulia", vin="",
            config={"platform": "Giorgio", "can_interfaces": ["can0", "can1"],
                    "can_database_ids": [db_id],
                    "notes": "Real opendbc Giorgio. Set your VIN. Monitor decodes real signals."})
    profiles_svc.set_active_profile(prof["id"])

    _seed_sim(db_id)
    _seed_actions()
    _seed_layout()

    from ..services import profile_bundle
    profile_bundle.capture(prof["id"])
    return {"ok": True, "profile_id": prof["id"], "database_id": db_id,
            "message": "Alfa Romeo Giulia loaded (real opendbc DBC). Open Monitor to decode a real "
                       "bus, or Simulate to drive a bench cluster."}


def _seed_sim(db_id: int) -> None:
    wanted = {
        "Wheel speeds (ABS_1)": {"arbitration_id": hex(ABS_1), "message": "ABS_1", "checksum": "fca_giorgio",
                                 "signals": {"WHEEL_SPEED_FL": 0, "WHEEL_SPEED_FR": 0,
                                             "WHEEL_SPEED_RL": 0, "WHEEL_SPEED_RR": 0}, "period_ms": 50},
        "Engine (ENGINE_1)": {"arbitration_id": hex(ENGINE_1), "message": "ENGINE_1", "checksum": "fca_giorgio",
                              "signals": {"ENGINE_RPM": 800}, "period_ms": 50},
        "Steering (EPS_1)": {"arbitration_id": hex(EPS_1), "message": "EPS_1", "checksum": "fca_giorgio",
                             "signals": {"STEERING_ANGLE": 0, "STEERING_RATE": 0}, "period_ms": 50},
        "ACC HUD (ACC_1)": {"arbitration_id": hex(ACC_1), "message": "ACC_1",
                            "signals": {"HUD_SPEED": 0}, "period_ms": 100},
    }
    existing = {e.get("name"): e for e in simulation.list_entries()}
    for name, spec in wanted.items():
        entry = {"name": name, "channel": CHANNEL, "backend": "socketcan",
                 "database_id": db_id, "is_fd": False, "enabled": True, **spec}
        if name in existing:
            simulation.update_entry(existing[name]["id"], entry)
        else:
            simulation.create_entry(entry)


def _seed_actions() -> None:
    # Vehicle speed: set all four wheel speeds together (ABS_1, m/s), label km/h.
    def wheels(kph):
        v = round(kph / 3.6, 3)
        return {"WHEEL_SPEED_FL": v, "WHEEL_SPEED_FR": v, "WHEEL_SPEED_RL": v, "WHEEL_SPEED_RR": v}
    for kph in (0, 30, 60, 100):
        _sel(f"speed_{kph}", f"Speed {kph}", "Wheel speeds (ABS_1)", wheels(kph),
             "bi-speedometer2", "#0e7490", "Speed")
    _sel("speed_up", "Speed +5", "Wheel speeds (ABS_1)",
         {k: 1.389 for k in wheels(0)}, "bi-plus-lg", "#0e7490", "Speed", mode="add", min=0, max=70)
    _sel("speed_down", "Speed -5", "Wheel speeds (ABS_1)",
         {k: -1.389 for k in wheels(0)}, "bi-dash-lg", "#0e7490", "Speed", mode="add", min=0, max=70)
    # HUD speed on the ACC message.
    for kph in (0, 60, 120):
        _sel(f"hud_{kph}", f"HUD {kph}", "ACC HUD (ACC_1)", {"HUD_SPEED": kph}, "bi-badge-hd", "#1d4ed8", "HUD")
    # Engine RPM.
    _sel("rpm_idle", "Idle", "Engine (ENGINE_1)", {"ENGINE_RPM": 800}, "bi-activity", "#334155", "Engine")
    _sel("rpm_rev", "Rev", "Engine (ENGINE_1)", {"ENGINE_RPM": 4000}, "bi-fire", "#334155", "Engine")
    # Steering angle.
    _sel("steer_center", "Center", "Steering (EPS_1)", {"STEERING_ANGLE": 0}, "bi-dot", "#b45309", "Steering")
    _sel("steer_left", "Left 90", "Steering (EPS_1)", {"STEERING_ANGLE": -90}, "bi-arrow-90deg-left", "#b45309", "Steering")
    _sel("steer_right", "Right 90", "Steering (EPS_1)", {"STEERING_ANGLE": 90}, "bi-arrow-90deg-right", "#b45309", "Steering")


def _seed_layout() -> None:
    deck = ["speed_0", "speed_30", "speed_60", "speed_100", "speed_up",
            "speed_down", "rpm_idle", "rpm_rev", "steer_left", "steer_center",
            "steer_right", "hud_0", "hud_60", "hud_120", "steer_center"]
    start = ["speed_0", "speed_30", "speed_60", "speed_100", "speed_up", "speed_down",
             "rpm_idle", "rpm_rev", "steer_left", "steer_center", "steer_right",
             "hud_0", "hud_60", "hud_120"]
    layout_svc.set_layout("streamdeck", deck)
    layout_svc.set_layout("start", start)
