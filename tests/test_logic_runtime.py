"""Tests for the logic runtime (Phase 3: inputs -> rules -> actions)."""
from app.logic import runtime as rt
from app.logic.store import save_rules
from app.logic.rule import Rule


def test_gather_inputs_constant_and_gpio():
    inputs = [
        {"name": "mode", "type": "constant", "value": 3},
        {"name": "btn", "type": "gpio", "pin": 17},
    ]
    got = rt.gather_inputs(inputs, frames_for=lambda c, b: [], gpio_read=lambda pin: 1)
    assert got == {"mode": 3, "btn": 1}


def test_gather_inputs_can_signal(monkeypatch):
    # Resolve returns (arb_id, dbc_text); the frame decode is stubbed.
    monkeypatch.setattr(rt, "_resolve_can", lambda db, msg: (0x1F0, "DBCTEXT"))
    monkeypatch.setattr(rt.monitor, "decode_record", lambda rec, txt: {"Speed": 88})
    frames = [{"arbitration_id": 0x1F0, "data": "00"}]
    inputs = [{"name": "spd", "type": "can_signal", "channel": "can0",
               "database_id": 1, "message": "VD", "signal": "Speed"}]
    got = rt.gather_inputs(inputs, frames_for=lambda c, b: frames, gpio_read=lambda p: None)
    assert got == {"spd": 88}


def test_gather_can_signal_no_frame_is_none(monkeypatch):
    monkeypatch.setattr(rt, "_resolve_can", lambda db, msg: (0x1F0, "DBCTEXT"))
    inputs = [{"name": "spd", "type": "can_signal", "database_id": 1, "message": "VD", "signal": "Speed"}]
    got = rt.gather_inputs(inputs, frames_for=lambda c, b: [], gpio_read=lambda p: None)
    assert got == {"spd": None}


def test_scan_once_fires_action_when_condition_true():
    save_rules([Rule(id="r1", condition={"type": "compare", "signal": "speed", "op": ">=", "value": 100},
                     actions=["overspeed"], trigger="level")])
    rt.set_config({"inputs": [{"name": "speed", "type": "constant", "value": 120}]})
    fired = []
    res = rt.runtime.scan_once(0.0, frames_for=lambda c, b: [], gpio_read=lambda p: None,
                               fire=lambda aid: fired.append(aid) or type("R", (), {"ok": True})())
    assert "overspeed" in fired
    assert res["inputs"]["speed"] == 120


def test_scan_once_does_not_fire_when_false():
    save_rules([Rule(id="r1", condition={"type": "compare", "signal": "speed", "op": ">=", "value": 100},
                     actions=["overspeed"])])
    rt.set_config({"inputs": [{"name": "speed", "type": "constant", "value": 50}]})
    fired = []
    rt.runtime.scan_once(0.0, frames_for=lambda c, b: [], gpio_read=lambda p: None,
                         fire=lambda aid: fired.append(aid))
    assert fired == []
