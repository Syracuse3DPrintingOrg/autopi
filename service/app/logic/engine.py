"""The scan engine.

``Engine.scan`` is the entire runtime contract: give it this cycle's inputs
and the current time, and it returns each rule's output plus which action
ids should fire. All state that must survive between scans (edge memory,
timer anchors, latch bits, and each rule's previous output for edge-gated
firing) lives on the engine instance and is only ever touched inside
``scan``, so calling it repeatedly with deterministic inputs and clock
values produces deterministic, replayable results. Nothing in this module
performs I/O or reads the wall clock.
"""
from __future__ import annotations

from typing import Any, NamedTuple

from .conditions import evaluate_condition
from .rule import Rule


class ScanResult(NamedTuple):
    """The result of one scan cycle.

    Supports both attribute access (``result.outputs``) and tuple unpacking
    (``outputs, fire = engine.scan(...)``).
    """

    outputs: dict[str, bool]
    fire: list[str]


class Engine:
    """Holds a set of rules and evaluates them one scan cycle at a time."""

    def __init__(self, rules: list[Rule] | None = None) -> None:
        self.rules: list[Rule] = list(rules) if rules else []
        # Keyed by each stateful condition node's own `id` (edges, timers,
        # latches); shared across all rules, so those ids must be unique
        # across the whole rule set.
        self._condition_state: dict[str, Any] = {}
        # Keyed by rule id: the output from the previous scan, used to
        # detect rising/falling transitions for edge-gated firing.
        self._previous_outputs: dict[str, bool] = {}

    def add_rule(self, rule: Rule) -> None:
        self.rules.append(rule)

    def remove_rule(self, rule_id: str) -> bool:
        before = len(self.rules)
        self.rules = [r for r in self.rules if r.id != rule_id]
        return len(self.rules) != before

    def reset(self) -> None:
        """Clear all cross-scan state (timers, edges, latches, transitions)."""
        self._condition_state.clear()
        self._previous_outputs.clear()

    def scan(self, inputs: dict[str, Any], now: float) -> ScanResult:
        """Evaluate every enabled rule once and report outputs plus firings."""
        outputs: dict[str, bool] = {}
        fire: list[str] = []

        for rule in self.rules:
            if not rule.enabled:
                outputs[rule.id] = False
                self._previous_outputs[rule.id] = False
                continue

            result = bool(
                evaluate_condition(rule.condition, inputs, self._condition_state, now)
            )
            outputs[rule.id] = result
            previous = self._previous_outputs.get(rule.id, False)

            if rule.trigger == "level":
                should_fire = result
            elif rule.trigger == "rising":
                should_fire = result and not previous
            elif rule.trigger == "falling":
                should_fire = previous and not result
            else:
                raise ValueError(f"Unknown rule trigger: {rule.trigger!r}")

            if should_fire:
                fire.extend(rule.actions)

            self._previous_outputs[rule.id] = result

        return ScanResult(outputs=outputs, fire=fire)
