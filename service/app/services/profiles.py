"""Vehicle profile CRUD and the active-profile selection.

A profile ties a saved config (CAN interfaces, linked CAN databases, transmit
lists) to a vehicle: year, make, model, and one or more VINs. Profiles are
DB-backed rows (``db.models.Profile``); which one is "active" (the vehicle
currently being worked on) is a small piece of cross-surface state, so it is
kept the same way the layout and scanner mode are: a single atomic JSON file
under data_dir (see ``services/state.py``), not a database column.

``config`` on a profile is a passthrough JSON blob with a few well-known
keys that callers may set:

- ``can_interfaces``: list of interface names (e.g. ``["can0", "can1"]``).
- ``can_database_ids``: list of ``CanDatabase.id`` values linked to this
  vehicle.
- ``vins``: list of VIN strings for this profile (a fleet vehicle, a
  multi-VIN test rig). The primary VIN also lives on ``Profile.vin``.
- ``tx_lists``: any transmit-list definitions a caller wants to store;
  passed through unmodified.

Nothing here validates those keys beyond normalizing ``vins``, so new config
shapes never require a schema change.
"""
from __future__ import annotations

from ..config import settings
from ..db import Profile, session_scope
from .state import StateFile


def _active_store() -> StateFile:
    return StateFile(settings.data_dir / "active-profile.json", default={"profile_id": None})


# The default set of control slots every vehicle starts with, covering the
# common use cases. Slots stay empty until mapped from the Signal Finder, the
# command library, or a manual entry. Grouped for display.
DEFAULT_CONTROL_SLOTS: list[dict] = [
    {"slot": "lock", "label": "Lock doors", "group": "Doors"},
    {"slot": "unlock", "label": "Unlock doors", "group": "Doors"},
    {"slot": "trunk", "label": "Trunk / tailgate", "group": "Doors"},
    {"slot": "window_up", "label": "Windows up", "group": "Windows"},
    {"slot": "window_down", "label": "Windows down", "group": "Windows"},
    {"slot": "headlights", "label": "Headlights", "group": "Lights"},
    {"slot": "high_beams", "label": "High beams", "group": "Lights"},
    {"slot": "fog_lights", "label": "Fog lights", "group": "Lights"},
    {"slot": "hazards", "label": "Hazards", "group": "Lights"},
    {"slot": "interior_light", "label": "Interior light", "group": "Lights"},
    {"slot": "horn", "label": "Horn", "group": "Body"},
    {"slot": "mirror_fold", "label": "Fold mirrors", "group": "Body"},
    {"slot": "remote_start", "label": "Remote start", "group": "Body"},
    {"slot": "climate_toggle", "label": "Climate on/off", "group": "Climate"},
    {"slot": "fan_up", "label": "Fan up", "group": "Climate"},
    {"slot": "fan_down", "label": "Fan down", "group": "Climate"},
    {"slot": "defrost", "label": "Defrost", "group": "Climate"},
    {"slot": "mute", "label": "Mute", "group": "Media"},
    {"slot": "volume_up", "label": "Volume up", "group": "Media"},
    {"slot": "volume_down", "label": "Volume down", "group": "Media"},
]


def get_controls(profile_id: int) -> list[dict] | None:
    """The vehicle's control slots: the default template merged with whatever is
    mapped in the profile config, plus any extra custom slots the user added.
    Each entry is {slot, label, group, command|None, source}. None if the vehicle
    does not exist."""
    profile = get_profile(profile_id)
    if profile is None:
        return None
    mapped = (profile.get("config") or {}).get("controls") or {}
    out: list[dict] = []
    seen: set[str] = set()
    for tmpl in DEFAULT_CONTROL_SLOTS:
        slot = tmpl["slot"]
        seen.add(slot)
        entry = mapped.get(slot) or {}
        out.append({"slot": slot, "label": entry.get("label") or tmpl["label"],
                    "group": tmpl["group"], "command": entry.get("command"),
                    "source": entry.get("source")})
    # Custom slots the user added beyond the template.
    for slot, entry in mapped.items():
        if slot in seen:
            continue
        out.append({"slot": slot, "label": entry.get("label") or slot,
                    "group": entry.get("group") or "Custom",
                    "command": entry.get("command"), "source": entry.get("source")})
    return out


def set_control(profile_id: int, slot: str, command: dict | None,
                label: str = "", source: str = "manual") -> list[dict] | None:
    """Map a command onto a control slot (or update its label). Returns the new
    control list, or None if the vehicle does not exist."""
    from .command_library import normalize_command
    slot = (slot or "").strip()
    if not slot:
        return get_controls(profile_id)
    with session_scope() as s:
        p = s.get(Profile, profile_id)
        if p is None:
            return None
        cfg = dict(p.config or {})
        controls = dict(cfg.get("controls") or {})
        entry = dict(controls.get(slot) or {})
        if command is not None:
            entry["command"] = normalize_command(command)
            entry["source"] = source
        if label:
            entry["label"] = label
        controls[slot] = entry
        cfg["controls"] = controls
        p.config = cfg
        s.flush()
    return get_controls(profile_id)


def clear_control(profile_id: int, slot: str) -> list[dict] | None:
    """Remove the mapping from a slot (a template slot goes back to empty; a
    custom slot is deleted). Returns the new control list, or None if missing."""
    with session_scope() as s:
        p = s.get(Profile, profile_id)
        if p is None:
            return None
        cfg = dict(p.config or {})
        controls = dict(cfg.get("controls") or {})
        if slot in controls:
            del controls[slot]
            cfg["controls"] = controls
            p.config = cfg
            s.flush()
    return get_controls(profile_id)


def profile_label(profile: dict | None) -> str:
    """A short human label for a vehicle: its name, else year/make/model, else
    a numbered fallback. Shared by the persistent selector and the pages."""
    if not profile:
        return ""
    name = (profile.get("name") or "").strip()
    if name:
        return name
    parts = [str(profile.get("year") or "").strip(),
             (profile.get("make") or "").strip(),
             (profile.get("model") or "").strip()]
    label = " ".join(p for p in parts if p)
    return label or f"Vehicle {profile.get('id')}"


def list_profiles() -> list[dict]:
    with session_scope() as s:
        return [p.to_dict() for p in s.query(Profile).order_by(Profile.id).all()]


def get_profile(profile_id: int) -> dict | None:
    with session_scope() as s:
        p = s.get(Profile, profile_id)
        return p.to_dict() if p is not None else None


def _normalize_config(config: dict | None, vin: str, vins: list[str] | None) -> dict:
    """Fold the primary VIN and any extra VINs into a single ``vins`` list."""
    cfg = dict(config or {})
    existing = cfg.get("vins")
    merged = list(existing) if isinstance(existing, list) else []
    if vins:
        merged.extend(vins)
    if vin and vin not in merged:
        merged.insert(0, vin)
    # De-duplicate while keeping order.
    seen: set[str] = set()
    ordered = []
    for v in merged:
        if v and v not in seen:
            seen.add(v)
            ordered.append(v)
    cfg["vins"] = ordered
    return cfg


def create_profile(
    name: str = "", year: int | None = None, make: str = "", model: str = "", vin: str = "",
    config: dict | None = None, vins: list[str] | None = None,
) -> dict:
    cfg = _normalize_config(config, vin, vins)
    with session_scope() as s:
        p = Profile(name=name, year=year, make=make, model=model, vin=vin, config=cfg)
        s.add(p)
        s.flush()
        return p.to_dict()


def copy_profile(profile_id: int, new_name: str = "") -> dict | None:
    """Duplicate a vehicle profile into a new one, carrying over its whole config
    (linked databases, transmit lists, mapped controls). VINs are not copied
    since they are unique to a physical vehicle. Returns the new profile, or None
    if the source does not exist."""
    with session_scope() as s:
        src = s.get(Profile, profile_id)
        if src is None:
            return None
        cfg = dict(src.config or {})
        cfg.pop("vins", None)  # VINs are per-vehicle; do not clone them
        name = (new_name or "").strip() or f"{src.name or profile_label(src.to_dict())} (copy)"
        p = Profile(name=name, year=src.year, make=src.make, model=src.model, vin="", config=cfg)
        s.add(p)
        s.flush()
        return p.to_dict()


def update_profile(profile_id: int, **fields) -> dict | None:
    """Apply only the fields that were actually passed (partial update)."""
    vin_update = "vin" in fields
    vins_update = fields.pop("vins", None)
    with session_scope() as s:
        p = s.get(Profile, profile_id)
        if p is None:
            return None
        for key in ("name", "year", "make", "model", "vin"):
            if key in fields and fields[key] is not None:
                setattr(p, key, fields[key])
        if "config" in fields and fields["config"] is not None:
            # Merge rather than replace, so a partial update (e.g. only
            # can_interfaces from the UI form) never wipes other passthrough
            # keys (can_database_ids, tx_lists, notes) already on the row.
            merged = dict(p.config or {})
            merged.update(fields["config"])
            p.config = merged
        if vins_update is not None or vin_update:
            p.config = _normalize_config(
                p.config, p.vin if vin_update else "", vins_update)
        s.flush()
        return p.to_dict()


def delete_profile(profile_id: int) -> bool:
    with session_scope() as s:
        p = s.get(Profile, profile_id)
        if p is None:
            return False
        s.delete(p)
    # Clear the active selection if it pointed at the profile we just removed.
    store = _active_store()
    doc = store.read()
    if doc.get("profile_id") == profile_id:
        doc["profile_id"] = None
        store.write(doc)
    return True


def get_active_profile_id() -> int | None:
    return _active_store().read().get("profile_id")


def set_active_profile(profile_id: int | None) -> dict | None:
    """Select a profile as active, or clear the selection with ``None``.

    Returns the newly active profile (or ``None`` when clearing), and raises
    ``ValueError`` if ``profile_id`` does not name an existing profile.
    """
    if profile_id is None:
        _active_store().write({"profile_id": None})
        return None
    profile = get_profile(profile_id)
    if profile is None:
        raise ValueError(f"No such profile: {profile_id}")
    _active_store().write({"profile_id": profile_id})
    return profile
