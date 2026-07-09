"""Tests for the virtual cockpit model: pure placement/scaling and gauge
value mapping, persistence CRUD, and the /cockpit router (image upload guard,
key firing, and the values endpoint with a stubbed decode).
"""
from __future__ import annotations

import io

import pytest

from app.services import cockpit as cockpit_svc


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------

def test_clamp_basic():
    assert cockpit_svc.clamp(5, 0, 10) == 5
    assert cockpit_svc.clamp(-5, 0, 10) == 0
    assert cockpit_svc.clamp(15, 0, 10) == 10


def test_clamp_swapped_range():
    assert cockpit_svc.clamp(5, 10, 0) == 5
    assert cockpit_svc.clamp(-5, 10, 0) == 0


def test_normalize_element_defaults_and_clamping():
    el = cockpit_svc.normalize_element({"type": "key", "x": 1.5, "y": -0.2, "w": 5, "h": 0})
    assert el["type"] == "key"
    assert el["x"] == 1.0
    assert el["y"] == 0.0
    assert el["w"] == 1.0
    assert el["h"] == 0.01


def test_normalize_element_unknown_type_falls_back_to_key():
    el = cockpit_svc.normalize_element({"type": "bogus"})
    assert el["type"] == "key"


def test_normalize_element_parses_hex_arbitration_id():
    el = cockpit_svc.normalize_element({"type": "gauge", "arbitration_id": "0x201"})
    assert el["arbitration_id"] == 0x201


def test_normalize_element_parses_decimal_string_arbitration_id():
    el = cockpit_svc.normalize_element({"type": "gauge", "arbitration_id": "512"})
    assert el["arbitration_id"] == 512


def test_normalize_element_bad_arbitration_id_is_none():
    el = cockpit_svc.normalize_element({"type": "gauge", "arbitration_id": "not-a-number"})
    assert el["arbitration_id"] is None


def test_normalize_element_gauge_style_defaults_to_bar():
    el = cockpit_svc.normalize_element({"type": "gauge"})
    assert el["style"] == "bar"


def test_normalize_element_invalid_gauge_style_falls_back():
    el = cockpit_svc.normalize_element({"type": "gauge", "style": "pie-chart"})
    assert el["style"] == "numeric"


def test_element_rect_percent():
    el = {"x": 0.25, "y": 0.5, "w": 0.1, "h": 0.2}
    rect = cockpit_svc.element_rect_percent(el)
    assert rect == {"left": 25.0, "top": 50.0, "width": 10.0, "height": 20.0}


def test_element_rect_percent_clamps_out_of_range():
    el = {"x": 2.0, "y": -1.0, "w": 5.0, "h": 0.0}
    rect = cockpit_svc.element_rect_percent(el)
    assert rect["left"] == 100.0
    assert rect["top"] == 0.0
    assert rect["width"] == 100.0
    assert rect["height"] == 1.0


def test_gauge_percent_midpoint():
    assert cockpit_svc.gauge_percent(50, 0, 100) == 50.0


def test_gauge_percent_clamps_outside_range():
    assert cockpit_svc.gauge_percent(-10, 0, 100) == 0.0
    assert cockpit_svc.gauge_percent(200, 0, 100) == 100.0


def test_gauge_percent_degenerate_range():
    assert cockpit_svc.gauge_percent(5, 10, 10) == 0.0


def test_indicator_on_threshold():
    assert cockpit_svc.indicator_on(5, 4) is True
    assert cockpit_svc.indicator_on(3, 4) is False


def test_indicator_on_non_numeric_falls_back_to_truthy():
    assert cockpit_svc.indicator_on("PARK", None) is True
    assert cockpit_svc.indicator_on("", None) is False


def test_map_element_value_no_data():
    el = {"type": "gauge", "min": 0, "max": 100}
    result = cockpit_svc.map_element_value(el, None)
    assert result == {"ok": False, "raw": None, "value": None, "percent": None,
                       "on": None, "display": "--"}


def test_map_element_value_gauge_clamps_and_computes_percent():
    el = {"type": "gauge", "min": 0, "max": 200, "unit": "mph"}
    result = cockpit_svc.map_element_value(el, 250)
    assert result["ok"] is True
    assert result["value"] == 200
    assert result["percent"] == 100.0
    assert result["display"] == "200.0 mph"


def test_map_element_value_indicator_on():
    el = {"type": "indicator", "threshold": 1}
    result = cockpit_svc.map_element_value(el, 1)
    assert result["on"] is True
    assert result["display"] == "ON"


def test_map_element_value_indicator_off():
    el = {"type": "indicator", "threshold": 1}
    result = cockpit_svc.map_element_value(el, 0)
    assert result["on"] is False
    assert result["display"] == "OFF"


def test_map_element_value_non_numeric_raw_passthrough():
    el = {"type": "gauge", "min": 0, "max": 100}
    result = cockpit_svc.map_element_value(el, "PARK")
    assert result["value"] is None
    assert result["display"] == "PARK"


def test_latest_signal_value_uses_most_recent_matching_frame():
    frames = [
        {"arbitration_id": 0x201, "data": [1, 2, 3, 4, 5, 6, 7, 8]},
        {"arbitration_id": 0x300, "data": [0, 0, 0, 0, 0, 0, 0, 0]},
        {"arbitration_id": 0x201, "data": [9, 9, 9, 9, 9, 9, 9, 9]},
    ]

    def fake_decode(dbc_text, arbitration_id, data):
        return {"SPEED": data[0]}

    value = cockpit_svc.latest_signal_value(frames, "DBC TEXT", 0x201, "SPEED", decode_fn=fake_decode)
    assert value == 9


def test_latest_signal_value_no_match_returns_none():
    value = cockpit_svc.latest_signal_value([], "DBC TEXT", 0x201, "SPEED")
    assert value is None


def test_latest_signal_value_unbound_returns_none():
    assert cockpit_svc.latest_signal_value([{"arbitration_id": 1, "data": []}], None, 1, "SPEED") is None
    assert cockpit_svc.latest_signal_value([{"arbitration_id": 1, "data": []}], "text", None, "SPEED") is None
    assert cockpit_svc.latest_signal_value([{"arbitration_id": 1, "data": []}], "text", 1, None) is None


def test_latest_signal_value_decode_failure_returns_none():
    def bad_decode(dbc_text, arbitration_id, data):
        raise ValueError("boom")

    frames = [{"arbitration_id": 1, "data": [0]}]
    assert cockpit_svc.latest_signal_value(frames, "text", 1, "SPEED", decode_fn=bad_decode) is None


def test_channels_used_distinct_and_ordered():
    cockpit = {"elements": [
        {"type": "gauge", "channel": "can1", "backend": "socketcan"},
        {"type": "gauge", "channel": "can0", "backend": "socketcan"},
        {"type": "indicator", "channel": "can1", "backend": "socketcan"},  # dup of first
        {"type": "key", "channel": "can2"},                                 # not a gauge/indicator
        {"type": "gauge"},                                                  # defaults can0 -> dup
    ]}
    used = cockpit_svc.channels_used(cockpit)
    assert used == [
        {"channel": "can1", "backend": "socketcan"},
        {"channel": "can0", "backend": "socketcan"},
    ]


def test_channels_used_empty_cockpit():
    assert cockpit_svc.channels_used({}) == []
    assert cockpit_svc.channels_used({"elements": []}) == []


def test_validate_image_upload_rejects_bad_extension():
    assert cockpit_svc.validate_image_upload("dash.txt", 100) is not None


def test_validate_image_upload_rejects_oversize():
    assert cockpit_svc.validate_image_upload("dash.png", cockpit_svc.MAX_IMAGE_BYTES + 1) is not None


def test_validate_image_upload_rejects_empty():
    assert cockpit_svc.validate_image_upload("dash.png", 0) is not None


def test_validate_image_upload_accepts_good_file():
    assert cockpit_svc.validate_image_upload("dash.png", 1024) is None


# --------------------------------------------------------------------------
# Persistence CRUD (uses the temp_data_dir autouse fixture from conftest.py)
# --------------------------------------------------------------------------

def test_create_get_update_delete_cockpit_roundtrip():
    cockpit = cockpit_svc.create_cockpit(name="Rig 1")
    assert cockpit["name"] == "Rig 1"
    assert cockpit["elements"] == []

    fetched = cockpit_svc.get_cockpit(cockpit["id"])
    assert fetched == cockpit

    updated = cockpit_svc.update_cockpit(cockpit["id"], name="Rig 1 Renamed")
    assert updated["name"] == "Rig 1 Renamed"

    assert cockpit_svc.delete_cockpit(cockpit["id"]) is True
    assert cockpit_svc.get_cockpit(cockpit["id"]) is None
    assert cockpit_svc.delete_cockpit(cockpit["id"]) is False


def test_set_background_image_persists():
    cockpit = cockpit_svc.create_cockpit(name="Rig")
    updated = cockpit_svc.set_background_image(cockpit["id"], "1.png")
    assert updated["image_filename"] == "1.png"
    assert cockpit_svc.get_cockpit(cockpit["id"])["image_filename"] == "1.png"


def test_add_update_delete_element_roundtrip():
    cockpit = cockpit_svc.create_cockpit(name="Rig")
    updated = cockpit_svc.add_element(cockpit["id"], {"type": "key", "label": "Horn", "action_id": "horn"})
    assert len(updated["elements"]) == 1
    element = updated["elements"][0]
    assert element["label"] == "Horn"
    assert element["id"]

    updated = cockpit_svc.update_element(cockpit["id"], element["id"], {"label": "Horn 2"})
    assert updated["elements"][0]["label"] == "Horn 2"

    assert cockpit_svc.delete_element(cockpit["id"], element["id"]) is True
    assert cockpit_svc.get_cockpit(cockpit["id"])["elements"] == []


def test_add_element_unknown_cockpit_returns_none():
    assert cockpit_svc.add_element(999, {"type": "key"}) is None


def test_element_ids_increment_across_deletes():
    cockpit = cockpit_svc.create_cockpit(name="Rig")
    cockpit_svc.add_element(cockpit["id"], {"type": "key"})
    updated = cockpit_svc.add_element(cockpit["id"], {"type": "key"})
    ids = [e["id"] for e in updated["elements"]]
    assert ids == ["el1", "el2"]
    cockpit_svc.delete_element(cockpit["id"], "el1")
    updated = cockpit_svc.add_element(cockpit["id"], {"type": "key"})
    ids = [e["id"] for e in updated["elements"]]
    assert ids == ["el2", "el3"]


# --------------------------------------------------------------------------
# Router: image upload guard, key firing, and the values endpoint
# --------------------------------------------------------------------------

@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def test_router_create_and_list_cockpit(client):
    resp = client.post("/cockpit", json={"name": "Test Rig"})
    assert resp.status_code == 200
    cockpit_id = resp.json()["id"]

    resp = client.get("/cockpit")
    assert resp.status_code == 200
    assert any(c["id"] == cockpit_id for c in resp.json()["cockpits"])


def test_router_upload_image_rejects_bad_type(client):
    resp = client.post("/cockpit", json={"name": "Rig"})
    cockpit_id = resp.json()["id"]
    resp = client.post(
        f"/cockpit/{cockpit_id}/image",
        files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert resp.status_code == 400


def test_router_upload_image_accepts_png(client):
    resp = client.post("/cockpit", json={"name": "Rig"})
    cockpit_id = resp.json()["id"]
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    resp = client.post(
        f"/cockpit/{cockpit_id}/image",
        files={"file": ("dash.png", io.BytesIO(png_bytes), "image/png")},
    )
    assert resp.status_code == 200
    assert resp.json()["cockpit"]["image_filename"] == f"{cockpit_id}.png"

    resp = client.get(f"/cockpit/{cockpit_id}/image")
    assert resp.status_code == 200
    assert resp.content == png_bytes


def test_router_fire_key_runs_action(client, monkeypatch):
    resp = client.post("/cockpit", json={"name": "Rig"})
    cockpit_id = resp.json()["id"]
    resp = client.post(f"/cockpit/{cockpit_id}/elements", json={"type": "key", "action_id": "clock"})
    element_id = resp.json()["elements"][0]["id"]

    resp = client.post(f"/cockpit/{cockpit_id}/elements/{element_id}/fire")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True


def test_router_fire_key_with_no_action_reports_not_bound(client):
    resp = client.post("/cockpit", json={"name": "Rig"})
    cockpit_id = resp.json()["id"]
    resp = client.post(f"/cockpit/{cockpit_id}/elements", json={"type": "key"})
    element_id = resp.json()["elements"][0]["id"]

    resp = client.post(f"/cockpit/{cockpit_id}/elements/{element_id}/fire")
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


def test_router_fire_non_key_element_rejected(client):
    resp = client.post("/cockpit", json={"name": "Rig"})
    cockpit_id = resp.json()["id"]
    resp = client.post(f"/cockpit/{cockpit_id}/elements", json={"type": "gauge"})
    element_id = resp.json()["elements"][0]["id"]

    resp = client.post(f"/cockpit/{cockpit_id}/elements/{element_id}/fire")
    assert resp.status_code == 400


def test_router_values_endpoint_with_stubbed_monitor_and_decode(client, monkeypatch):
    resp = client.post("/cockpit", json={"name": "Rig"})
    cockpit_id = resp.json()["id"]
    resp = client.post(
        f"/cockpit/{cockpit_id}/elements",
        json={"type": "gauge", "database_id": 1, "arbitration_id": "0x201",
              "signal": "SPEED", "min": 0, "max": 200},
    )
    assert resp.status_code == 200

    class FakeMonitor:
        def frames(self):
            return [{"arbitration_id": 0x201, "data": [42, 0, 0, 0, 0, 0, 0, 0]}]

        def is_running(self):
            return True

        def is_live(self):
            return True

    from app.can import monitor as mon
    monkeypatch.setattr(mon, "get_monitor", lambda channel, backend="socketcan": FakeMonitor())

    from app.routers import cockpit as cockpit_router
    monkeypatch.setattr(cockpit_router, "_resolve_dbc_text", lambda database_id: "FAKE DBC")

    from app.services import cockpit as cockpit_svc_mod
    monkeypatch.setattr(
        cockpit_svc_mod, "latest_signal_value",
        lambda frames, dbc_text, arb, signal, decode_fn=None: 88,
    )

    resp = client.get(f"/cockpit/{cockpit_id}/values")
    assert resp.status_code == 200
    values = resp.json()["values"]
    assert len(values) == 1
    (v,) = values.values()
    assert v["ok"] is True
    assert v["value"] == 88


def test_router_values_endpoint_unbound_gauge_reports_no_data(client):
    resp = client.post("/cockpit", json={"name": "Rig"})
    cockpit_id = resp.json()["id"]
    client.post(f"/cockpit/{cockpit_id}/elements", json={"type": "gauge"})

    resp = client.get(f"/cockpit/{cockpit_id}/values")
    assert resp.status_code == 200
    (v,) = resp.json()["values"].values()
    assert v["ok"] is False
