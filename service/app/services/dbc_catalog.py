"""Curated catalog of open-source CAN databases, and vehicle matching.

Two jobs:

- A **catalog** of real, open-source DBC sources the user can get. Only
  permissively-licensed content (MIT/CC0) may ever be bundled with the app;
  this catalog additionally lists sources whose license does not let us ship
  them, as link-only entries. ``importable`` means the app can fetch it directly
  (a raw ``.dbc`` URL); otherwise the user follows ``homepage`` to get it. Nothing
  here is a preloaded database, so shipping the software carries no third-party
  DBC content, only pointers to where real databases live.

- **Vehicle matching**: given an installed database's metadata and a vehicle's
  make/model/year, decide (leniently) whether they are compatible, so selecting a
  vehicle can surface the databases that fit it. Pure functions, unit-tested.
"""
from __future__ import annotations

from typing import Any

# Each entry always has a working ``homepage`` link. ``import_url`` is a raw
# ``.dbc`` the app can fetch when ``importable`` is True; the homepage is the
# fallback if a direct import ever fails. Keep this list to genuinely
# open-source sources; a user can always import any other DBC by URL or file.
CATALOG: list[dict[str, Any]] = [
    {
        "name": "opendbc — Toyota / Lexus powertrain",
        "make": "Toyota", "models": ["Corolla", "Camry", "RAV4", "Prius", "Highlander"],
        "years": "2015+", "author": "comma.ai / opendbc community", "license": "MIT",
        "homepage": "https://github.com/commaai/opendbc/tree/master/opendbc/dbc",
        "import_url": "https://raw.githubusercontent.com/commaai/opendbc/master/opendbc/dbc/toyota_nodsu_pt_generated.dbc",
        "importable": True,
    },
    {
        "name": "opendbc — Honda / Acura powertrain",
        "make": "Honda", "models": ["Civic", "Accord", "CR-V"],
        "years": "2016+", "author": "comma.ai / opendbc community", "license": "MIT",
        "homepage": "https://github.com/commaai/opendbc/tree/master/opendbc/dbc",
        "import_url": "https://raw.githubusercontent.com/commaai/opendbc/master/opendbc/dbc/honda_civic_touring_2016_can_generated.dbc",
        "importable": True,
    },
    {
        "name": "opendbc — Hyundai / Kia generic",
        "make": "Hyundai", "models": ["Elantra", "Sonata", "Kona"],
        "years": "2015+", "author": "comma.ai / opendbc community", "license": "MIT",
        "homepage": "https://github.com/commaai/opendbc/tree/master/opendbc/dbc",
        "import_url": "https://raw.githubusercontent.com/commaai/opendbc/master/opendbc/dbc/hyundai_kia_generic.dbc",
        "importable": True,
    },
    {
        "name": "opendbc — full library (all brands)",
        "make": "", "models": [], "years": "", "author": "comma.ai / opendbc community",
        "license": "MIT",
        "homepage": "https://github.com/commaai/opendbc/tree/master/opendbc/dbc",
        "import_url": None, "importable": False,
        "notes": "Browse the full MIT-licensed DBC set and import a specific file by its raw URL below.",
    },
    {
        "name": "OBD2 standard PIDs (speed, RPM, coolant, ...)",
        "make": "", "models": [], "years": "", "author": "CSS Electronics",
        "license": "See source",
        "homepage": "https://www.csselectronics.com/pages/obd2-dbc-file",
        "import_url": None, "importable": False,
        "notes": "Generic OBD2 diagnostics, handy as a reference signal. Get it from the source.",
    },
]


def catalog() -> list[dict[str, Any]]:
    """The catalog, defensively copied."""
    return [dict(e) for e in CATALOG]


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _db_models(db: dict) -> list[str]:
    out = [_norm(db.get("model"))]
    raw = db.get("models")
    if isinstance(raw, (list, tuple)):
        # Catalog entries carry ``models`` as a list; installed databases carry
        # a comma-separated string. Handle both so matching works on either.
        out += [_norm(m) for m in raw]
    else:
        out += [_norm(m) for m in str(raw or "").split(",")]
    return [m for m in out if m]


def _year_ok(year: int, db: dict) -> bool:
    """Whether ``year`` falls in the database's single year or ``years`` range.
    A database with no year information matches any year."""
    single = db.get("year")
    years = str(db.get("years") or "").strip()
    if not single and not years:
        return True
    if single and int(single) == int(year):
        return True
    if years:
        # "YYYY+" means that year onward (an open upper bound), the shape the
        # catalog uses ("2015+"); anything at or after the year matches.
        stripped = years.rstrip("+")
        if years.endswith("+") and stripped.isdigit():
            return int(year) >= int(stripped)
        parts = [p.strip() for p in years.replace("–", "-").split("-") if p.strip().isdigit()]
        nums = [int(p) for p in parts]
        if len(nums) == 1 and nums[0] == int(year):
            return True
        if len(nums) >= 2 and min(nums) <= int(year) <= max(nums):
            return True
    return False


def database_matches(db: dict, make: str = "", model: str = "", year: int | None = None) -> bool:
    """Lenient compatibility test between an installed database (its ``to_dict``)
    and a vehicle. A field the database leaves blank never rules it out, so a
    generic database still matches; a field it fills must be consistent with the
    vehicle when the vehicle specifies it."""
    if make and _norm(db.get("make")) and _norm(db.get("make")) != _norm(make):
        return False
    if model:
        models = _db_models(db)
        if models and not any(_norm(model) in m or m in _norm(model) for m in models):
            return False
    if year and not _year_ok(int(year), db):
        return False
    return True


def compatible_databases(dbs: list[dict], make: str = "", model: str = "",
                         year: int | None = None) -> list[dict]:
    """The installed databases compatible with a vehicle, most-specific first (a
    database that names the make and model ranks above a generic one)."""
    matched = [db for db in dbs if database_matches(db, make, model, year)]

    def specificity(db: dict) -> int:
        return (1 if _norm(db.get("make")) else 0) + (1 if _db_models(db) else 0) + (1 if db.get("year") or db.get("years") else 0)

    matched.sort(key=specificity, reverse=True)
    return matched


def pick_active_database_id(linked_ids: list[int], available_ids: list[int]) -> int | None:
    """The database a vehicle should decode with, given its linked ids and the
    ids that actually exist. The first linked database still present wins, so a
    deleted link is skipped without ever falling back to an unrelated database.
    Pure: no DB access."""
    have = {int(i) for i in available_ids}
    for i in linked_ids:
        try:
            i = int(i)
        except (TypeError, ValueError):
            continue
        if i in have:
            return i
    return None


def annotate_matches(entries: list[dict], make: str = "", model: str = "",
                     year: int | None = None) -> list[dict]:
    """Copy each entry and add a ``matches`` flag saying whether it fits the given
    vehicle. With no vehicle (all fields blank) nothing is flagged, so the caller
    can pass an inactive selection through unchanged. Pure: no DB access."""
    has_vehicle = bool(make or model or year)
    out: list[dict] = []
    for e in entries:
        item = dict(e)
        item["matches"] = bool(has_vehicle and database_matches(e, make, model, year))
        out.append(item)
    return out
