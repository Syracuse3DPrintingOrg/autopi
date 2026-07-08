"""Tests for vehicle test profiles: the service, the seed, and the router."""
import pytest
from starlette.testclient import TestClient

from app.db import init_db, session_scope
from app.db.models import Profile
from app.main import app
from app.services import profiles as profiles_svc
from app.services.seed_profiles import seed_profiles_if_empty


@pytest.fixture(autouse=True)
def _tables(temp_data_dir):
    """Create the (fresh, per-test) SQLite tables the service-level tests need.

    The router tests get this for free through TestClient's app lifespan; the
    direct service-level calls below bypass the app, so they need the tables
    created explicitly.
    """
    init_db()


def _client():
    return TestClient(app)


# --- Service: CRUD and VIN handling -----------------------------------------


def test_create_profile_stores_primary_vin_in_vins_list():
    profile = profiles_svc.create_profile(
        name="Track car", year=2018, make="Mazda", model="MX-5", vin="JM1ND2W37Z0123456")
    assert profile["vin"] == "JM1ND2W37Z0123456"
    assert profile["config"]["vins"] == ["JM1ND2W37Z0123456"]


def test_create_profile_supports_multiple_vins():
    profile = profiles_svc.create_profile(
        name="Fleet A", year=2023, make="Stellantis", model="Atlantis High",
        vin="1C4RJFAG0MC000001", vins=["1C4RJFAG0MC000002", "1C4RJFAG0MC000003"])
    assert profile["config"]["vins"] == [
        "1C4RJFAG0MC000001", "1C4RJFAG0MC000002", "1C4RJFAG0MC000003"]


def test_create_profile_deduplicates_vins():
    profile = profiles_svc.create_profile(
        name="Dup test", vin="VIN1", vins=["VIN1", "VIN2", "VIN1"])
    assert profile["config"]["vins"] == ["VIN1", "VIN2"]


def test_update_profile_partial_fields_only():
    profile = profiles_svc.create_profile(name="Original", year=2020, make="Honda", model="Civic")
    updated = profiles_svc.update_profile(profile["id"], name="Renamed")
    assert updated["name"] == "Renamed"
    assert updated["year"] == 2020
    assert updated["make"] == "Honda"


def test_update_profile_config_merges_not_replaces():
    profile = profiles_svc.create_profile(
        name="Rig", config={"can_interfaces": ["can0"], "notes": "keep me"})
    updated = profiles_svc.update_profile(profile["id"], config={"can_interfaces": ["can0", "can1"]})
    assert updated["config"]["can_interfaces"] == ["can0", "can1"]
    assert updated["config"]["notes"] == "keep me"


def test_update_profile_unknown_id_returns_none():
    assert profiles_svc.update_profile(999999, name="Nope") is None


def test_delete_profile_clears_active_selection():
    profile = profiles_svc.create_profile(name="Temp")
    profiles_svc.set_active_profile(profile["id"])
    assert profiles_svc.get_active_profile_id() == profile["id"]

    assert profiles_svc.delete_profile(profile["id"]) is True
    assert profiles_svc.get_active_profile_id() is None


def test_delete_unknown_profile_returns_false():
    assert profiles_svc.delete_profile(999999) is False


def test_set_active_profile_unknown_id_raises():
    import pytest
    with pytest.raises(ValueError):
        profiles_svc.set_active_profile(999999)


def test_set_active_profile_none_clears_selection():
    profile = profiles_svc.create_profile(name="Whatever")
    profiles_svc.set_active_profile(profile["id"])
    profiles_svc.set_active_profile(None)
    assert profiles_svc.get_active_profile_id() is None


# --- Seed: Atlantis High and Atlantis Mid, idempotent ----------------------


def test_seed_profiles_creates_atlantis_high_and_mid():
    assert seed_profiles_if_empty() is True
    names = {p["name"] for p in profiles_svc.list_profiles()}
    assert names == {"Atlantis High", "Atlantis Mid"}


def test_seed_profiles_sets_stellantis_make_and_infotainment_notes():
    seed_profiles_if_empty()
    profiles = {p["name"]: p for p in profiles_svc.list_profiles()}
    for name in ("Atlantis High", "Atlantis Mid"):
        p = profiles[name]
        assert p["make"] == "Stellantis"
        assert p["model"] == name
        assert "infotainment" in p["config"]["notes"].lower()
        assert p["config"]["can_interfaces"]


def test_seed_profiles_skips_when_a_profile_already_exists():
    profiles_svc.create_profile(name="My own car")
    assert seed_profiles_if_empty() is False
    names = {p["name"] for p in profiles_svc.list_profiles()}
    assert names == {"My own car"}


def test_seed_profiles_never_overwrites_existing_rows():
    with session_scope() as s:
        s.add(Profile(name="Existing", make="Toyota"))
    seed_profiles_if_empty()
    names = {p["name"] for p in profiles_svc.list_profiles()}
    assert names == {"Existing"}


# --- Router: end-to-end through a real TestClient ---------------------------


def test_router_create_list_get_roundtrip():
    with _client() as c:
        created = c.post("/profiles", json={
            "name": "Daily driver", "year": 2019, "make": "Subaru", "model": "Outback",
            "vin": "4S4BSANC1K3000001",
        }).json()
        assert created["id"] is not None

        listing = c.get("/profiles").json()
        assert any(p["id"] == created["id"] for p in listing["profiles"])

        fetched = c.get(f"/profiles/{created['id']}").json()
        assert fetched["name"] == "Daily driver"


def test_router_get_unknown_profile_is_404():
    with _client() as c:
        resp = c.get("/profiles/999999")
    assert resp.status_code == 404


def test_router_update_profile():
    with _client() as c:
        created = c.post("/profiles", json={"name": "Before"}).json()
        resp = c.put(f"/profiles/{created['id']}", json={"name": "After"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "After"


def test_router_update_unknown_profile_is_404():
    with _client() as c:
        resp = c.put("/profiles/999999", json={"name": "Nope"})
    assert resp.status_code == 404


def test_router_delete_profile():
    with _client() as c:
        created = c.post("/profiles", json={"name": "Delete me"}).json()
        resp = c.delete(f"/profiles/{created['id']}")
        assert resp.status_code == 200
        assert c.get(f"/profiles/{created['id']}").status_code == 404


def test_router_delete_unknown_profile_is_404():
    with _client() as c:
        resp = c.delete("/profiles/999999")
    assert resp.status_code == 404


def test_router_set_and_get_active_profile():
    with _client() as c:
        created = c.post("/profiles", json={"name": "Active candidate"}).json()
        resp = c.post("/profiles/active", json={"profile_id": created["id"]})
        assert resp.status_code == 200
        assert resp.json()["active_id"] == created["id"]

        active = c.get("/profiles/active").json()
        assert active["active_id"] == created["id"]
        assert active["profile"]["name"] == "Active candidate"


def test_router_set_active_unknown_profile_is_404():
    with _client() as c:
        resp = c.post("/profiles/active", json={"profile_id": 999999})
    assert resp.status_code == 404


def test_router_clear_active_profile():
    with _client() as c:
        created = c.post("/profiles", json={"name": "Was active"}).json()
        c.post("/profiles/active", json={"profile_id": created["id"]})
        c.post("/profiles/active", json={"profile_id": None})
        active = c.get("/profiles/active").json()
        assert active["active_id"] is None
        assert active["profile"] is None


def test_router_multiple_vins_via_api():
    with _client() as c:
        created = c.post("/profiles", json={
            "name": "Multi-VIN rig", "vin": "VIN-A", "vins": ["VIN-B", "VIN-C"],
        }).json()
        assert created["config"]["vins"] == ["VIN-A", "VIN-B", "VIN-C"]


def test_ui_profiles_page_renders():
    with _client() as c:
        resp = c.get("/ui/profiles")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
