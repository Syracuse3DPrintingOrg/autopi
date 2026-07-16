"""Active-vehicle database matching and decode preference (AutoPi-tlr)."""
import pytest
from starlette.testclient import TestClient

from app.db import init_db
from app.main import app
from app.services import can_databases as can_db_svc
from app.services import dbc_catalog


# --- pure helpers ----------------------------------------------------------

def test_pick_active_database_id_takes_first_linked_that_exists():
    assert dbc_catalog.pick_active_database_id([3, 1, 2], [1, 2]) == 1
    assert dbc_catalog.pick_active_database_id([9], [1, 2]) is None
    assert dbc_catalog.pick_active_database_id([], [1, 2]) is None
    # Junk ids are skipped, not fatal.
    assert dbc_catalog.pick_active_database_id(["x", 2], [2]) == 2


def test_annotate_matches_flags_only_fitting_entries():
    entries = [
        {"name": "Civic", "make": "Honda", "models": ["Civic"], "years": "2016-2020"},
        {"name": "Camry", "make": "Toyota", "models": ["Camry"], "years": "2018+"},
    ]
    out = dbc_catalog.annotate_matches(entries, "Honda", "Civic", 2018)
    assert out[0]["matches"] is True
    assert out[1]["matches"] is False
    # Originals untouched (defensive copy).
    assert "matches" not in entries[0]


def test_annotate_matches_flags_nothing_without_a_vehicle():
    entries = [{"name": "Civic", "make": "Honda", "models": ["Civic"]}]
    assert dbc_catalog.annotate_matches(entries)[0]["matches"] is False


def test_database_matches_handles_list_models_from_catalog():
    entry = {"make": "Toyota", "models": ["Corolla", "RAV4"], "years": "2015+"}
    assert dbc_catalog.database_matches(entry, "Toyota", "RAV4", 2020) is True
    assert dbc_catalog.database_matches(entry, "Toyota", "Tacoma", 2020) is False


# --- service + API ---------------------------------------------------------

@pytest.fixture(autouse=True)
def _tables(temp_data_dir):
    init_db()


def _client():
    return TestClient(app)


def _make_db(client, name="DBC", **meta):
    return client.post("/can/databases", json={"name": name, **meta}).json()["database"]


def _make_vehicle(client, **fields):
    body = {"name": "Bench", "make": "Honda", "model": "Civic", "year": 2018}
    body.update(fields)
    return client.post("/profiles", json=body).json()


def test_active_database_prefers_linked_of_active_vehicle():
    with _client() as client:
        db = _make_db(client, make="Honda", models="Civic")
        vehicle = _make_vehicle(client)
        client.post(f"/can/databases/{db['id']}/link", json={"profile_id": vehicle["id"]})
        client.post("/profiles/active", json={"profile_id": vehicle["id"]})
        assert can_db_svc.active_database_id() == db["id"]
        resp = client.get("/can/databases/active").json()
        assert resp["database_id"] == db["id"]
        assert resp["database"]["name"] == "DBC"


def test_active_database_is_none_with_no_active_vehicle():
    with _client() as client:
        _make_db(client)
        assert can_db_svc.active_database_id() is None
        assert client.get("/can/databases/active").json()["database_id"] is None


def test_list_databases_flags_matches_and_linked_for_active_vehicle():
    with _client() as client:
        match_db = _make_db(client, name="Fits", make="Honda", models="Civic", years="2016-2020")
        other_db = _make_db(client, name="Other", make="Toyota", models="Camry")
        vehicle = _make_vehicle(client)
        client.post(f"/can/databases/{match_db['id']}/link", json={"profile_id": vehicle["id"]})
        client.post("/profiles/active", json={"profile_id": vehicle["id"]})
        dbs = {d["name"]: d for d in client.get("/can/databases").json()["databases"]}
        assert dbs["Fits"]["matches"] is True and dbs["Fits"]["linked"] is True
        assert dbs["Other"]["matches"] is False and dbs["Other"]["linked"] is False


def test_catalog_flags_matches_for_active_vehicle():
    with _client() as client:
        vehicle = _make_vehicle(client, make="Toyota", model="Corolla", year=2020)
        client.post("/profiles/active", json={"profile_id": vehicle["id"]})
        catalog = client.get("/can/dbc/catalog").json()["catalog"]
        toyota = next(e for e in catalog if e["make"] == "Toyota")
        assert toyota["matches"] is True
        honda = next(e for e in catalog if e["make"] == "Honda")
        assert honda["matches"] is False


def test_monitor_frames_decode_falls_back_to_active_database(monkeypatch):
    # The Monitor decodes with the active vehicle's linked database even when the
    # request names no database. Stub decode so the test needs no cantools.
    import app.routers.can_monitor as cm
    from app.can import monitor as mon
    from app.can.base import Frame

    seen = {}

    def fake_decode(record, dbc_text, obd2_overlay=False):
        seen["dbc_text"] = dbc_text
        return {"stub": True}

    monkeypatch.setattr(cm, "decode_record", fake_decode)
    mon.reset_monitors()

    with _client() as client:
        db = _make_db(client, make="Honda", models="Civic")
        from app.db import CanDatabase, session_scope
        with session_scope() as s:
            s.get(CanDatabase, db["id"]).dbc_text = 'VERSION ""\n'
        vehicle = _make_vehicle(client)
        client.post(f"/can/databases/{db['id']}/link", json={"profile_id": vehicle["id"]})
        client.post("/profiles/active", json={"profile_id": vehicle["id"]})

        # Seed one frame into the monitor ring buffer without hardware.
        m = mon.get_monitor("can0", backend="socketcan")
        mon.ingest_frame(m._buffer, m._counts, Frame(arbitration_id=0x100, data=[1, 2]), timestamp=1.0)

        body = client.get("/can/monitor/frames?channel=can0&backend=socketcan&obd2=0").json()
        assert body["frames"], "expected the seeded frame back"
        # Decode ran against the active vehicle's linked DBC, with no database_id.
        assert seen["dbc_text"] == 'VERSION ""\n'
        assert body["frames"][0]["decoded"] == {"stub": True}

    mon.reset_monitors()


def test_available_ids_returns_only_ids(temp_data_dir):
    # Guard the /frames hot-path optimization: _available_ids must return plain
    # ids (loading only the id column), not whole CanDatabase rows.
    from app.db import init_db, session_scope
    from app.db.models import CanDatabase
    from app.services import can_databases as svc
    init_db()
    with session_scope() as s:
        s.add(CanDatabase(name="One", dbc_text="BO_ 1 M: 8 X\n"))
        s.add(CanDatabase(name="Two", dbc_text="BO_ 2 N: 8 X\n"))
    ids = svc._available_ids()
    assert ids and all(isinstance(i, int) for i in ids)
