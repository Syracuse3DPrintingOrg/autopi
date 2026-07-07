"""Tests for the pure, scan-based PLC-like logic engine."""
from app.logic.conditions import evaluate_condition
from app.logic.engine import Engine, ScanResult
from app.logic.rule import Rule


# --- condition evaluation -----------------------------------------------


def test_compare_operators():
    inputs = {"temp": 100}
    assert evaluate_condition({"type": "compare", "signal": "temp", "op": ">", "value": 90}, inputs, {}, 0.0)
    assert not evaluate_condition({"type": "compare", "signal": "temp", "op": "<", "value": 90}, inputs, {}, 0.0)
    assert evaluate_condition({"type": "compare", "signal": "temp", "op": ">=", "value": 100}, inputs, {}, 0.0)
    assert evaluate_condition({"type": "compare", "signal": "temp", "op": "<=", "value": 100}, inputs, {}, 0.0)
    assert evaluate_condition({"type": "compare", "signal": "temp", "op": "==", "value": 100}, inputs, {}, 0.0)
    assert evaluate_condition({"type": "compare", "signal": "temp", "op": "!=", "value": 1}, inputs, {}, 0.0)


def test_compare_missing_signal_is_false():
    cond = {"type": "compare", "signal": "ghost", "op": "==", "value": 1}
    assert evaluate_condition(cond, {}, {}, 0.0) is False


def test_compare_unknown_op_raises():
    cond = {"type": "compare", "signal": "x", "op": "~=", "value": 1}
    try:
        evaluate_condition(cond, {"x": 1}, {}, 0.0)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_bool_input_and_negate():
    cond = {"type": "bool", "signal": "door_open"}
    assert evaluate_condition(cond, {"door_open": True}, {}, 0.0) is True
    assert evaluate_condition(cond, {"door_open": False}, {}, 0.0) is False
    assert evaluate_condition(cond, {}, {}, 0.0) is False  # missing -> falsy

    negated = {"type": "bool", "signal": "door_open", "negate": True}
    assert evaluate_condition(negated, {"door_open": True}, {}, 0.0) is False
    assert evaluate_condition(negated, {"door_open": False}, {}, 0.0) is True


def test_and_or_not_combinators():
    a = {"type": "bool", "signal": "a"}
    b = {"type": "bool", "signal": "b"}

    and_cond = {"type": "and", "conditions": [a, b]}
    assert evaluate_condition(and_cond, {"a": True, "b": True}, {}, 0.0) is True
    assert evaluate_condition(and_cond, {"a": True, "b": False}, {}, 0.0) is False

    or_cond = {"type": "or", "conditions": [a, b]}
    assert evaluate_condition(or_cond, {"a": False, "b": True}, {}, 0.0) is True
    assert evaluate_condition(or_cond, {"a": False, "b": False}, {}, 0.0) is False

    not_cond = {"type": "not", "condition": a}
    assert evaluate_condition(not_cond, {"a": True}, {}, 0.0) is False
    assert evaluate_condition(not_cond, {"a": False}, {}, 0.0) is True

    nested = {"type": "and", "conditions": [or_cond, {"type": "not", "condition": b}]}
    assert evaluate_condition(nested, {"a": True, "b": False}, {}, 0.0) is True
    assert evaluate_condition(nested, {"a": True, "b": True}, {}, 0.0) is False


def test_and_does_not_short_circuit_stateful_children():
    # Two edge detectors under an AND: even when the first child is false
    # (killing the AND's overall result), the second child's edge memory
    # must still update every scan, or it will misfire once the AND becomes
    # relevant again.
    always_false = {"type": "bool", "signal": "gate"}
    edge = {"type": "edge", "id": "e1", "signal": "button", "edge": "rising"}
    cond = {"type": "and", "conditions": [always_false, edge]}
    state = {}

    # Scan 1: button goes true for the first time, but gate is false so the
    # AND is false. The edge's "previous" memory must still update to True.
    assert evaluate_condition(cond, {"gate": False, "button": True}, state, 0.0) is False
    assert state["e1"] is True

    # Scan 2: button stays true (no new rising edge) and gate flips true.
    # If the edge state had not updated in scan 1, this would incorrectly
    # register a rising edge now.
    assert evaluate_condition(cond, {"gate": True, "button": True}, state, 1.0) is False


# --- edge detection ------------------------------------------------------


def test_rising_edge_detection():
    cond = {"type": "edge", "id": "e1", "signal": "btn", "edge": "rising"}
    state = {}
    assert evaluate_condition(cond, {"btn": False}, state, 0.0) is False
    assert evaluate_condition(cond, {"btn": True}, state, 1.0) is True   # rising here
    assert evaluate_condition(cond, {"btn": True}, state, 2.0) is False  # held, not a new edge
    assert evaluate_condition(cond, {"btn": False}, state, 3.0) is False
    assert evaluate_condition(cond, {"btn": True}, state, 4.0) is True   # rising again


def test_falling_edge_detection():
    cond = {"type": "edge", "id": "e1", "signal": "btn", "edge": "falling"}
    state = {}
    assert evaluate_condition(cond, {"btn": True}, state, 0.0) is False
    assert evaluate_condition(cond, {"btn": False}, state, 1.0) is True   # falling here
    assert evaluate_condition(cond, {"btn": False}, state, 2.0) is False  # held low


# --- TON / TOF timers -----------------------------------------------------


def test_ton_timer_delays_the_rise_and_drops_immediately():
    cond = {
        "type": "timer",
        "id": "t1",
        "mode": "TON",
        "duration": 5.0,
        "input": {"type": "bool", "signal": "run"},
    }
    state = {}
    assert evaluate_condition(cond, {"run": True}, state, 0.0) is False   # just started
    assert evaluate_condition(cond, {"run": True}, state, 3.0) is False   # not yet
    assert evaluate_condition(cond, {"run": True}, state, 5.0) is True    # exactly at duration
    assert evaluate_condition(cond, {"run": True}, state, 9.0) is True    # still true

    # Input drops: TON output drops immediately, no delay on the way down.
    assert evaluate_condition(cond, {"run": False}, state, 9.5) is False

    # Restart the timer: must wait the full duration again.
    assert evaluate_condition(cond, {"run": True}, state, 10.0) is False
    assert evaluate_condition(cond, {"run": True}, state, 14.9) is False
    assert evaluate_condition(cond, {"run": True}, state, 15.0) is True


def test_ton_timer_resets_if_input_drops_before_elapsed():
    cond = {
        "type": "timer",
        "id": "t1",
        "mode": "TON",
        "duration": 5.0,
        "input": {"type": "bool", "signal": "run"},
    }
    state = {}
    assert evaluate_condition(cond, {"run": True}, state, 0.0) is False
    assert evaluate_condition(cond, {"run": False}, state, 2.0) is False  # dropped early, resets
    assert evaluate_condition(cond, {"run": True}, state, 2.5) is False   # anchor restarts at 2.5
    assert evaluate_condition(cond, {"run": True}, state, 6.5) is False   # only 4s elapsed
    assert evaluate_condition(cond, {"run": True}, state, 7.5) is True    # 5s elapsed


def test_tof_timer_holds_true_after_input_drops():
    cond = {
        "type": "timer",
        "id": "t1",
        "mode": "TOF",
        "duration": 3.0,
        "input": {"type": "bool", "signal": "run"},
    }
    state = {}
    assert evaluate_condition(cond, {"run": True}, state, 0.0) is True    # true immediately
    assert evaluate_condition(cond, {"run": True}, state, 1.0) is True
    assert evaluate_condition(cond, {"run": False}, state, 2.0) is True   # held: just dropped
    assert evaluate_condition(cond, {"run": False}, state, 4.5) is True   # still within 3s
    assert evaluate_condition(cond, {"run": False}, state, 5.0) is False  # 3s elapsed, falls

    # Input comes back true before falling: immediately true again, and the
    # off-delay anchor is cleared.
    assert evaluate_condition(cond, {"run": True}, state, 5.5) is True
    assert evaluate_condition(cond, {"run": False}, state, 6.0) is True
    assert evaluate_condition(cond, {"run": False}, state, 8.9) is True
    assert evaluate_condition(cond, {"run": False}, state, 9.0) is False


def test_unknown_timer_mode_raises():
    cond = {
        "type": "timer", "id": "t1", "mode": "XYZ", "duration": 1.0,
        "input": {"type": "bool", "signal": "run"},
    }
    try:
        evaluate_condition(cond, {"run": True}, {}, 0.0)
        assert False, "expected ValueError"
    except ValueError:
        pass


# --- RS / SR latches -------------------------------------------------------


def test_latch_set_dominant_wins_a_tie():
    cond = {
        "type": "latch", "id": "l1", "kind": "set_dominant",
        "set": {"type": "bool", "signal": "s"},
        "reset": {"type": "bool", "signal": "r"},
    }
    state = {}
    assert evaluate_condition(cond, {"s": True, "r": False}, state, 0.0) is True
    assert evaluate_condition(cond, {"s": False, "r": False}, state, 1.0) is True   # holds
    assert evaluate_condition(cond, {"s": False, "r": True}, state, 2.0) is False   # reset
    assert evaluate_condition(cond, {"s": False, "r": False}, state, 3.0) is False  # holds low
    # Both true simultaneously: set wins.
    assert evaluate_condition(cond, {"s": True, "r": True}, state, 4.0) is True


def test_latch_reset_dominant_wins_a_tie():
    cond = {
        "type": "latch", "id": "l1", "kind": "reset_dominant",
        "set": {"type": "bool", "signal": "s"},
        "reset": {"type": "bool", "signal": "r"},
    }
    state = {}
    assert evaluate_condition(cond, {"s": True, "r": False}, state, 0.0) is True
    # Both true simultaneously: reset wins this time.
    assert evaluate_condition(cond, {"s": True, "r": True}, state, 1.0) is False


def test_unknown_latch_kind_raises():
    cond = {
        "type": "latch", "id": "l1", "kind": "banana",
        "set": {"type": "bool", "signal": "s"},
        "reset": {"type": "bool", "signal": "r"},
    }
    try:
        evaluate_condition(cond, {"s": True, "r": False}, {}, 0.0)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_unknown_condition_type_raises():
    try:
        evaluate_condition({"type": "mystery"}, {}, {}, 0.0)
        assert False, "expected ValueError"
    except ValueError:
        pass


# --- Rule (de)serialization ------------------------------------------------


def test_rule_round_trips_through_dict():
    rule = Rule(
        id="r1",
        name="Fan on when hot",
        condition={"type": "compare", "signal": "temp", "op": ">", "value": 80},
        actions=["fan_on"],
        trigger="rising",
        enabled=True,
    )
    restored = Rule.from_dict(rule.to_dict())
    assert restored == rule


def test_rule_from_dict_ignores_unknown_fields_and_fills_defaults():
    rule = Rule.from_dict({"id": "r1", "bogus_field": 123})
    assert rule.id == "r1"
    assert rule.actions == []
    assert rule.trigger == "level"
    assert rule.enabled is True


# --- Engine.scan ------------------------------------------------------------


def test_scan_level_trigger_fires_every_scan_while_true():
    rule = Rule(
        id="r1",
        condition={"type": "bool", "signal": "on"},
        actions=["light_on"],
        trigger="level",
    )
    engine = Engine([rule])

    result = engine.scan({"on": True}, now=0.0)
    assert isinstance(result, ScanResult)
    assert result.outputs == {"r1": True}
    assert result.fire == ["light_on"]

    result = engine.scan({"on": True}, now=1.0)
    assert result.fire == ["light_on"]  # still firing every scan while true

    result = engine.scan({"on": False}, now=2.0)
    assert result.outputs == {"r1": False}
    assert result.fire == []


def test_scan_rising_trigger_fires_once_per_transition():
    rule = Rule(
        id="r1",
        condition={"type": "bool", "signal": "on"},
        actions=["ping"],
        trigger="rising",
    )
    engine = Engine([rule])

    assert engine.scan({"on": False}, now=0.0).fire == []
    assert engine.scan({"on": True}, now=1.0).fire == ["ping"]   # rising edge
    assert engine.scan({"on": True}, now=2.0).fire == []          # held, no re-fire
    assert engine.scan({"on": False}, now=3.0).fire == []
    assert engine.scan({"on": True}, now=4.0).fire == ["ping"]   # rising again


def test_scan_falling_trigger():
    rule = Rule(
        id="r1",
        condition={"type": "bool", "signal": "on"},
        actions=["cleanup"],
        trigger="falling",
    )
    engine = Engine([rule])
    assert engine.scan({"on": True}, now=0.0).fire == []
    assert engine.scan({"on": False}, now=1.0).fire == ["cleanup"]
    assert engine.scan({"on": False}, now=2.0).fire == []


def test_scan_disabled_rule_never_fires_and_reports_false():
    rule = Rule(
        id="r1",
        condition={"type": "bool", "signal": "on"},
        actions=["boom"],
        enabled=False,
    )
    engine = Engine([rule])
    result = engine.scan({"on": True}, now=0.0)
    assert result.outputs == {"r1": False}
    assert result.fire == []


def test_multi_rule_scan_combines_outputs_and_firings():
    rules = [
        Rule(id="temp_high", condition={"type": "compare", "signal": "temp", "op": ">", "value": 90},
             actions=["fan_on"], trigger="level"),
        Rule(id="door_opened", condition={"type": "edge", "id": "door_edge", "signal": "door", "edge": "rising"},
             actions=["chime"], trigger="level"),
        Rule(id="motion_latched",
             condition={"type": "latch", "id": "motion_latch", "kind": "set_dominant",
                        "set": {"type": "bool", "signal": "motion"},
                        "reset": {"type": "bool", "signal": "clear"}},
             actions=["light_on"], trigger="level"),
    ]
    engine = Engine(rules)

    result = engine.scan({"temp": 95, "door": False, "motion": False, "clear": False}, now=0.0)
    assert result.outputs == {"temp_high": True, "door_opened": False, "motion_latched": False}
    assert result.fire == ["fan_on"]

    result = engine.scan({"temp": 95, "door": True, "motion": True, "clear": False}, now=1.0)
    assert result.outputs == {"temp_high": True, "door_opened": True, "motion_latched": True}
    assert set(result.fire) == {"fan_on", "chime", "light_on"}

    result = engine.scan({"temp": 50, "door": True, "motion": False, "clear": True}, now=2.0)
    # temp dropped (rule false), door held open (no new edge), latch reset.
    assert result.outputs == {"temp_high": False, "door_opened": False, "motion_latched": False}
    assert result.fire == []


def test_scan_is_deterministic_given_the_same_injected_now():
    # No wall clock anywhere: replaying identical inputs/now must produce
    # identical results, proving there is no hidden time dependency.
    def build():
        return Engine([Rule(
            id="delayed",
            condition={
                "type": "timer", "id": "ton", "mode": "TON", "duration": 2.0,
                "input": {"type": "bool", "signal": "go"},
            },
            actions=["go_action"],
        )])

    engine_a = build()
    engine_b = build()
    schedule = [(0.0, False), (1.0, True), (2.0, True), (3.0, True), (4.0, False)]

    results_a = [engine_a.scan({"go": v}, now=t) for t, v in schedule]
    results_b = [engine_b.scan({"go": v}, now=t) for t, v in schedule]
    assert results_a == results_b


def test_add_and_remove_rule():
    engine = Engine()
    rule = Rule(id="r1", condition={"type": "bool", "signal": "x"}, actions=["a"])
    engine.add_rule(rule)
    assert engine.scan({"x": True}, now=0.0).fire == ["a"]

    assert engine.remove_rule("r1") is True
    assert engine.remove_rule("r1") is False  # already gone
    assert engine.scan({"x": True}, now=1.0).outputs == {}


def test_reset_clears_stateful_memory():
    rule = Rule(
        id="r1",
        condition={"type": "edge", "id": "e1", "signal": "btn", "edge": "rising"},
        actions=["ping"],
    )
    engine = Engine([rule])
    engine.scan({"btn": True}, now=0.0)  # e1 memory now True
    engine.reset()
    # After reset, a still-true signal should register as a fresh rising edge.
    result = engine.scan({"btn": True}, now=1.0)
    assert result.fire == ["ping"]
