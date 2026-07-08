"""The /logs API and /ui/logs page, plus that running an action journals it."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_logs_page_renders(client):
    resp = client.get("/ui/logs")
    assert resp.status_code == 200
    assert "Logs" in resp.text


def test_logs_nav_link_present(client):
    resp = client.get("/ui/logs")
    assert 'href="ui/logs"' in resp.text


def test_recent_empty_then_populated(client):
    resp = client.get("/logs/recent")
    assert resp.status_code == 200
    assert resp.json()["events"] == []

    client.post("/actions/page_next/run")

    resp = client.get("/logs/recent")
    events = resp.json()["events"]
    assert len(events) == 1
    assert events[0]["kind"] == "action"
    assert "page_next" in events[0]["message"]


def test_recent_kind_filter(client):
    client.post("/actions/page_next/run")
    resp = client.get("/logs/recent", params={"kind": "can"})
    assert resp.json()["events"] == []


def test_files_and_download(client):
    client.post("/actions/page_next/run")
    files = client.get("/logs/files").json()["files"]
    assert len(files) == 1
    name = files[0]["name"]

    resp = client.get(f"/logs/file/{name}")
    assert resp.status_code == 200
    assert "page_next" in resp.text


def test_download_rejects_path_traversal(client):
    resp = client.get("/logs/file/..%2F..%2Fetc%2Fpasswd")
    assert resp.status_code in (404, 400)


def test_download_missing_file_404s(client):
    resp = client.get("/logs/file/autopi-19990101.jsonl")
    assert resp.status_code == 404


def test_clear_removes_files(client):
    client.post("/actions/page_next/run")
    assert len(client.get("/logs/files").json()["files"]) == 1
    resp = client.post("/logs/clear")
    assert resp.json() == {"ok": True, "removed": 1}
    assert client.get("/logs/files").json()["files"] == []
    assert client.get("/logs/recent").json()["events"] == []
