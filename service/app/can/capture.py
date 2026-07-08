"""Inhale/exhale: capture a run of frames from a CAN channel into a named
buffer, and replay a buffer back to a channel later.

Inhaling is a bounded background reader (a frame count limit, a duration
limit, or manual stop), mirroring :class:`app.can.monitor.MonitorChannel`'s
thread shape. Exhaling walks the captured records and resends them, waiting
between frames by their originally recorded spacing (optionally scaled), and
can run the same firewall rule set (:mod:`app.can.firewall`) over each frame
first, so a capture can be edited on replay rather than only played back
verbatim.

The frame-record shape, the inter-frame delay math, and buffer
serialize/parse are kept pure so they are unit-testable with a synthetic
clock and no thread or hardware; only :class:`InhaleSession` and
:class:`ExhaleSession` touch a real provider or a real clock.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Callable

from ..config import settings
from ..services.state import StateFile
from .base import Frame, parse_data_bytes
from .registry import get_channel

log = logging.getLogger(__name__)

RECV_TIMEOUT = 0.5


def _store() -> StateFile:
    return StateFile(settings.data_dir / "can_captures.json", default={"captures": []})


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# -- record shape and buffer math (pure) ---------------------------------

def frame_to_record(frame: Frame, timestamp: float) -> dict[str, Any]:
    """Turn a :class:`Frame` into the plain-dict record kept in a capture."""
    return {
        "arbitration_id": frame.arbitration_id,
        "data": list(frame.data),
        "timestamp": timestamp,
        "is_extended_id": frame.is_extended_id,
        "is_fd": frame.is_fd,
        "is_remote": frame.is_remote,
    }


def record_to_frame(record: dict[str, Any]) -> Frame:
    """Rebuild the :class:`Frame` a capture record describes."""
    raw = record.get("data") or []
    data = parse_data_bytes(raw) if isinstance(raw, str) else list(raw)
    return Frame(
        arbitration_id=record["arbitration_id"],
        data=data,
        is_fd=bool(record.get("is_fd", False)),
        is_extended_id=bool(record.get("is_extended_id", False)),
        is_remote=bool(record.get("is_remote", False)),
    )


def compute_replay_delays(records: list[dict[str, Any]], speed: float = 1.0) -> list[float]:
    """Return one wait time per record: how long to pause *before* sending it,
    so replay reproduces the captured relative timing.

    The first record has no predecessor and so waits 0. ``speed`` scales the
    gaps (2.0 replays twice as fast, 0.5 half as fast); a speed of 0 or less
    is treated as 1.0 (real-time) since a zero divide has no sane meaning
    here. A capture recorded out of order (a timestamp older than the one
    before it) never produces a negative wait.
    """
    if speed <= 0:
        speed = 1.0
    delays: list[float] = []
    previous: float | None = None
    for record in records:
        ts = record.get("timestamp", 0.0)
        if previous is None:
            delays.append(0.0)
        else:
            delays.append(max(0.0, (ts - previous) / speed))
        previous = ts
    return delays


# -- capture persistence -------------------------------------------------

def list_captures() -> list[dict[str, Any]]:
    """Summaries only (no frame data), for a lightweight list view."""
    captures = _store().read().get("captures", [])
    return [
        {k: v for k, v in c.items() if k != "frames"} | {"frame_count": len(c.get("frames", []))}
        for c in captures
    ]


def get_capture(capture_id: str) -> dict[str, Any] | None:
    for capture in _store().read().get("captures", []):
        if capture.get("id") == capture_id:
            return capture
    return None


def save_capture(name: str, channel: str, backend: str, frames: list[dict[str, Any]]) -> dict[str, Any]:
    capture = {
        "id": _new_id(),
        "name": name or f"{channel} capture",
        "channel": channel,
        "backend": backend,
        "created_at": time.time(),
        "frames": frames,
    }
    store = _store()
    doc = store.read()
    captures = doc.get("captures", [])
    captures.append(capture)
    doc["captures"] = captures
    store.write(doc)
    return capture


def delete_capture(capture_id: str) -> bool:
    store = _store()
    doc = store.read()
    captures = doc.get("captures", [])
    remaining = [c for c in captures if c.get("id") != capture_id]
    if len(remaining) == len(captures):
        return False
    doc["captures"] = remaining
    store.write(doc)
    return True


# -- inhale: bounded background capture ----------------------------------

class InhaleSession:
    """Captures frames from one channel into memory, up to a frame-count or
    duration limit (or until stopped by hand), then persists them as a named
    capture on :meth:`stop`."""

    def __init__(self, channel: str, backend: str = "socketcan",
                 channel_factory: Callable[..., Any] | None = None) -> None:
        self.channel = channel
        self.backend = backend
        self._get_channel = channel_factory or get_channel
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._frames: list[dict[str, Any]] = []
        self._name = ""
        self._max_frames: int | None = None
        self._max_duration_s: float | None = None
        self._started_at: float | None = None
        # Set by _loop right before it exits (whether stopped by hand or by
        # hitting a limit), and handed back (once) by stop().
        self._saved: dict[str, Any] | None = None

    def is_running(self) -> bool:
        return self._running

    def status(self) -> dict[str, Any]:
        with self._lock:
            frame_count = len(self._frames)
            elapsed = (time.time() - self._started_at) if self._started_at else 0.0
        return {
            "channel": self.channel,
            "backend": self.backend,
            "running": self._running,
            "frame_count": frame_count,
            "elapsed_s": elapsed,
            "max_frames": self._max_frames,
            "max_duration_s": self._max_duration_s,
        }

    def start(self, name: str, max_frames: int | None = None, max_duration_s: float | None = None) -> bool:
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._frames = []
            self._name = name
            self._max_frames = max_frames
            self._max_duration_s = max_duration_s
            self._started_at = time.time()
            self._saved = None
            self._thread = threading.Thread(target=self._loop, daemon=True, name=f"can-inhale-{self.channel}")
            self._thread.start()
            return True

    def stop(self) -> dict[str, Any] | None:
        """Stop capturing (if still running; a no-op if it already hit a
        limit on its own) and return what was persisted. Returns None if
        nothing was running and nothing is waiting to be collected."""
        with self._lock:
            self._running = False
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None
        with self._lock:
            saved = self._saved
            self._saved = None
        return saved

    def _loop(self) -> None:
        provider = self._get_channel(self.channel, backend=self.backend)
        while self._running:
            try:
                frame = provider.recv(timeout=RECV_TIMEOUT)
            except Exception as exc:
                log.info("CAN inhale recv failed on %s: %s", self.channel, exc)
                time.sleep(RECV_TIMEOUT)
                continue
            if frame is None:
                continue
            with self._lock:
                if not self._running:
                    break
                self._frames.append(frame_to_record(frame, time.time()))
                done = (
                    (self._max_frames is not None and len(self._frames) >= self._max_frames)
                    or (self._max_duration_s is not None and self._started_at is not None
                        and time.time() - self._started_at >= self._max_duration_s)
                )
            if done:
                self._running = False
        # Persist whatever was captured, whether the loop ended because
        # stop() was called or because a limit was reached on its own.
        with self._lock:
            frames = list(self._frames)
        saved = save_capture(self._name, self.channel, self.backend, frames)
        with self._lock:
            self._saved = saved


# Module-level registry, one InhaleSession per (backend, channel).
_inhale_sessions: dict[str, InhaleSession] = {}


def get_inhale_session(channel: str, backend: str = "socketcan") -> InhaleSession:
    key = f"{backend}:{channel}"
    session = _inhale_sessions.get(key)
    if session is None:
        session = InhaleSession(channel, backend=backend)
        _inhale_sessions[key] = session
    return session


def reset_inhale_sessions() -> None:
    """Stop and drop every cached inhale session. Mainly for tests."""
    for session in _inhale_sessions.values():
        try:
            session.stop()
        except Exception:
            pass
    _inhale_sessions.clear()


# -- exhale: replay a capture ---------------------------------------------

DbcTextLookup = Callable[[int], "str | None"]
FrameSender = Callable[[str, str, Frame], bool]
SleepFn = Callable[[float], None]


def replay_records(
    records: list[dict[str, Any]],
    channel: str,
    backend: str,
    *,
    rules: list[dict[str, Any]] | None = None,
    dbc_lookup: DbcTextLookup | None = None,
    speed: float = 1.0,
    sender: FrameSender | None = None,
    sleep_fn: SleepFn | None = None,
    should_continue: Callable[[], bool] | None = None,
) -> dict[str, int]:
    """Replay a list of capture records to a channel, pacing sends by their
    originally recorded spacing (scaled by ``speed``).

    When ``rules`` is given, each record is run through
    :func:`app.can.firewall.apply_rules` (direction ``"replay"``, so only
    rules scoped to "both" apply) before sending, allowing a blocked frame to
    be dropped and a rewrite/inject rule to modify or extend the traffic on
    the way out. ``should_continue`` lets a caller abort a long replay
    early (checked before each frame); it defaults to always continuing.
    """
    sender = sender or (lambda b, c, f: get_channel(c, backend=b).send(f))
    sleep_fn = sleep_fn or time.sleep
    should_continue = should_continue or (lambda: True)
    delays = compute_replay_delays(records, speed=speed)
    stats = {"sent": 0, "blocked": 0, "rewritten": 0, "injected": 0, "errors": 0}
    for record, delay in zip(records, delays):
        if not should_continue():
            break
        if delay:
            sleep_fn(delay)
        frame = record_to_frame(record)
        if rules:
            from .firewall import apply_rules
            decision = apply_rules(frame, rules, "replay", dbc_lookup)
        else:
            from .firewall import Decision
            decision = Decision(action="allow", rule_id=None, frame=frame)
        if decision.action == "block":
            stats["blocked"] += 1
            continue
        if decision.action == "rewrite":
            stats["rewritten"] += 1
        if decision.injected:
            stats["injected"] += len(decision.injected)
        to_send = ([decision.frame] if decision.frame is not None else []) + decision.injected
        for out_frame in to_send:
            try:
                ok = sender(backend, channel, out_frame)
            except Exception as exc:
                log.info("CAN exhale send failed on %s: %s", channel, exc)
                ok = False
            if ok:
                stats["sent"] += 1
            else:
                stats["errors"] += 1
    return stats


class ExhaleSession:
    """Background driver for :func:`replay_records`, so a replay of a long
    capture can run without blocking the request that started it, and can be
    cancelled early."""

    def __init__(self, sender: FrameSender | None = None, sleep_fn: SleepFn | None = None) -> None:
        self._sender = sender
        self._sleep_fn = sleep_fn
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._stats: dict[str, int] = {}
        self._total = 0

    def is_running(self) -> bool:
        return self._running

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"running": self._running, "total": self._total, "stats": dict(self._stats)}

    def start(
        self,
        capture: dict[str, Any],
        channel: str,
        backend: str,
        *,
        rules: list[dict[str, Any]] | None = None,
        dbc_lookup: DbcTextLookup | None = None,
        speed: float = 1.0,
    ) -> bool:
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._stats = {"sent": 0, "blocked": 0, "rewritten": 0, "injected": 0, "errors": 0}
            self._total = len(capture.get("frames", []))
            self._thread = threading.Thread(
                target=self._run, args=(capture, channel, backend, rules, dbc_lookup, speed),
                daemon=True, name="can-exhale",
            )
            self._thread.start()
            return True

    def stop(self) -> bool:
        with self._lock:
            if not self._running:
                return False
            self._running = False
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None
        return True

    def _run(self, capture, channel, backend, rules, dbc_lookup, speed) -> None:
        stats = replay_records(
            capture.get("frames", []), channel, backend,
            rules=rules, dbc_lookup=dbc_lookup, speed=speed,
            sender=self._sender, sleep_fn=self._sleep_fn,
            should_continue=lambda: self._running,
        )
        with self._lock:
            self._stats = stats
            self._running = False


# Module-level singleton shared by the router.
exhale = ExhaleSession()
