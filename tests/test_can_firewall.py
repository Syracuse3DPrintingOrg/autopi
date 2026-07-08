"""CAN firewall/gateway: pure rule matching and each action, the persisted
rule set and config, the gateway engine's start/stop/degradation, and the
router, all without real threads or CAN hardware.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.can import firewall as fw
from app.can.base import Frame
from app.can.firewall import Decision, GatewayEngine, apply_rules
from app.main import app


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    fw.engine.stop()


# -- rule matching (pure) -----------------------------------------------

def test_no_rules_passes_through_unmodified():
    frame = Frame(arbitration_id=0x100, data=[1, 2, 3])
    decision = apply_rules(frame, [], "a_to_b")
    assert decision == Decision(action="allow", rule_id=None, frame=frame)


def test_exact_id_match_blocks():
    frame = Frame(arbitration_id=0x100, data=[1])
    rules = [{"id": "r1", "action": "block", "match": {"arbitration_id": 0x100}}]
    decision = apply_rules(frame, rules, "a_to_b")
    assert decision.action == "block"
    assert decision.rule_id == "r1"
    assert decision.frame is None


def test_exact_id_mismatch_does_not_match():
    frame = Frame(arbitration_id=0x101, data=[1])
    rules = [{"id": "r1", "action": "block", "match": {"arbitration_id": 0x100}}]
    decision = apply_rules(frame, rules, "a_to_b")
    assert decision.action == "allow"
    assert decision.rule_id is None


def test_mask_match():
    # Mask 0x7F0 groups 0x100-0x10F together.
    rules = [{"id": "r1", "action": "block", "match": {"arbitration_id": 0x100, "mask": 0x7F0}}]
    hit = apply_rules(Frame(arbitration_id=0x10A, data=[]), rules, "a_to_b")
    miss = apply_rules(Frame(arbitration_id=0x200, data=[]), rules, "a_to_b")
    assert hit.action == "block"
    assert miss.action == "allow"


def test_id_range_match():
    rules = [{"id": "r1", "action": "block", "match": {"id_min": 0x100, "id_max": 0x1FF}}]
    assert apply_rules(Frame(arbitration_id=0x150, data=[]), rules, "a_to_b").action == "block"
    assert apply_rules(Frame(arbitration_id=0x200, data=[]), rules, "a_to_b").action == "allow"


def test_disabled_rule_is_skipped():
    rules = [{"id": "r1", "enabled": False, "action": "block", "match": {"arbitration_id": 0x100}}]
    decision = apply_rules(Frame(arbitration_id=0x100, data=[]), rules, "a_to_b")
    assert decision.action == "allow"
    assert decision.rule_id is None


def test_direction_scoping():
    rules = [{"id": "r1", "action": "block", "direction": "a_to_b", "match": {"arbitration_id": 0x100}}]
    blocked = apply_rules(Frame(arbitration_id=0x100, data=[]), rules, "a_to_b")
    passed = apply_rules(Frame(arbitration_id=0x100, data=[]), rules, "b_to_a")
    assert blocked.action == "block"
    assert passed.action == "allow"
    assert passed.rule_id is None


def test_both_direction_rule_applies_either_way():
    rules = [{"id": "r1", "action": "block", "direction": "both", "match": {"arbitration_id": 0x100}}]
    assert apply_rules(Frame(arbitration_id=0x100, data=[]), rules, "a_to_b").action == "block"
    assert apply_rules(Frame(arbitration_id=0x100, data=[]), rules, "b_to_a").action == "block"


def test_first_matching_rule_wins():
    rules = [
        {"id": "r1", "action": "allow", "match": {"arbitration_id": 0x100}},
        {"id": "r2", "action": "block", "match": {"arbitration_id": 0x100}},
    ]
    decision = apply_rules(Frame(arbitration_id=0x100, data=[]), rules, "a_to_b")
    assert decision.action == "allow"
    assert decision.rule_id == "r1"


def test_signal_match_compares_decoded_value(monkeypatch):
    def fake_decode(dbc_text, arbitration_id, data):
        return {"SPEED": 55}

    monkeypatch.setattr("app.can.dbc.decode", fake_decode)
    rules = [{
        "id": "r1", "action": "block",
        "match": {"database_id": 1, "signal": "SPEED", "op": "gt", "value": 50},
    }]
    decision = apply_rules(Frame(arbitration_id=0x100, data=[1]), rules, "a_to_b",
                           dbc_lookup=lambda db_id: "fake dbc text")
    assert decision.action == "block"


def test_signal_match_op_below_threshold_does_not_match(monkeypatch):
    monkeypatch.setattr("app.can.dbc.decode", lambda *a: {"SPEED": 10})
    rules = [{
        "id": "r1", "action": "block",
        "match": {"database_id": 1, "signal": "SPEED", "op": "gt", "value": 50},
    }]
    decision = apply_rules(Frame(arbitration_id=0x100, data=[1]), rules, "a_to_b",
                           dbc_lookup=lambda db_id: "fake dbc text")
    assert decision.action == "allow"


def test_signal_match_without_dbc_lookup_never_matches():
    rules = [{
        "id": "r1", "action": "block",
        "match": {"database_id": 1, "signal": "SPEED", "op": "gt", "value": 50},
    }]
    decision = apply_rules(Frame(arbitration_id=0x100, data=[1]), rules, "a_to_b", dbc_lookup=None)
    assert decision.action == "allow"


def test_signal_match_unknown_signal_does_not_match(monkeypatch):
    monkeypatch.setattr("app.can.dbc.decode", lambda *a: {"OTHER": 1})
    rules = [{
        "id": "r1", "action": "block",
        "match": {"database_id": 1, "signal": "SPEED", "op": "eq", "value": 1},
    }]
    decision = apply_rules(Frame(arbitration_id=0x100, data=[1]), rules, "a_to_b",
                           dbc_lookup=lambda db_id: "fake dbc text")
    assert decision.action == "allow"


# -- rewrite action -------------------------------------------------------

def test_rewrite_with_raw_data_overwrites_payload():
    frame = Frame(arbitration_id=0x100, data=[1, 2, 3])
    rules = [{"id": "r1", "action": "rewrite", "match": {"arbitration_id": 0x100},
              "rewrite": {"data": "AA BB"}}]
    decision = apply_rules(frame, rules, "a_to_b")
    assert decision.action == "rewrite"
    assert decision.frame.data == [0xAA, 0xBB]
    assert decision.frame.arbitration_id == 0x100


def test_rewrite_via_dbc_merges_current_signals_with_overrides(monkeypatch):
    decode_calls = []
    encode_calls = []

    def fake_decode(dbc_text, arbitration_id, data):
        decode_calls.append((arbitration_id, bytes(data)))
        return {"SPEED": 10, "GEAR": 3}

    def fake_encode(dbc_text, message, signals, counter=None, checksum=""):
        encode_calls.append((message, dict(signals)))
        return [9, 9]

    monkeypatch.setattr("app.can.dbc.decode", fake_decode)
    monkeypatch.setattr("app.can.dbc.encode", fake_encode)
    frame = Frame(arbitration_id=0x200, data=[1, 2])
    rules = [{
        "id": "r1", "action": "rewrite", "match": {"arbitration_id": 0x200},
        "rewrite": {"database_id": 1, "message": "SPEED_MSG", "signals": {"SPEED": 99}},
    }]
    decision = apply_rules(frame, rules, "a_to_b", dbc_lookup=lambda db_id: "fake dbc")
    assert decision.action == "rewrite"
    assert decision.frame.data == [9, 9]
    # The unset GEAR signal from the decoded frame is preserved, only SPEED overridden.
    assert encode_calls == [("SPEED_MSG", {"SPEED": 99, "GEAR": 3})]


def test_rewrite_without_dbc_lookup_passes_through_unmodified():
    frame = Frame(arbitration_id=0x200, data=[1, 2])
    rules = [{
        "id": "r1", "action": "rewrite", "match": {"arbitration_id": 0x200},
        "rewrite": {"database_id": 1, "message": "SPEED_MSG", "signals": {"SPEED": 99}},
    }]
    decision = apply_rules(frame, rules, "a_to_b", dbc_lookup=None)
    assert decision.frame == frame


def test_rewrite_encode_failure_passes_through_unmodified(monkeypatch):
    monkeypatch.setattr("app.can.dbc.decode", lambda *a: {})

    def fake_encode(*a, **k):
        raise ValueError("boom")

    monkeypatch.setattr("app.can.dbc.encode", fake_encode)
    frame = Frame(arbitration_id=0x200, data=[1, 2])
    rules = [{
        "id": "r1", "action": "rewrite", "match": {"arbitration_id": 0x200},
        "rewrite": {"database_id": 1, "message": "SPEED_MSG", "signals": {"SPEED": 99}},
    }]
    decision = apply_rules(frame, rules, "a_to_b", dbc_lookup=lambda db_id: "fake dbc")
    assert decision.frame == frame


# -- inject action --------------------------------------------------------

def test_inject_passes_original_frame_and_emits_extra():
    frame = Frame(arbitration_id=0x100, data=[1])
    rules = [{
        "id": "r1", "action": "inject", "match": {"arbitration_id": 0x100},
        "inject": {"arbitration_id": "0x200", "data": "AA BB"},
    }]
    decision = apply_rules(frame, rules, "a_to_b")
    assert decision.action == "inject"
    assert decision.frame == frame
    assert len(decision.injected) == 1
    assert decision.injected[0].arbitration_id == 0x200
    assert decision.injected[0].data == [0xAA, 0xBB]


def test_inject_with_invalid_spec_emits_nothing():
    frame = Frame(arbitration_id=0x100, data=[1])
    rules = [{
        "id": "r1", "action": "inject", "match": {"arbitration_id": 0x100},
        "inject": {"arbitration_id": "0x200", "data": "00 " * 9},  # invalid classic length
    }]
    decision = apply_rules(frame, rules, "a_to_b")
    assert decision.action == "inject"
    assert decision.frame == frame
    assert decision.injected == []


def test_inject_missing_arbitration_id_emits_nothing():
    frame = Frame(arbitration_id=0x100, data=[1])
    rules = [{"id": "r1", "action": "inject", "match": {"arbitration_id": 0x100}, "inject": {}}]
    decision = apply_rules(frame, rules, "a_to_b")
    assert decision.injected == []


# -- rule persistence -----------------------------------------------------

def test_create_list_get_rule_roundtrip():
    created = fw.create_rule({"name": "A", "action": "allow", "match": {}})
    assert created["id"]
    assert fw.get_rule(created["id"])["name"] == "A"
    assert [r["id"] for r in fw.list_rules()] == [created["id"]]


def test_update_rule_merges_fields():
    created = fw.create_rule({"name": "A", "action": "allow"})
    updated = fw.update_rule(created["id"], {"name": "B"})
    assert updated["name"] == "B"
    assert updated["action"] == "allow"


def test_update_missing_rule_returns_none():
    assert fw.update_rule("nope", {"name": "x"}) is None


def test_delete_rule_removes_it():
    created = fw.create_rule({"name": "A", "action": "allow"})
    assert fw.delete_rule(created["id"]) is True
    assert fw.get_rule(created["id"]) is None


def test_delete_missing_rule_returns_false():
    assert fw.delete_rule("nope") is False


def test_reorder_rules_sets_explicit_order():
    r1 = fw.create_rule({"name": "first"})
    r2 = fw.create_rule({"name": "second"})
    reordered = fw.reorder_rules([r2["id"], r1["id"]])
    assert [r["id"] for r in reordered] == [r2["id"], r1["id"]]


def test_reorder_appends_unlisted_rules_after_named_ones():
    r1 = fw.create_rule({"name": "first"})
    r2 = fw.create_rule({"name": "second"})
    reordered = fw.reorder_rules([r2["id"]])
    assert [r["id"] for r in reordered] == [r2["id"], r1["id"]]


# -- config persistence -----------------------------------------------------

def test_get_config_defaults():
    cfg = fw.get_config()
    assert cfg["channel_a"] == "can0"
    assert cfg["channel_b"] == "can1"
    assert cfg["forward_a_to_b"] is True


def test_update_config_merges_and_ignores_rules_key():
    fw.create_rule({"name": "should stay"})
    fw.update_config({"channel_a": "can2", "rules": []})
    cfg = fw.get_config()
    assert cfg["channel_a"] == "can2"
    assert len(cfg["rules"]) == 1  # untouched by the config update


# -- gateway engine ---------------------------------------------------------

def _engine_with_fakes(rules=None, same_channels=False):
    sent = []

    def sender(backend, channel, frame):
        sent.append((backend, channel, frame))
        return True

    channel_b = "can0" if same_channels else "can1"
    config = {
        "channel_a": "can0", "backend_a": "socketcan",
        "channel_b": channel_b, "backend_b": "socketcan",
        "forward_a_to_b": True, "forward_b_to_a": True,
    }
    engine = GatewayEngine(
        config_resolver=lambda: config,
        rules_resolver=lambda: (rules or []),
        sender=sender,
    )
    return engine, sent, config


def test_start_fails_when_channels_are_the_same():
    engine, sent, config = _engine_with_fakes(same_channels=True)
    ok, error = engine.start()
    assert ok is False
    assert "two different" in error
    assert engine.is_running() is False


def test_start_fails_when_no_direction_enabled():
    config = {
        "channel_a": "can0", "backend_a": "socketcan",
        "channel_b": "can1", "backend_b": "socketcan",
        "forward_a_to_b": False, "forward_b_to_a": False,
    }
    engine = GatewayEngine(config_resolver=lambda: config, rules_resolver=list)
    ok, error = engine.start()
    assert ok is False
    assert "at least one direction" in error


def test_start_stop_toggles_running():
    engine, sent, config = _engine_with_fakes()

    class _FakeProvider:
        available = False

        def recv(self, timeout=None):
            return None

    engine._get_channel = lambda *a, **k: _FakeProvider()
    assert engine.is_running() is False
    ok, error = engine.start()
    assert ok is True
    assert error is None
    assert engine.is_running() is True
    ok2, error2 = engine.start()
    assert ok2 is False
    assert engine.stop() is True
    assert engine.is_running() is False
    assert engine.stop() is False


def test_status_reports_needs_two_interfaces():
    engine, sent, config = _engine_with_fakes(same_channels=True)
    status = engine.status()
    assert status["needs_two_interfaces"] is True


def test_status_reports_live_flags_from_providers():
    engine, sent, config = _engine_with_fakes()

    class _FakeProvider:
        def __init__(self, live):
            self.available = live

    def factory(channel, backend="socketcan"):
        return _FakeProvider(channel == "can0")

    engine._get_channel = factory
    status = engine.status()
    assert status["live_a"] is True
    assert status["live_b"] is False


def test_gateway_forwards_frame_and_counts_stats():
    rules = []
    engine, sent, config = _engine_with_fakes(rules=rules)

    class _OneShotProvider:
        available = True

        def __init__(self):
            self._sent_one = False

        def recv(self, timeout=None):
            if self._sent_one:
                return None
            self._sent_one = True
            return Frame(arbitration_id=0x100, data=[1, 2])

    engine._get_channel = lambda *a, **k: _OneShotProvider()
    engine.start()
    import time
    deadline = time.time() + 2.0
    while time.time() < deadline and not sent:
        time.sleep(0.02)
    engine.stop()
    assert len(sent) >= 1
    assert sent[0][2].arbitration_id == 0x100
    assert engine._stats["forwarded"] >= 1


# -- router ---------------------------------------------------------------

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_router_config_get_and_put(client):
    resp = client.get("/firewall/config")
    assert resp.status_code == 200
    assert resp.json()["channel_a"] == "can0"

    resp = client.put("/firewall/config", json={"channel_a": "can2"})
    assert resp.status_code == 200
    assert resp.json()["channel_a"] == "can2"


def test_router_rules_crud(client):
    created = client.post("/firewall/rules", json={
        "name": "Block diag", "action": "block",
        "match": {"arbitration_id": 0x700},
    })
    assert created.status_code == 200, created.text
    rule_id = created.json()["rule"]["id"]

    listed = client.get("/firewall/rules").json()
    assert any(r["id"] == rule_id for r in listed["rules"])

    got = client.get(f"/firewall/rules/{rule_id}")
    assert got.status_code == 200

    updated = client.put(f"/firewall/rules/{rule_id}", json={
        "name": "Block diag v2", "action": "block", "match": {"arbitration_id": 0x700},
    })
    assert updated.status_code == 200
    assert updated.json()["rule"]["name"] == "Block diag v2"

    deleted = client.delete(f"/firewall/rules/{rule_id}")
    assert deleted.status_code == 200
    assert client.get(f"/firewall/rules/{rule_id}").status_code == 404


def test_router_rule_bad_direction_400s(client):
    resp = client.post("/firewall/rules", json={"name": "x", "direction": "sideways"})
    assert resp.status_code == 400


def test_router_rule_bad_action_400s(client):
    resp = client.post("/firewall/rules", json={"name": "x", "action": "nope"})
    assert resp.status_code == 400


def test_router_rule_unknown_database_404s(client):
    resp = client.post("/firewall/rules", json={
        "name": "x", "action": "block", "match": {"database_id": 999, "signal": "S"},
    })
    assert resp.status_code == 404


def test_router_rules_reorder(client):
    r1 = client.post("/firewall/rules", json={"name": "first"}).json()["rule"]
    r2 = client.post("/firewall/rules", json={"name": "second"}).json()["rule"]
    resp = client.post("/firewall/rules/reorder", json={"rule_ids": [r2["id"], r1["id"]]})
    assert resp.status_code == 200
    assert [r["id"] for r in resp.json()["rules"]] == [r2["id"], r1["id"]]


def test_router_delete_missing_rule_404s(client):
    assert client.delete("/firewall/rules/nope").status_code == 404


def test_router_update_missing_rule_404s(client):
    resp = client.put("/firewall/rules/nope", json={"name": "x"})
    assert resp.status_code == 404


def test_router_gateway_start_stop_status_degraded(client):
    # Default config has can0/can1 as distinct channels, no real hardware:
    # start should succeed (both directions enabled) but report not live.
    resp = client.post("/firewall/start")
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True

    status = client.get("/firewall/status").json()
    assert status["running"] is True
    assert status["live_a"] is False
    assert status["live_b"] is False

    stop = client.post("/firewall/stop")
    assert stop.status_code == 200
    assert stop.json()["stopped"] is True


def test_router_gateway_start_same_channel_400s(client):
    client.put("/firewall/config", json={"channel_a": "can0", "channel_b": "can0"})
    resp = client.post("/firewall/start")
    assert resp.status_code == 400
    assert "two different" in resp.json()["detail"]


def test_ui_page_renders(client):
    resp = client.get("/ui/firewall")
    assert resp.status_code == 200
    assert "CAN Firewall" in resp.text
