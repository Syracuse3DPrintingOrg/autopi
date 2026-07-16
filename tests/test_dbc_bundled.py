"""Bundled open DBC files and their offline one-click install (AutoPi-rak)."""
import pytest
from starlette.testclient import TestClient

from app.can import dbc as dbc_mod
from app.db import init_db
from app.main import app
from app.services import dbc_catalog


@pytest.fixture(autouse=True)
def _tables(temp_data_dir):
    init_db()


def _client():
    return TestClient(app)


# --- manifest / files ------------------------------------------------------

def test_bundled_lists_only_permissive_present_files():
    entries = dbc_catalog.bundled()
    assert entries, "expected at least one bundled DBC"
    for e in entries:
        assert e["bundled"] is True
        assert dbc_catalog._is_permissive(e["license"]), e["name"]
        # Every listed file actually reads back as DBC text.
        text = dbc_catalog.bundled_dbc_text(e["file"])
        assert text and "BO_" in text, e["file"]


def test_bundled_entry_rejects_paths_outside_the_manifest():
    assert dbc_catalog.bundled_entry("../config.py") is None
    assert dbc_catalog.bundled_entry("/etc/passwd") is None
    assert dbc_catalog.bundled_dbc_text("../../secret.dbc") is None


def test_bundled_route_flags_matches_for_active_vehicle():
    with _client() as client:
        body = client.get("/can/dbc/bundled").json()
        assert isinstance(body["bundled"], list)
        assert body["bundled"], "route should surface bundled files"


# --- install ---------------------------------------------------------------

def test_install_bundled_unknown_file_404s():
    with _client() as client:
        resp = client.post("/can/dbc/install-bundled", json={"file": "nope.dbc"})
        assert resp.status_code == 404


def test_install_bundled_imports_offline_when_cantools_present():
    file = dbc_catalog.bundled()[0]["file"]
    with _client() as client:
        resp = client.post("/can/dbc/install-bundled", json={"file": file})
        if not dbc_mod.available():
            # No cantools in this environment: the endpoint refuses cleanly and
            # imports nothing, rather than crashing.
            assert resp.status_code == 400
            assert client.get("/can/databases").json()["databases"] == []
            return
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        # It landed as a real installed database with a source of "bundled".
        dbs = client.get("/can/databases").json()["databases"]
        assert any(d["source"] == "AutoPi bundled" for d in dbs)
