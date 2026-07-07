"""Pure condition evaluation.

A condition is a plain, JSON-serializable dict tree. Every node has a
``type`` key that selects one of the evaluators below. Comparisons and
boolean inputs are stateless; edges, timers, and latches carry their own
``id`` and keep state across scans in the ``state`` dict the caller passes
in (the :class:`~.engine.Engine` owns that dict so it survives between
calls to ``scan``).

Node shapes:

- ``{"type": "compare", "signal": "temp_c", "op": ">", "value": 90}``
  Compares ``inputs[signal]`` against ``value`` with one of
  ``==, !=, <, <=, >, >=``. A missing signal evaluates to ``False`` rather
  than raising, since a scan should never crash on an input that has not
  arrived yet.
- ``{"type": "bool", "signal": "door_open", "negate": false}``
  Truthiness of a named input, optionally inverted.
- ``{"type": "edge", "id": "e1", "signal": "button", "edge": "rising"}``
  ``edge`` is ``"rising"`` or ``"falling"``. True only on the single scan
  where the signal's boolean value changes in that direction.
- ``{"type": "timer", "id": "t1", "mode": "TON", "duration": 5.0,
  "input": <condition>}``
  ``TON`` (on-delay) goes true ``duration`` seconds after ``input`` becomes
  true, and drops immediately when ``input`` goes false. ``TOF``
  (off-delay) is true immediately while ``input`` is true and stays true for
  ``duration`` seconds after ``input`` drops.
- ``{"type": "latch", "id": "l1", "kind": "set_dominant", "set": <condition>,
  "reset": <condition>}``
  A bistable RS/SR latch. ``kind`` is ``"set_dominant"`` (SR: if both set and
  reset are true in the same scan, the output ends up set) or
  ``"reset_dominant"`` (RS: reset wins a tie).
- ``{"type": "and", "conditions": [<condition>, ...]}``
- ``{"type": "or", "conditions": [<condition>, ...]}``
- ``{"type": "not", "condition": <condition>}``

AND/OR always evaluate every child, with no short-circuiting. A stateful
condition (edge/timer/latch) nested inside an AND/OR must update its state
every scan regardless of the sibling values, or its notion of "previous
scan" would skip scans and misfire later. This mirrors how a real PLC scans
every rung element on every cycle.
"""
from __future__ import annotations

import operator
from typing import Any, Callable

Inputs = dict[str, Any]
State = dict[str, Any]

_COMPARE_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "==": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}


def _eval_compare(cond: dict, inputs: Inputs, state: State, now: float) -> bool:
    signal = cond["signal"]
    if signal not in inputs:
        return False
    op = cond.get("op", "==")
    fn = _COMPARE_OPS.get(op)
    if fn is None:
        raise ValueError(f"Unknown compare operator: {op}")
    return bool(fn(inputs[signal], cond.get("value")))


def _eval_bool(cond: dict, inputs: Inputs, state: State, now: float) -> bool:
    value = bool(inputs.get(cond["signal"], False))
    return (not value) if cond.get("negate") else value


def _eval_edge(cond: dict, inputs: Inputs, state: State, now: float) -> bool:
    node_id = cond["id"]
    current = bool(inputs.get(cond["signal"], False))
    previous = bool(state.get(node_id, False))
    state[node_id] = current
    edge = cond.get("edge", "rising")
    if edge == "rising":
        return current and not previous
    if edge == "falling":
        return previous and not current
    raise ValueError(f"Unknown edge direction: {edge}")


def _eval_timer(cond: dict, inputs: Inputs, state: State, now: float) -> bool:
    node_id = cond["id"]
    mode = cond.get("mode", "TON")
    duration = float(cond["duration"])
    input_value = evaluate_condition(cond["input"], inputs, state, now)

    slot = state.get(node_id)
    if not isinstance(slot, dict):
        slot = {"anchor": None}
        state[node_id] = slot

    if mode == "TON":
        # Rises `duration` seconds after the input goes true; drops the
        # instant the input goes false (no delay on the way down).
        if input_value:
            if slot["anchor"] is None:
                slot["anchor"] = now
            return (now - slot["anchor"]) >= duration
        slot["anchor"] = None
        return False

    if mode == "TOF":
        # True immediately while the input is true; stays true for
        # `duration` seconds after the input drops, then falls.
        if input_value:
            slot["anchor"] = None
            return True
        if slot["anchor"] is None:
            slot["anchor"] = now
        return (now - slot["anchor"]) < duration

    raise ValueError(f"Unknown timer mode: {mode}")


def _eval_latch(cond: dict, inputs: Inputs, state: State, now: float) -> bool:
    node_id = cond["id"]
    kind = cond.get("kind", "set_dominant")
    set_value = evaluate_condition(cond["set"], inputs, state, now)
    reset_value = evaluate_condition(cond["reset"], inputs, state, now)

    current = bool(state.get(node_id, False))
    if kind == "set_dominant":
        if set_value:
            current = True
        elif reset_value:
            current = False
    elif kind == "reset_dominant":
        if reset_value:
            current = False
        elif set_value:
            current = True
    else:
        raise ValueError(f"Unknown latch kind: {kind}")

    state[node_id] = current
    return current


def _eval_and(cond: dict, inputs: Inputs, state: State, now: float) -> bool:
    # No short-circuiting: every child must be evaluated so stateful
    # children (edges/timers/latches) update on every scan.
    results = [evaluate_condition(c, inputs, state, now) for c in cond["conditions"]]
    return all(results)


def _eval_or(cond: dict, inputs: Inputs, state: State, now: float) -> bool:
    results = [evaluate_condition(c, inputs, state, now) for c in cond["conditions"]]
    return any(results)


def _eval_not(cond: dict, inputs: Inputs, state: State, now: float) -> bool:
    return not evaluate_condition(cond["condition"], inputs, state, now)


_EVALUATORS: dict[str, Callable[[dict, Inputs, State, float], bool]] = {
    "compare": _eval_compare,
    "bool": _eval_bool,
    "edge": _eval_edge,
    "timer": _eval_timer,
    "latch": _eval_latch,
    "and": _eval_and,
    "or": _eval_or,
    "not": _eval_not,
}


def evaluate_condition(cond: dict, inputs: Inputs, state: State, now: float) -> bool:
    """Evaluate a condition node against this scan's inputs.

    ``state`` is mutated in place for stateful node types (edge/timer/latch)
    and is expected to persist across calls (the engine owns one ``state``
    dict for the whole rule set, keyed by each stateful node's own ``id``,
    so ids must be unique across the rule set).
    """
    node_type = cond.get("type")
    evaluator = _EVALUATORS.get(node_type)
    if evaluator is None:
        raise ValueError(f"Unknown condition type: {node_type!r}")
    return evaluator(cond, inputs, state, now)
