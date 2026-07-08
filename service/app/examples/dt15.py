"""DT15 case study: a 2025 RAM DT (Atlantis High) test bench.

Loads a complete, working scenario in one step: a vehicle profile, an example
CAN database, a Stream Deck / start-menu layout, and a running instrument-cluster
simulation. It exercises every part of AutoPi end to end:

- media / ICS controls and steering-wheel media controls as CAN commands sent to
  the radio,
- an adjustable vehicle-speed signal,
- a PNDL (P/R/N/D/L) selector and an ignition (Off/Accy/Run/Start) selector, each
  of which updates a periodically-transmitted message so the connected
  instrument cluster follows along, and
- the instrument cluster itself simulated as periodic CAN broadcast.

The DBC below is an EXAMPLE with representative message and signal layouts, not
the vehicle's real proprietary definitions. Swap in the real DBC (import your own
on the CAN page) and repoint the actions to drive a real radio, display, and
cluster over the Waveshare 2-Channel CAN-FD HAT.
"""
from __future__ import annotations

from ..actions.registry import ActionSpec, upsert_action
from ..can import dbc as dbc_mod
from ..can import simulation
from ..db import CanDatabase, session_scope
from ..services import layout as layout_svc
from ..services import profiles as profiles_svc

NAME = "DT15 — 2025 RAM DT (Atlantis High)"
DESCRIPTION = ("A full RAM DT test bench: media/ICS and steering-wheel controls, "
               "an adjustable speed signal, PNDL and ignition selectors, and a "
               "simulated instrument cluster, over the Waveshare 2-Ch CAN-FD HAT.")

CHANNEL = "can0"
DB_NAME = "RAM DT Atlantis High (example)"

# Message ids used below (match the DBC).
ICS = 0x200          # 512 ICS_Command
SWC = 0x201          # 513 SWC_Media
SPEED = 0x100        # 256 VehicleSpeed
TRANS = 0x101        # 257 Transmission
IGN = 0x102          # 258 IgnitionStatus
CL_ENGINE = 0x120    # 288 Cluster_Engine
CL_STATUS = 0x121    # 289 Cluster_Status

DBC_TEXT = '''VERSION ""

BU_: PI RADIO CLUSTER DISPLAY

BO_ 512 ICS_Command: 8 PI
 SG_ ICS_MediaCmd : 0|8@1+ (1,0) [0|255] "" RADIO
 SG_ ICS_Volume : 8|8@1+ (1,0) [0|40] "" RADIO
 SG_ ICS_Source : 16|4@1+ (1,0) [0|15] "" RADIO

BO_ 513 SWC_Media: 8 PI
 SG_ SWC_Button : 0|8@1+ (1,0) [0|255] "" RADIO

BO_ 256 VehicleSpeed: 8 PI
 SG_ Speed : 0|16@1+ (0.01,0) [0|655.35] "km/h" CLUSTER,RADIO,DISPLAY

BO_ 257 Transmission: 8 PI
 SG_ Gear : 0|4@1+ (1,0) [0|15] "" CLUSTER,DISPLAY

BO_ 258 IgnitionStatus: 8 PI
 SG_ IgnState : 0|4@1+ (1,0) [0|15] "" CLUSTER,RADIO,DISPLAY

BO_ 288 Cluster_Engine: 8 PI
 SG_ EngineRPM : 0|16@1+ (0.25,0) [0|16383.75] "rpm" CLUSTER

BO_ 289 Cluster_Status: 8 PI
 SG_ FuelLevel : 0|8@1+ (0.5,0) [0|100] "%" CLUSTER
 SG_ CoolantTemp : 8|8@1+ (1,-40) [-40|215] "degC" CLUSTER

VAL_ 257 Gear 0 "P" 1 "R" 2 "N" 3 "D" 4 "L" ;
VAL_ 258 IgnState 0 "Off" 1 "Accy" 2 "Run" 3 "Start" ;
'''


def is_loaded() -> bool:
    try:
        with session_scope() as s:
            return s.query(CanDatabase).filter_by(name=DB_NAME).first() is not None
    except Exception:
        return False


def _cmd(action_id, label, message, signals, icon, color, category, db_id):
    """A momentary CAN command sent to the radio (can_command driver)."""
    upsert_action(ActionSpec(
        id=action_id, label=label, driver="can_command", icon=icon, color=color, category=category,
        params={"channel": CHANNEL, "database_id": db_id, "message": message, "signals": signals},
    ))


def _sel(action_id, label, entry, signals, icon, color, category, mode="set", **extra):
    """A selector that updates a live periodic simulation entry (sim_set driver)."""
    params = {"entry": entry, "signals": signals, "mode": mode}
    params.update(extra)
    upsert_action(ActionSpec(id=action_id, label=label, driver="sim_set",
                             icon=icon, color=color, category=category, params=params))


def load() -> dict:
    """Load the DT15 case study. Idempotent: re-running refreshes it."""
    # 1. The example CAN database.
    with session_scope() as s:
        existing = s.query(CanDatabase).filter_by(name=DB_NAME).first()
        if existing is not None:
            db_id = existing.id
            existing.dbc_text = DBC_TEXT
        else:
            d = dbc_mod.import_dbc(s, name=DB_NAME, dbc_text=DBC_TEXT, source="example",
                                   license="example (not real OEM data)", make="Stellantis",
                                   model="RAM DT", year=2025)
            s.flush()
            db_id = d.id

    # 2. The vehicle profile.
    prof = next((p for p in profiles_svc.list_profiles() if p.get("name") == "DT15"), None)
    if prof is None:
        prof = profiles_svc.create_profile(
            name="DT15", year=2025, make="Stellantis", model="RAM DT",
            vin="1C6RRFFG9SN513894",
            config={"platform": "Atlantis High", "can_interfaces": ["can0", "can1"],
                    "can_database_ids": [db_id], "notes": "Radio + display + instrument cluster on can0."})
    profiles_svc.set_active_profile(prof["id"])

    # 3. The instrument-cluster simulation: periodic vehicle-state broadcast the
    #    real cluster reads. The selectors below update these entries live.
    _seed_sim(db_id)

    # 4. The keys.
    _seed_actions(db_id)

    # 5. The layout on the Stream Deck and start menu.
    _seed_layout()

    # 6. Save the whole setup into the profile so it is recallable in one click.
    from ..services import profile_bundle
    profile_bundle.capture(prof["id"])

    return {"ok": True, "profile_id": prof["id"], "database_id": db_id,
            "message": "DT15 loaded. Open the Layout, CAN, and Simulate pages to drive it."}


def _seed_sim(db_id: int) -> None:
    wanted = {
        "Speed": {"arbitration_id": hex(SPEED), "message": "VehicleSpeed", "signals": {"Speed": 0}, "period_ms": 100},
        "Gear": {"arbitration_id": hex(TRANS), "message": "Transmission", "signals": {"Gear": 0}, "period_ms": 100},
        "Ignition": {"arbitration_id": hex(IGN), "message": "IgnitionStatus", "signals": {"IgnState": 2}, "period_ms": 200},
        "Cluster Engine": {"arbitration_id": hex(CL_ENGINE), "message": "Cluster_Engine", "signals": {"EngineRPM": 750}, "period_ms": 100},
        "Cluster Status": {"arbitration_id": hex(CL_STATUS), "message": "Cluster_Status",
                           "signals": {"FuelLevel": 75, "CoolantTemp": 90}, "period_ms": 200},
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
    # Media / ICS (momentary commands to the radio).
    media = [("media_playpause", "Play/Pause", 1, "bi-play-fill"), ("media_prev", "Prev", 3, "bi-skip-start-fill"),
             ("media_next", "Next", 2, "bi-skip-end-fill"), ("media_voldown", "Vol -", 5, "bi-volume-down"),
             ("media_volup", "Vol +", 4, "bi-volume-up"), ("media_mute", "Mute", 6, "bi-volume-mute"),
             ("media_source", "Source", 7, "bi-music-note-list"), ("media_power", "Power", 8, "bi-power")]
    for aid, label, code, icon in media:
        _cmd(aid, label, "ICS_Command", {"ICS_MediaCmd": code, "ICS_Volume": 0, "ICS_Source": 0}, icon, "#1d4ed8", "Media", db_id)

    # Steering-wheel media controls.
    swc = [("swc_volup", "SWC Vol +", 1, "bi-volume-up"), ("swc_voldown", "SWC Vol -", 2, "bi-volume-down"),
           ("swc_next", "SWC Next", 3, "bi-skip-end"), ("swc_prev", "SWC Prev", 4, "bi-skip-start"),
           ("swc_mode", "SWC Mode", 5, "bi-arrow-repeat"), ("swc_voice", "SWC Voice", 6, "bi-mic"),
           ("swc_mute", "SWC Mute", 7, "bi-volume-mute")]
    for aid, label, code, icon in swc:
        _cmd(aid, label, "SWC_Media", {"SWC_Button": code}, icon, "#7c3aed", "Steering wheel", db_id)

    # Adjustable speed.
    for aid, label, val in [("speed_0", "0", 0), ("speed_30", "30", 30), ("speed_60", "60", 60), ("speed_100", "100", 100)]:
        _sel(aid, f"Speed {label}", "Speed", {"Speed": val}, "bi-speedometer2", "#0e7490", "Speed")
    _sel("speed_up", "Speed +5", "Speed", {"Speed": 5}, "bi-plus-lg", "#0e7490", "Speed", mode="add", min=0, max=250)
    _sel("speed_down", "Speed -5", "Speed", {"Speed": -5}, "bi-dash-lg", "#0e7490", "Speed", mode="add", min=0, max=250)

    # PNDL selector.
    for aid, label, val, icon in [("gear_p", "P", 0, "bi-p-circle"), ("gear_r", "R", 1, "bi-arrow-counterclockwise"),
                                  ("gear_n", "N", 2, "bi-n-circle"), ("gear_d", "D", 3, "bi-arrow-up-circle"),
                                  ("gear_l", "L", 4, "bi-arrow-down-circle")]:
        _sel(aid, label, "Gear", {"Gear": val}, icon, "#b45309", "Gear")

    # Ignition selector.
    for aid, label, val, icon in [("ign_off", "Off", 0, "bi-power"), ("ign_accy", "Accy", 1, "bi-music-player"),
                                  ("ign_run", "Run", 2, "bi-check-circle"), ("ign_start", "Start", 3, "bi-lightning-charge-fill")]:
        _sel(aid, f"Ign {label}", "Ignition", {"IgnState": val}, icon, "#166534", "Ignition")


def _seed_layout() -> None:
    deck = ["media_playpause", "media_prev", "media_next", "media_voldown", "media_volup",
            "gear_p", "gear_r", "gear_n", "gear_d", "ign_off",
            "ign_run", "speed_0", "speed_60", "speed_down", "speed_up"]
    start = deck + ["media_mute", "media_source", "media_power", "gear_l", "ign_accy", "ign_start",
                    "speed_30", "speed_100", "swc_volup", "swc_voldown", "swc_next", "swc_prev",
                    "swc_mode", "swc_voice", "swc_mute"]
    layout_svc.set_layout("streamdeck", deck)
    layout_svc.set_layout("start", start)
