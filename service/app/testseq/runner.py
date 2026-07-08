"""The test sequence runner: steps through a :class:`~app.testseq.model.Sequence`
one step at a time and records a result for each.

The state-machine decision (what a step's current status is, and whether the
runner can move on to the next one) lives in :meth:`Runner.tick`, which is
pure with respect to the collaborators passed into the constructor: a clock,
a frame source, a DBC text resolver, a frame sender, and an action runner.
That mirrors ``app.can.simulation.SimEngine.tick`` and
``app.can.monitor.MonitorChannel``: a test drives ``tick()`` directly with a
fake clock and injected frames, and the only thing that runs on a real
background thread is a thin loop calling the same ``tick()``.

Only one sequence runs at a time (a test bench validates one vehicle at
once); the module-level singleton at the bottom is what the router and the
UI talk to, the same pattern ``can.simulation.engine`` uses.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from . import evaluation
from .model import Sequence, Step

log = logging.getLogger(__name__)

# How often the background loop calls tick() while a run is in progress.
TICK_SECONDS = 0.05

# Runner-level (not per-step) states.
IDLE = "idle"
RUNNING = "running"
WAITING_CONFIRM = "waiting_confirm"
DONE = "done"

# Per-step states.
STEP_PENDING = "pending"
STEP_RUNNING = "running"
STEP_PASS = "pass"
STEP_FAIL = "fail"
STEP_SKIP = "skip"
STEP_WAITING_CONFIRM = "pending_confirm"


def _log_event(kind: str, message: str, data: dict[str, Any] | None = None) -> None:
    """Best-effort write to the diagnostics journal, if that module exists.

    ``app.services.journal`` is not part of every checkout yet; guard the
    import so the runner records results in its own state either way.
    """
    try:
        from ..services import journal
        journal.log_event(kind, message, data=data)
    except Exception:
        pass


@dataclass
class StepResult:
    step_id: str
    type: str
    label: str = ""
    status: str = STEP_PENDING
    message: str = ""
    observed: Any = None
    started_at: float | None = None
    ended_at: float | None = None
    duration_ms: float | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# -- default collaborators, real CAN/DB/action-registry backed --------------

def _default_clock() -> float:
    return time.monotonic()


def _default_dbc_text_resolver(database_id: int) -> str | None:
    from ..db import session_scope
    from ..db.models import CanDatabase
    with session_scope() as s:
        database = s.get(CanDatabase, database_id)
        return database.dbc_text if database else None


def _default_frame_source(channel: str, backend: str) -> list[dict[str, Any]]:
    from ..can.monitor import get_monitor
    return get_monitor(channel, backend=backend).frames()


def _default_sender(channel: str, backend: str, step: Step, dbc_text: str | None) -> tuple[bool, str]:
    from ..can.registry import get_channel
    from ..can.simulation import build_frame
    entry = {
        "arbitration_id": step.arbitration_id,
        "data": step.data,
        "database_id": step.database_id,
        "message": step.message,
        "signals": step.signals,
        "is_fd": step.is_fd,
        "is_extended_id": step.is_extended_id,
    }
    try:
        frame = build_frame(entry, dbc_text)
    except ValueError as exc:
        return False, str(exc)
    provider = get_channel(channel, backend=backend)
    if not provider.available:
        return True, f"(simulated) would send {frame.format()} on {channel}"
    ok = provider.send(frame)
    return ok, (f"Sent {frame.format()} on {channel}" if ok else f"CAN send failed on {channel}")


def _default_action_runner(action_id: str) -> tuple[bool, str]:
    from ..actions import registry
    result = registry.run(action_id)
    return result.ok, result.message


DbcTextResolver = Callable[[int], "str | None"]
FrameSource = Callable[[str, str], list[dict[str, Any]]]
Sender = Callable[[str, str, Step, "str | None"], tuple[bool, str]]
ActionRunner = Callable[[str], tuple[bool, str]]
Clock = Callable[[], float]


class Runner:
    """Steps through one :class:`Sequence` and records a per-step result."""

    def __init__(
        self,
        sequence: Sequence,
        *,
        clock: Clock | None = None,
        frame_source: FrameSource | None = None,
        dbc_text_resolver: DbcTextResolver | None = None,
        sender: Sender | None = None,
        action_runner: ActionRunner | None = None,
    ) -> None:
        self.sequence = sequence
        self._clock = clock or _default_clock
        self._frame_source = frame_source or _default_frame_source
        self._dbc_text_resolver = dbc_text_resolver or _default_dbc_text_resolver
        self._sender = sender or _default_sender
        self._action_runner = action_runner or _default_action_runner

        self._lock = threading.Lock()
        self._results: list[StepResult] = [
            StepResult(step_id=s.id, type=s.type, label=s.label) for s in sequence.steps
        ]
        self._index = 0
        self._state = IDLE
        self._thread: threading.Thread | None = None
        self._bg_running = False

    # -- collaborator helpers ------------------------------------------------

    def _resolve_dbc(self, step: Step) -> str | None:
        if not step.database_id:
            return None
        try:
            return self._dbc_text_resolver(step.database_id)
        except Exception as exc:
            log.info("Could not resolve DBC text for database %s: %s", step.database_id, exc)
            return None

    # -- lifecycle ------------------------------------------------------------

    def start(self, threaded: bool = True) -> bool:
        """Reset all step results and begin the run.

        Returns False if a run is already in progress. With ``threaded``
        (the default, used by the router), a daemon thread calls :meth:`tick`
        on an interval so a real run advances on its own. A test passes
        ``threaded=False`` and drives :meth:`tick` itself with a synthetic
        clock and injected frames, so the exact same state-machine decision
        runs with no real thread or timing dependency.
        """
        with self._lock:
            if self._state in (RUNNING, WAITING_CONFIRM):
                return False
            self._results = [
                StepResult(step_id=s.id, type=s.type, label=s.label) for s in self.sequence.steps
            ]
            self._index = 0
            self._state = RUNNING if self.sequence.steps else DONE
            self._bg_running = threaded
        _log_event("test_step", f"Started sequence {self.sequence.name or self.sequence.id}",
                    data={"sequence_id": self.sequence.id})
        if threaded:
            self._thread = threading.Thread(target=self._loop, daemon=True, name="testseq-runner")
            self._thread.start()
        return True

    def stop(self) -> None:
        """Stop the background loop (results already recorded are kept)."""
        with self._lock:
            self._bg_running = False
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None

    def _loop(self) -> None:
        while True:
            with self._lock:
                if not self._bg_running or self._state in (DONE, IDLE):
                    return
            self.tick()
            time.sleep(TICK_SECONDS)

    # -- the pure-ish state machine step --------------------------------------

    def tick(self) -> None:
        """Advance the run as far as it can go right now without blocking.

        Loops over consecutive steps that complete immediately (send,
        action) so a single call drains them all, and stops as soon as a
        step is left waiting (a delay or expect not yet due, or a prompt
        parked in WAITING_CONFIRM). Depends only on the collaborators passed
        to the constructor, so a test can call this directly (no thread, no
        sleep) with a synthetic clock and an injected frame list to drive
        the exact decision the background loop makes.
        """
        with self._lock:
            while self._state == RUNNING:
                if self._index >= len(self.sequence.steps):
                    self._state = DONE
                    return
                step = self.sequence.steps[self._index]
                result = self._results[self._index]
                now = self._clock()

                if result.status == STEP_PENDING:
                    result.status = STEP_RUNNING
                    result.started_at = now
                    self._begin_step(step, result, now)

                if not self._advance_if_ready(step, result, now):
                    return

    def _begin_step(self, step: Step, result: StepResult, now: float) -> None:
        """Do the one-shot work a step needs when it first becomes current.

        "send" and "action" complete immediately (there is nothing to wait
        on); "delay" and "expect" are evaluated on later ticks;  "prompt"
        parks the runner in WAITING_CONFIRM until :meth:`resolve_prompt` is
        called.
        """
        if step.type == "send":
            dbc_text = self._resolve_dbc(step)
            ok, message = self._sender(step.channel, step.backend, step, dbc_text)
            result.status = STEP_PASS if ok else STEP_FAIL
            result.message = message
        elif step.type == "action":
            if not step.action_id:
                result.status = STEP_FAIL
                result.message = "No action id configured"
            else:
                ok, message = self._action_runner(step.action_id)
                result.status = STEP_PASS if ok else STEP_FAIL
                result.message = message
        elif step.type == "prompt":
            self._state = WAITING_CONFIRM
            result.status = STEP_WAITING_CONFIRM
            result.message = step.prompt_text or "Waiting for operator confirmation"
        # "delay" and "expect" need no one-shot work; _advance_if_ready
        # evaluates them against elapsed time / frames on every tick.

    def _advance_if_ready(self, step: Step, result: StepResult, now: float) -> bool:
        """Finalize ``result`` if it is ready to move on. Returns True when the
        step finalized (so :meth:`tick` should keep looping onto the next
        one), False when it is still waiting (so :meth:`tick` should stop)."""
        if result.status in (STEP_PASS, STEP_FAIL, STEP_SKIP):
            self._finalize_step(result, now)
            return True
        if result.status == STEP_WAITING_CONFIRM:
            return False  # resolve_prompt() will move this along

        if step.type == "delay":
            outcome = evaluation.evaluate_delay(step, result.started_at, now)
        elif step.type == "expect":
            frames = self._frame_source(step.channel, step.backend)
            dbc_text = self._resolve_dbc(step)
            outcome = evaluation.match_expect(step, frames, dbc_text, result.started_at, now)
        else:
            return False

        if outcome["outcome"] == evaluation.PENDING:
            return False
        result.status = STEP_PASS if outcome["outcome"] == evaluation.PASS else STEP_FAIL
        result.message = outcome["message"]
        result.observed = outcome["observed"]
        self._finalize_step(result, now)
        return True

    def _finalize_step(self, result: StepResult, now: float) -> None:
        result.ended_at = now
        if result.started_at is not None:
            result.duration_ms = (now - result.started_at) * 1000.0
        _log_event("test_step", f"{result.type} step {result.status}: {result.message}", data={
            "sequence_id": self.sequence.id, "step_id": result.step_id, "status": result.status,
        })
        self._index += 1
        if self._index >= len(self.sequence.steps):
            self._state = DONE
            self._bg_running = False
            # Not self.report(): that re-acquires self._lock, and this runs
            # from inside tick()'s locked section (or resolve_prompt()'s).
            _log_event("test_result", self._summary_message(), data=self._report_locked())

    def _summary_message(self) -> str:
        failed = [r for r in self._results if r.status == STEP_FAIL]
        name = self.sequence.name or self.sequence.id
        if failed:
            return f"Sequence {name} finished: {len(failed)} of {len(self._results)} step(s) failed"
        return f"Sequence {name} finished: all {len(self._results)} step(s) passed"

    # -- operator confirmation -------------------------------------------------

    def resolve_prompt(self, passed: bool, note: str = "") -> bool:
        """Answer the current "prompt" step. Returns False if none is pending."""
        with self._lock:
            if self._state != WAITING_CONFIRM or self._index >= len(self.sequence.steps):
                return False
            step = self.sequence.steps[self._index]
            result = self._results[self._index]
            if step.type != "prompt" or result.status != STEP_WAITING_CONFIRM:
                return False
            outcome = evaluation.resolve_confirm(step, passed, note)
            result.status = STEP_PASS if outcome["outcome"] == evaluation.PASS else STEP_FAIL
            result.message = outcome["message"]
            result.observed = outcome["observed"]
            result.note = note
            now = self._clock()
            self._state = RUNNING
            self._finalize_step(result, now)
            return True

    # -- reporting --------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        with self._lock:
            current = self._index if self._index < len(self._results) else None
            return {
                "sequence_id": self.sequence.id,
                "state": self._state,
                "current_index": current,
                "steps": [r.to_dict() for r in self._results],
            }

    def report(self) -> dict[str, Any]:
        with self._lock:
            return self._report_locked()

    def _report_locked(self) -> dict[str, Any]:
        """The report body. Caller must already hold ``self._lock``."""
        passed = sum(1 for r in self._results if r.status == STEP_PASS)
        failed = sum(1 for r in self._results if r.status == STEP_FAIL)
        skipped = sum(1 for r in self._results if r.status == STEP_SKIP)
        return {
            "sequence_id": self.sequence.id,
            "sequence_name": self.sequence.name,
            "state": self._state,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "total": len(self._results),
            "ok": self._state == DONE and failed == 0,
            "steps": [r.to_dict() for r in self._results],
        }


# -- module-level singleton: one active run at a time ------------------------

_active: Runner | None = None
_active_lock = threading.Lock()


def run_sequence(sequence: Sequence) -> Runner:
    """Create a fresh :class:`Runner` for ``sequence``, start it, and make it
    the active run (replacing and stopping any previous one)."""
    global _active
    with _active_lock:
        if _active is not None:
            _active.stop()
        runner = Runner(sequence)
        _active = runner
    runner.start()
    return runner


def get_active() -> Runner | None:
    with _active_lock:
        return _active


def reset_active() -> None:
    """Stop and drop the active runner. Mainly for tests."""
    global _active
    with _active_lock:
        if _active is not None:
            _active.stop()
        _active = None
