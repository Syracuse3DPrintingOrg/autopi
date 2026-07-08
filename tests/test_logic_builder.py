"""Tests for the cross-trigger rule builder (AutoPi-49q).

Covers the pieces the /ui/automation builder relies on: the rule/runtime
config API round-trips what the UI posts, a CAN-signal condition and a
GPIO-input condition each drive the engine to the right action with
injected inputs, and the multi-protocol outputs (relay, I2C, Modbus) are
selectable actions that actually fire from the runtime's scan loop.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.actions import registry
from app.actions.registry import ActionSpec
from app.logic import runtime as rt
from app.logic.engine import Engine
from app.logic.rule import Rule
from app.logic.store import load_rules, save_rules


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


# --- builder round-trip through the REST API -------------------------------


def test_rules_api_round_trips_a_builder_rule(client):
    rule = {
        "id": "fan_over_temp",
        "name": "Drive fan relay above 90C",
        "condition": {"type": "compare", "signal": "coolant_temp", "op": ">=", "value": 90},
        "actions": ["fan_relay"],
        "trigger": "level",
        "enabled": True,
    }
    resp = client.put("/logic/rules", json={"rules": [rule]})
    assert resp.status_code == 200
    assert resp.json()["count"] == 1

    got = client.get("/logic/rules").json()["rules"]
    assert len(got) == 1
    assert got[0]["id"] == "fan_over_temp"
    assert got[0]["condition"]["signal"] == "coolant_temp"
    assert got[0]["actions"] == ["fan_relay"]


def test_runtime_config_round_trips_builder_inputs(client):
    inputs = [
        {"name": "coolant_temp", "type": "can_signal", "database_id": 1,
         "message": "ENGINE_TEMP", "signal": "COOLANT_TEMP", "channel": "can0", "backend": "socketcan"},
        {"name": "door_switch", "type": "gpio", "pin": 17},
    ]
    resp = client.put("/logic/runtime", json={"inputs": inputs})
    assert resp.status_code == 200
    assert resp.json()["config"]["inputs"] == inputs

    got = client.get("/logic/runtime").json()["config"]["inputs"]
    assert got == inputs


def test_reordering_and_disabling_rules_round_trips(client):
    rules_payload = [
        {"id": "r1", "name": "First", "condition": {"type": "bool", "signal": "a"}, "actions": ["x"]},
        {"id": "r2", "name": "Second", "condition": {"type": "bool", "signal": "b"}, "actions": ["y"]},
    ]
    client.put("/logic/rules", json={"rules": rules_payload})

    # Reorder (r2 first) and disable r1, as the "up" button + power toggle would.
    reordered = [
        {**rules_payload[1]},
        {**rules_payload[0], "enabled": False},
    ]
    client.put("/logic/rules", json={"rules": reordered})

    got = client.get("/logic/rules").json()["rules"]
    assert [r["id"] for r in got] == ["r2", "r1"]
    assert got[1]["enabled"] is False


# --- headline flow 1: a CAN signal drives an output -------------------------


def test_can_signal_condition_selects_output_action(monkeypatch):
    """WHEN a CAN-sourced signal crosses a value THEN an output action fires."""
    monkeypatch.setattr(rt, "_resolve_can", lambda db, msg: (0x1F0, "DBCTEXT"))
    monkeypatch.setattr(rt.monitor, "decode_record", lambda rec, txt: {"COOLANT_TEMP": 95})
    frames = [{"arbitration_id": 0x1F0, "data": "00"}]

    save_rules([Rule(
        id="fan_rule",
        condition={"type": "compare", "signal": "coolant_temp", "op": ">=", "value": 90},
        actions=["fan_relay"], trigger="level",
    )])
    rt.set_config({"inputs": [
        {"name": "coolant_temp", "type": "can_signal", "database_id": 1,
         "message": "ENGINE_TEMP", "signal": "COOLANT_TEMP", "channel": "can0"},
    ]})

    fired = []
    result = rt.runtime.scan_once(
        0.0, frames_for=lambda c, b: frames, gpio_read=lambda p: None,
        fire=lambda aid: fired.append(aid) or type("R", (), {"ok": True})())

    assert fired == ["fan_relay"]
    assert result["inputs"]["coolant_temp"] == 95
    assert result["outputs"]["fan_rule"] is True


def test_can_signal_condition_does_not_fire_below_threshold(monkeypatch):
    monkeypatch.setattr(rt, "_resolve_can", lambda db, msg: (0x1F0, "DBCTEXT"))
    monkeypatch.setattr(rt.monitor, "decode_record", lambda rec, txt: {"COOLANT_TEMP": 60})
    frames = [{"arbitration_id": 0x1F0, "data": "00"}]

    save_rules([Rule(
        id="fan_rule",
        condition={"type": "compare", "signal": "coolant_temp", "op": ">=", "value": 90},
        actions=["fan_relay"],
    )])
    rt.set_config({"inputs": [
        {"name": "coolant_temp", "type": "can_signal", "database_id": 1,
         "message": "ENGINE_TEMP", "signal": "COOLANT_TEMP", "channel": "can0"},
    ]})

    fired = []
    rt.runtime.scan_once(0.0, frames_for=lambda c, b: frames, gpio_read=lambda p: None,
                         fire=lambda aid: fired.append(aid))
    assert fired == []


# --- headline flow 2: a GPIO input triggers a CAN command -------------------


def test_gpio_input_condition_selects_can_command_action():
    """WHEN a GPIO input pin goes high THEN a CAN command action fires."""
    save_rules([Rule(
        id="horn_rule",
        condition={"type": "bool", "signal": "horn_button"},
        actions=["send_horn_command"], trigger="rising",
    )])
    rt.set_config({"inputs": [{"name": "horn_button", "type": "gpio", "pin": 17}]})

    pin_state = {"value": 0}
    fired = []

    def fire(aid):
        fired.append(aid)
        return type("R", (), {"ok": True})()

    # Scan 1: pin low, rule armed but not yet true.
    rt.runtime.scan_once(0.0, frames_for=lambda c, b: [], gpio_read=lambda p: pin_state["value"], fire=fire)
    assert fired == []

    # Scan 2: pin goes high -> rising edge on the "rising" trigger fires once.
    pin_state["value"] = 1
    rt.runtime.scan_once(1.0, frames_for=lambda c, b: [], gpio_read=lambda p: pin_state["value"], fire=fire)
    assert fired == ["send_horn_command"]

    # Scan 3: pin stays high -> rising-triggered rule does not fire again.
    fired.clear()
    rt.runtime.scan_once(2.0, frames_for=lambda c, b: [], gpio_read=lambda p: pin_state["value"], fire=fire)
    assert fired == []


def test_gpio_edge_condition_via_engine_directly():
    """The edge condition type also works standalone against a GPIO-sourced input."""
    engine = Engine([Rule(
        id="button_edge",
        condition={"type": "edge", "id": "e1", "signal": "btn", "edge": "rising"},
        actions=["ping"],
    )])
    out1 = engine.scan({"btn": False}, 0.0)
    assert out1.fire == []
    out2 = engine.scan({"btn": True}, 1.0)
    assert out2.fire == ["ping"]


# --- multi-protocol outputs are selectable and fireable as logic actions ---


def _make_action(action_id: str, driver: str, params: dict) -> None:
    registry.upsert_action(ActionSpec(id=action_id, label=action_id, driver=driver, params=params))


def test_relay_action_fires_from_runtime_scan(monkeypatch):
    # Relay boards are real hardware, so (like the plain GPIO driver) the
    # registry correctly refuses to run one when no pin factory is present
    # (see test_registry.py::test_run_refuses_unavailable_driver). Mock the
    # hardware as present, the way a real Pi with a relay HAT would report
    # it, to confirm the relay action genuinely fires through the runtime's
    # scan loop rather than just being reachable in the store.
    from app.actions.drivers.gpio import GpioDriver

    class _FakeDevice:
        def __init__(self):
            self.value = 0

        def blink(self, **kwargs):
            pass

    monkeypatch.setattr(GpioDriver, "available", property(lambda self: True))
    monkeypatch.setattr(GpioDriver, "_device", lambda self, pin, active_high: _FakeDevice())

    _make_action("bench_relay", "relay", {"pin": 5, "state": "on"})
    save_rules([Rule(id="r1", condition={"type": "bool", "signal": "go"}, actions=["bench_relay"])])
    rt.set_config({"inputs": [{"name": "go", "type": "constant", "value": True}]})

    result = rt.runtime.scan_once(0.0, frames_for=lambda c, b: [], gpio_read=lambda p: None)
    fired_ids = [f["id"] for f in result["fired"]]
    assert "bench_relay" in fired_ids
    assert all(f["ok"] for f in result["fired"])


def test_i2c_action_fires_from_runtime_scan():
    _make_action("bench_i2c", "i2c", {"address": "0x48", "register": "0x00", "op": "read_byte"})
    save_rules([Rule(id="r1", condition={"type": "bool", "signal": "go"}, actions=["bench_i2c"])])
    rt.set_config({"inputs": [{"name": "go", "type": "constant", "value": True}]})

    result = rt.runtime.scan_once(0.0, frames_for=lambda c, b: [], gpio_read=lambda p: None)
    fired_ids = [f["id"] for f in result["fired"]]
    assert "bench_i2c" in fired_ids
    assert all(f["ok"] for f in result["fired"])


def test_modbus_action_fires_from_runtime_scan():
    _make_action("bench_modbus", "modbus", {"host": "10.0.0.5", "op": "read_register", "address": 40001})
    save_rules([Rule(id="r1", condition={"type": "bool", "signal": "go"}, actions=["bench_modbus"])])
    rt.set_config({"inputs": [{"name": "go", "type": "constant", "value": True}]})

    result = rt.runtime.scan_once(0.0, frames_for=lambda c, b: [], gpio_read=lambda p: None)
    fired_ids = [f["id"] for f in result["fired"]]
    assert "bench_modbus" in fired_ids
    assert all(f["ok"] for f in result["fired"])


def test_relay_i2c_modbus_selectable_via_actions_api(client):
    for name, driver, params in (
        ("api_relay", "relay", {"pin": 5, "state": "on"}),
        ("api_i2c", "i2c", {"address": "0x48", "register": "0x00", "op": "read_byte"}),
        ("api_modbus", "modbus", {"host": "10.0.0.5", "op": "read_register", "address": 1}),
    ):
        resp = client.post("/actions", json={"id": name, "label": name, "driver": driver, "params": params})
        assert resp.status_code == 200, resp.text

    ids = {a["id"] for a in client.get("/actions").json()["actions"]}
    assert {"api_relay", "api_i2c", "api_modbus"}.issubset(ids)
