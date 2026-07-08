"""Pure step-evaluation logic: response matching and the pass/fail decision.

Nothing here touches a thread, a clock, or real CAN hardware. Every function
takes the frames, the clock reading, and the DBC text it needs as plain
arguments, so a test drives the exact same decision the runner makes, with
injected frames and a synthetic clock (see ``app.can.monitor.decode_record``
and ``app.can.monitor.ingest_frame`` for the same pattern used by the live
monitor).
"""
from __future__ import annotations

from typing import Any

from ..can.base import parse_arbitration_id
from ..can.monitor import decode_record
from .model import Step

# What match_expect returns for `outcome`: still waiting, matched, or timed
# out without a match.
PENDING = "pending"
PASS = "pass"
FAIL = "fail"


def compare_value(op: str, actual: Any, expected: Any) -> bool:
    """Compare a decoded signal value against an expected value.

    Never raises: a type mismatch (e.g. comparing a string signal choice
    against a number) just means "not a match" rather than blowing up the
    run.
    """
    try:
        if op == "==":
            return actual == expected
        if op == "!=":
            return actual != expected
        if op == "<":
            return actual < expected
        if op == "<=":
            return actual <= expected
        if op == ">":
            return actual > expected
        if op == ">=":
            return actual >= expected
    except TypeError:
        return False
    return False


def match_expect(
    step: Step,
    frames: list[dict[str, Any]],
    dbc_text: str | None,
    started_at: float,
    now: float,
) -> dict[str, Any]:
    """Decide whether an "expect" step has passed, failed, or is still pending.

    ``frames`` is the monitor's frame history (or any list of records shaped
    like it: ``arbitration_id``, ``data``, ``timestamp``). Only frames with
    ``timestamp >= started_at`` are considered, so a frame left over from
    before this step began (or from a previous run) never counts as this
    step's response. When ``step.signal_name`` is set, a candidate frame must
    decode against ``dbc_text`` and satisfy ``step.op``/``step.value``;
    otherwise arrival of any matching-id frame is enough.

    Returns ``{"outcome": "pass"|"fail"|"pending", "message": str, "observed": Any}``.
    """
    try:
        target_id = parse_arbitration_id(step.arbitration_id) if step.arbitration_id else None
    except ValueError:
        return {"outcome": FAIL, "message": f"Bad arbitration id: {step.arbitration_id}", "observed": None}

    elapsed_ms = (now - started_at) * 1000.0
    candidates = [
        f for f in frames
        if f.get("timestamp", 0) >= started_at
        and (target_id is None or f.get("arbitration_id") == target_id)
    ]

    if step.signal_name:
        last_seen = None
        for record in candidates:
            decoded = decode_record(record, dbc_text)
            if not decoded or step.signal_name not in decoded:
                continue
            actual = decoded[step.signal_name]
            last_seen = actual
            if compare_value(step.op, actual, step.value):
                return {
                    "outcome": PASS,
                    "message": f"{step.signal_name} {step.op} {step.value!r} (got {actual!r})",
                    "observed": actual,
                }
        if elapsed_ms >= step.timeout_ms:
            if last_seen is not None:
                message = (
                    f"Timed out after {step.timeout_ms} ms: {step.signal_name} never "
                    f"{step.op} {step.value!r} (last seen {last_seen!r})"
                )
            else:
                message = (
                    f"Timed out after {step.timeout_ms} ms waiting for a frame with "
                    f"signal {step.signal_name}"
                )
            return {"outcome": FAIL, "message": message, "observed": last_seen}
        return {"outcome": PENDING, "message": "Waiting for response", "observed": last_seen}

    if candidates:
        record = candidates[-1]
        return {
            "outcome": PASS,
            "message": f"Received {record.get('hex', '')}".strip(),
            "observed": record.get("data"),
        }
    if elapsed_ms >= step.timeout_ms:
        id_desc = step.arbitration_id or "any id"
        return {
            "outcome": FAIL,
            "message": f"Timed out after {step.timeout_ms} ms waiting for {id_desc}",
            "observed": None,
        }
    return {"outcome": PENDING, "message": "Waiting for response", "observed": None}


def resolve_confirm(step: Step, passed: bool, note: str = "") -> dict[str, Any]:
    """The step result for a "prompt" step once the operator answers.

    Pure: the caller (the runner) is responsible for actually pausing and
    for storing the result; this just turns an operator's pass/fail answer
    into the same result shape the other step types produce.
    """
    outcome = PASS if passed else FAIL
    message = step.prompt_text or "Operator confirmation"
    if note:
        message = f"{message} ({note})"
    return {"outcome": outcome, "message": message, "observed": note or None}


def evaluate_delay(step: Step, started_at: float, now: float) -> dict[str, Any]:
    """Whether a "delay" step's wait has elapsed yet."""
    elapsed_ms = (now - started_at) * 1000.0
    if elapsed_ms >= step.delay_ms:
        return {"outcome": PASS, "message": f"Waited {step.delay_ms} ms", "observed": None}
    return {"outcome": PENDING, "message": "Waiting", "observed": None}
