"""Automated test sequences: a step model, pure step evaluation, a runner,
and JSON-file persistence.

A :class:`Sequence` is an ordered list of :class:`Step` (send a CAN command,
expect a response, prompt the operator, delay, or run an existing action).
:class:`Runner` steps through one sequence and records a pass/fail result per
step; :mod:`app.testseq.evaluation` holds the pure matching and pass/fail
decisions so they are unit-testable with injected frames and a synthetic
clock, no real hardware or threads required.
"""
from __future__ import annotations

from .evaluation import compare_value, evaluate_delay, match_expect, resolve_confirm
from .model import COMPARE_OPS, STEP_TYPES, Sequence, Step
from .runner import Runner, StepResult, get_active, reset_active, run_sequence
from .store import (
    create_sequence,
    delete_sequence,
    get_sequence,
    list_sequences,
    update_sequence,
)

__all__ = [
    "COMPARE_OPS",
    "STEP_TYPES",
    "Runner",
    "Sequence",
    "Step",
    "StepResult",
    "compare_value",
    "create_sequence",
    "delete_sequence",
    "evaluate_delay",
    "get_active",
    "get_sequence",
    "list_sequences",
    "match_expect",
    "reset_active",
    "resolve_confirm",
    "run_sequence",
    "update_sequence",
]
