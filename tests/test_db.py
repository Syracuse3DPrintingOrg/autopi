"""Unit tests for the database models, import/export, and the router.

The pure import/export logic is tested against an in-memory SQLite session
so it never touches the temp data dir; the router tests go through a real
TestClient with the autouse temp_data_dir fixture (see conftest.py), which
gives each test its own SQLite file under a temp directory.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.testclient import TestClient

from app.db import importexport
from app.db.models import Action, Base, CanMessage, CanSignal, LogicRule, Profile
from app.main import app


def _memory_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_export_all_is_empty_on_a_fresh_database():
    session = _memory_session()
    data = importexport.export_all(session)
    assert data["version"] == importexport.FORMAT_VERSION
    assert data["actions"] == []
    assert data["profiles"] == []
    assert data["can_messages"] == []
    assert data["logic_rules"] == []


def test_import_then_export_roundtrips_an_action():
    session = _memory_session()
    payload = {
        "actions": [{
            "id": "light", "label": "Light", "driver": "gpio",
            "params": {"pin": 17}, "icon": "bi-lightbulb", "color": "#f00",
            "category": "Actions", "members": [], "deck_only": False,
        }],
    }
    counts = importexport.import_data(session, payload)
    session.commit()
    assert counts["actions"] == 1

    data = importexport.export_all(session)
    assert len(data["actions"]) == 1
    assert data["actions"][0]["label"] == "Light"
    assert data["actions"][0]["params"] == {"pin": 17}


def test_import_upserts_an_existing_action_by_id():
    session = _memory_session()
    session.add(Action(id="light", label="Light", driver="gpio", params={"pin": 17}))
    session.commit()

    importexport.import_data(session, {"actions": [
        {"id": "light", "label": "Light (renamed)", "driver": "gpio", "params": {"pin": 18}},
    ]})
    session.commit()

    rows = session.query(Action).all()
    assert len(rows) == 1
    assert rows[0].label == "Light (renamed)"
    assert rows[0].params == {"pin": 18}


def test_import_never_deletes_records_it_does_not_mention():
    session = _memory_session()
    session.add(Action(id="keep-me", label="Keep me", driver="shell", params={}))
    session.commit()

    # An import that only mentions a different action must not touch "keep-me".
    importexport.import_data(session, {"actions": [
        {"id": "other", "label": "Other", "driver": "shell", "params": {}},
    ]})
    session.commit()

    ids = {a.id for a in session.query(Action).all()}
    assert ids == {"keep-me", "other"}


def test_profile_config_roundtrips_arbitrary_json():
    session = _memory_session()
    profile = Profile(name="Daily driver", year=2018, make="Honda", model="Civic",
                       vin="1HGCM82633A004352", config={"gauges": ["rpm", "boost"]})
    session.add(profile)
    session.commit()

    data = importexport.export_all(session)
    assert data["profiles"][0]["config"] == {"gauges": ["rpm", "boost"]}


def test_export_profile_returns_only_that_profile():
    session = _memory_session()
    a = Profile(name="Car A")
    b = Profile(name="Car B")
    session.add_all([a, b])
    session.commit()

    data = importexport.export_profile(session, a.id)
    assert data is not None
    assert len(data["profiles"]) == 1
    assert data["profiles"][0]["name"] == "Car A"
    assert data["actions"] == []


def test_export_profile_missing_id_returns_none():
    session = _memory_session()
    assert importexport.export_profile(session, 999) is None


def test_can_message_with_signals_roundtrips_and_upsert_keeps_existing_signals():
    session = _memory_session()
    msg = CanMessage(arbitration_id=0x123, name="Engine RPM", is_fd=False)
    msg.signals.append(CanSignal(name="rpm", definition={"start_bit": 0, "length": 16}))
    session.add(msg)
    session.commit()

    exported = importexport.export_all(session)
    assert exported["can_messages"][0]["arbitration_id"] == 0x123
    assert len(exported["can_messages"][0]["signals"]) == 1

    # Re-import the same message but only reference it (no signals key): the
    # existing signal must survive, never be wiped.
    importexport.import_data(session, {"can_messages": [
        {"id": exported["can_messages"][0]["id"], "arbitration_id": 0x123, "name": "Engine RPM (v2)"},
    ]})
    session.commit()

    row = session.get(CanMessage, exported["can_messages"][0]["id"])
    assert row.name == "Engine RPM (v2)"
    assert len(row.signals) == 1
    assert row.signals[0].name == "rpm"


def test_logic_rule_definition_roundtrips():
    session = _memory_session()
    session.add(LogicRule(name="Lights off at night", definition={
        "when": {"time_after": "22:00"}, "then": ["screen_off"],
    }))
    session.commit()

    data = importexport.export_all(session)
    assert data["logic_rules"][0]["definition"]["then"] == ["screen_off"]


def test_import_rejects_a_non_object_payload():
    import pytest
    session = _memory_session()
    with pytest.raises(ValueError):
        importexport.import_data(session, ["not", "a", "dict"])


# --- Router: end-to-end export -> import through a real TestClient ---------


def _client():
    return TestClient(app)


def test_export_endpoint_returns_a_downloadable_json_document():
    with _client() as c:
        resp = c.get("/db/export")
    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("content-disposition", "")
    data = resp.json()
    assert "actions" in data and "profiles" in data


def test_export_then_import_roundtrip_through_the_api():
    with _client() as c:
        c.post("/db/import", json={"profiles": [{"name": "Track car", "make": "Mazda"}]})
        exported = c.get("/db/export").json()
        assert any(p["name"] == "Track car" for p in exported["profiles"])

        # Re-importing the same export must not error and must not duplicate.
        resp = c.post("/db/import", json=exported)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        again = c.get("/db/export").json()
        assert len(again["profiles"]) == len(exported["profiles"])


def test_export_profile_by_id_via_query_param():
    with _client() as c:
        c.post("/db/import", json={"profiles": [{"name": "Solo profile"}]})
        all_data = c.get("/db/export").json()
        profile_id = next(p["id"] for p in all_data["profiles"] if p["name"] == "Solo profile")

        resp = c.get(f"/db/export?profile_id={profile_id}")
        assert resp.status_code == 200
        scoped = resp.json()
        assert len(scoped["profiles"]) == 1
        assert scoped["profiles"][0]["name"] == "Solo profile"


def test_export_unknown_profile_id_is_404():
    with _client() as c:
        resp = c.get("/db/export?profile_id=999999")
    assert resp.status_code == 404
