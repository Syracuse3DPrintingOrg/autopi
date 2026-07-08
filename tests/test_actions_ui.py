"""The /ui/actions library page and creating a can_command action through
the /actions API that backs it."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.actions import registry
from app.can import dbc
from app.db import CanDatabase, init_db, session_scope

SAMPLE_DBC = """VERSION ""

BU_: ECU RADIO

BO_ 512 VolumeControl: 8 RADIO
 SG_ VOLUME_UP : 0|8@1+ (1,0) [0|255] "" ECU
"""

cantools_missing = not dbc.available()
skip_no_cantools = pytest.mark.skipif(cantools_missing, reason="cantools not installed")


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_ui_actions_page_renders(client):
    resp = client.get("/ui/actions")
    assert resp.status_code == 200
    assert "Action library" in resp.text


def test_actions_nav_link_present(client):
    resp = client.get("/ui/actions")
    assert 'href="ui/actions"' in resp.text


def test_drivers_list_includes_can_command(client):
    resp = client.get("/actions/drivers")
    names = {d["name"] for d in resp.json()["drivers"]}
    assert "can_command" in names


def test_create_can_command_action_raw_mode(client):
    resp = client.post("/actions", json={
        "id": "horn",
        "label": "Horn",
        "driver": "can_command",
        "params": {"channel": "can0", "arbitration_id": "0x3D1", "data": "01"},
        "category": "Vehicle",
    })
    assert resp.status_code == 200, resp.text
    action = registry.get_action("horn")
    assert action is not None
    assert action.driver == "can_command"
    assert action.category == "Vehicle"

    # The CAN drivers are simulate_when_unavailable, so with no bus in CI the
    # run reports a simulated send instead of refusing, which is what makes the
    # UI "Test" button useful on a bench.
    run = client.post("/actions/horn/run")
    body = run.json()
    assert body["ok"] is True
    assert body["data"].get("simulated") is True


@skip_no_cantools
def test_create_and_run_can_command_action_with_database(client):
    init_db()
    with session_scope() as s:
        database = dbc.import_dbc(s, name="radio", dbc_text=SAMPLE_DBC, source="upload")
        s.flush()
        db_id = database.id

    resp = client.post("/actions", json={
        "id": "volume_up",
        "label": "Volume Up",
        "driver": "can_command",
        "params": {"database_id": db_id, "message": "VolumeControl",
                   "signals": {"VOLUME_UP": 1}},
        "category": "Vehicle",
    })
    assert resp.status_code == 200, resp.text
    action = registry.get_action("volume_up")
    assert action.params["database_id"] == db_id
    assert action.params["message"] == "VolumeControl"
    assert action.params["signals"] == {"VOLUME_UP": 1}

    # With no bus in CI the CAN command simulates (encodes the frame and reports
    # what it would send) rather than refusing, so the Test button works.
    run = client.post("/actions/volume_up/run")
    body = run.json()
    assert body["ok"] is True
    assert body["data"].get("simulated") is True


def test_delete_action(client):
    client.post("/actions", json={"id": "temp_action", "driver": "shell",
                                  "params": {"command": "true"}})
    resp = client.delete("/actions/temp_action")
    assert resp.status_code == 200
    assert registry.get_action("temp_action") is None
