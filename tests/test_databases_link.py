"""Tests for the Databases page and linking a database to a vehicle."""
import pytest
from starlette.testclient import TestClient

from app.db import init_db
from app.main import app


@pytest.fixture(autouse=True)
def _tables(temp_data_dir):
    init_db()


def _client():
    return TestClient(app)


def _make_db(client, name="Test DBC", **meta):
    resp = client.post("/can/databases", json={"name": name, **meta})
    assert resp.status_code == 200
    return resp.json()["database"]


def _make_vehicle(client, name="Bench car"):
    resp = client.post("/profiles", json={"name": name, "make": "Honda", "model": "Civic"})
    assert resp.status_code == 200
    return resp.json()


def test_databases_page_renders():
    with _client() as client:
        resp = client.get("/ui/databases")
        assert resp.status_code == 200
        assert "CAN databases" in resp.text


def test_link_database_to_vehicle_persists_in_profile_config():
    with _client() as client:
        db = _make_db(client)
        vehicle = _make_vehicle(client)
        resp = client.post(f"/can/databases/{db['id']}/link", json={"profile_id": vehicle["id"]})
        assert resp.status_code == 200
        assert resp.json()["can_database_ids"] == [db["id"]]
        profile = client.get(f"/profiles/{vehicle['id']}").json()
        assert profile["config"]["can_database_ids"] == [db["id"]]


def test_link_is_idempotent_and_keeps_other_links():
    with _client() as client:
        db1 = _make_db(client, name="First")
        db2 = _make_db(client, name="Second")
        vehicle = _make_vehicle(client)
        client.post(f"/can/databases/{db1['id']}/link", json={"profile_id": vehicle["id"]})
        client.post(f"/can/databases/{db2['id']}/link", json={"profile_id": vehicle["id"]})
        resp = client.post(f"/can/databases/{db1['id']}/link", json={"profile_id": vehicle["id"]})
        assert resp.json()["can_database_ids"] == [db1["id"], db2["id"]]


def test_unlink_removes_only_that_database():
    with _client() as client:
        db1 = _make_db(client, name="Keep")
        db2 = _make_db(client, name="Drop")
        vehicle = _make_vehicle(client)
        client.post(f"/can/databases/{db1['id']}/link", json={"profile_id": vehicle["id"]})
        client.post(f"/can/databases/{db2['id']}/link", json={"profile_id": vehicle["id"]})
        resp = client.post(f"/can/databases/{db2['id']}/unlink", json={"profile_id": vehicle["id"]})
        assert resp.json()["can_database_ids"] == [db1["id"]]
        profile = client.get(f"/profiles/{vehicle['id']}").json()
        assert profile["config"]["can_database_ids"] == [db1["id"]]


def test_link_missing_database_or_vehicle_404s():
    with _client() as client:
        vehicle = _make_vehicle(client)
        assert client.post("/can/databases/9999/link", json={"profile_id": vehicle["id"]}).status_code == 404
        db = _make_db(client)
        assert client.post(f"/can/databases/{db['id']}/link", json={"profile_id": 9999}).status_code == 404


def test_unlink_survives_a_deleted_database():
    with _client() as client:
        db = _make_db(client)
        vehicle = _make_vehicle(client)
        client.post(f"/can/databases/{db['id']}/link", json={"profile_id": vehicle["id"]})
        client.delete(f"/can/databases/{db['id']}")
        resp = client.post(f"/can/databases/{db['id']}/unlink", json={"profile_id": vehicle["id"]})
        assert resp.status_code == 200
        assert resp.json()["can_database_ids"] == []
