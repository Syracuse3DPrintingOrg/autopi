"""Vehicle-to-database matching and the open-source catalog invariants."""
from __future__ import annotations

from app.services import dbc_catalog


def test_blank_database_matches_any_vehicle():
    generic = {"make": "", "model": "", "models": "", "year": None, "years": ""}
    assert dbc_catalog.database_matches(generic, "Toyota", "Corolla", 2020)


def test_make_model_year_matching():
    toyota = {"make": "Toyota", "model": "Corolla", "models": "", "year": None, "years": "2018-2022"}
    assert dbc_catalog.database_matches(toyota, "Toyota", "Corolla", 2020)
    assert dbc_catalog.database_matches(toyota, "Toyota", "", None)          # partial vehicle info
    assert not dbc_catalog.database_matches(toyota, "Honda", "Civic", 2020)  # make mismatch
    assert not dbc_catalog.database_matches(toyota, "Toyota", "Corolla", 2025)  # year out of range


def test_multi_model_field_matches_any_listed_model():
    db = {"make": "Hyundai", "model": "", "models": "Elantra, Sonata, Kona", "year": None, "years": ""}
    assert dbc_catalog.database_matches(db, "Hyundai", "Sonata", None)
    assert not dbc_catalog.database_matches(db, "Hyundai", "Palisade", None)


def test_compatible_databases_orders_specific_first():
    dbs = [
        {"id": 1, "make": "", "model": "", "models": "", "year": None, "years": ""},
        {"id": 2, "make": "Toyota", "model": "Corolla", "models": "", "year": 2020, "years": ""},
    ]
    out = dbc_catalog.compatible_databases(dbs, "Toyota", "Corolla", 2020)
    assert [d["id"] for d in out] == [2, 1]


def test_only_permissive_catalog_entries_are_importable():
    # We may only fetch/ship permissively-licensed content directly.
    for entry in dbc_catalog.catalog():
        if entry.get("importable"):
            lic = (entry.get("license") or "").lower()
            assert any(t in lic for t in ("mit", "cc0", "bsd", "apache", "public")), entry["name"]
            assert entry.get("import_url"), entry["name"]


def test_every_catalog_entry_keeps_the_shape():
    required = {"name", "make", "models", "years", "author", "license", "homepage",
                "import_url", "importable"}
    for entry in dbc_catalog.catalog():
        missing = required - set(entry)
        assert not missing, f"{entry.get('name')} missing {missing}"
        assert isinstance(entry["models"], list), entry["name"]
        assert entry["homepage"].startswith("http"), entry["name"]


def test_catalog_carries_the_awesome_can_id_community_entries():
    names = [e["name"] for e in dbc_catalog.catalog()]
    assert any("awesome-automotive-can-id" in n for n in names)
    makes = {e["make"] for e in dbc_catalog.catalog()}
    # Coverage grew beyond the original opendbc trio.
    for make in ("Tesla", "Nissan", "Ford", "BMW"):
        assert make in makes, make


def test_community_reference_entries_are_link_only():
    # Anything without a clearly permissive license must not be importable.
    for entry in dbc_catalog.catalog():
        lic = (entry.get("license") or "").lower()
        permissive = any(t in lic for t in ("mit", "cc0", "bsd", "apache", "public"))
        if not permissive:
            assert not entry.get("importable"), entry["name"]
            assert entry.get("import_url") is None, entry["name"]
