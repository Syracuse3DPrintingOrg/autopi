"""Save a vehicle's whole test bench into its profile, and recall it in one step.

A profile bundle is a complete snapshot: the CAN databases, the action library
(all your keys), the Stream Deck / start layout, and the simulation transmit
list. Capturing it stores that snapshot against the profile; applying it
restores the lot, so switching vehicles reloads that vehicle's entire setup.

Databases are matched by name on apply and their ids remapped, so an action or
simulation entry that referenced a database keeps pointing at the right one even
if its row id differs on this device.
"""
from __future__ import annotations

from typing import Any

from ..actions.registry import ActionSpec, save_user_actions, user_actions
from ..can import dbc as dbc_mod
from ..can import simulation
from ..db import CanDatabase, session_scope
from ..services import layout as layout_svc
from ..services import profiles as profiles_svc
from ..services.state import StateFile
from ..config import settings


def _store() -> StateFile:
    return StateFile(settings.data_dir / "profile_bundles.json", default={"bundles": {}})


def has_bundle(profile_id: int) -> bool:
    return str(profile_id) in _store().read().get("bundles", {})


def store_bundle(profile_id: int, bundle: dict) -> None:
    """Save a bundle (e.g. one pulled from a sync server) as this profile's
    saved setup, without applying it. ``capture`` is the same operation for a
    bundle built from this device's current setup; ``apply`` restores whatever
    was last stored here, from either source."""
    store = _store()
    doc = store.read()
    doc.setdefault("bundles", {})[str(profile_id)] = bundle
    store.write(doc)


def _export_databases() -> list[dict[str, Any]]:
    with session_scope() as s:
        return [{"old_id": d.id, "name": d.name, "source": d.source, "license": d.license,
                 "make": d.make, "model": d.model, "year": d.year, "dbc_text": d.dbc_text or ""}
                for d in s.query(CanDatabase).all()]


def capture(profile_id: int) -> dict:
    """Snapshot the current setup into the given profile's bundle."""
    bundle = {
        "databases": _export_databases(),
        "actions": [a.to_dict() for a in user_actions().values()],
        "layout": layout_svc.get_all(),
        "simulation": simulation.list_entries(),
    }
    store_bundle(profile_id, bundle)
    return {"ok": True, "counts": {
        "databases": len(bundle["databases"]), "actions": len(bundle["actions"]),
        "simulation": len(bundle["simulation"])}}


def _restore_database(session, cap: dict) -> int:
    existing = session.query(CanDatabase).filter_by(name=cap["name"]).first()
    if existing is not None:
        existing.dbc_text = cap.get("dbc_text") or existing.dbc_text
        session.flush()
        return existing.id
    d = dbc_mod.import_dbc(session, name=cap["name"], dbc_text=cap.get("dbc_text") or "",
                          source=cap.get("source", "bundle"), license=cap.get("license", ""),
                          make=cap.get("make", ""), model=cap.get("model", ""), year=cap.get("year"))
    session.flush()
    return d.id


def _remap(obj: dict, id_map: dict[int, int]) -> dict:
    out = dict(obj)
    params = out.get("params")
    if isinstance(params, dict) and params.get("database_id") in id_map:
        params = dict(params)
        params["database_id"] = id_map[params["database_id"]]
        out["params"] = params
    if out.get("database_id") in id_map:
        out["database_id"] = id_map[out["database_id"]]
    return out


def apply(profile_id: int) -> dict:
    """Restore a profile's bundle: databases, actions, layout, and simulation."""
    bundle = _store().read().get("bundles", {}).get(str(profile_id))
    if bundle is None:
        return {"ok": False, "error": "This profile has no saved setup to recall."}

    id_map: dict[int, int] = {}
    with session_scope() as s:
        for cap in bundle.get("databases", []):
            id_map[cap["old_id"]] = _restore_database(s, cap)

    # Actions: remap database ids, then replace the user action set.
    specs = [ActionSpec.from_dict(_remap(a, id_map)) for a in bundle.get("actions", [])]
    save_user_actions(specs)

    # Layout.
    for surface, slots in (bundle.get("layout") or {}).items():
        if surface in layout_svc.SURFACES:
            layout_svc.set_layout(surface, slots)

    # Simulation: clear and restore, remapping database ids.
    for entry in list(simulation.list_entries()):
        simulation.delete_entry(entry["id"])
    for entry in bundle.get("simulation", []):
        simulation.create_entry(_remap(entry, id_map))

    profiles_svc.set_active_profile(profile_id)
    return {"ok": True, "message": "Recalled this vehicle's saved setup."}
