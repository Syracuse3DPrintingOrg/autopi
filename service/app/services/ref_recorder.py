"""Reference recorder for Signal Finder: turns a bench technician's live
interaction with a control (sweeping a knob, pressing a button) into the
``{"t": ..., "value": ..., "available": bool}`` reference series the
bitsearch pipeline already expects.

Every mark is timestamped on the server with ``time.time()``, the same clock
:class:`app.can.capture.InhaleSession` uses to stamp captured frames, so a
recorded reference lines up with a capture automatically without trusting a
browser clock or doing any manual clock sync.

State is persisted through :class:`~app.services.state.StateFile` (atomic
JSON, mtime-cached) so the recording survives across uvicorn workers and a
restart, the same pattern used by timers, current-recipe-style shared state
elsewhere in this codebase's sibling projects.
"""
from __future__ import annotations

import time
from typing import Any

from ..config import settings
from .state import StateFile

MODES = ("sweep", "button")

_DEFAULT: dict[str, Any] = {
    "recording": False,
    "mode": None,
    "points": [],   # sweep: [{"t": ..., "value": ...}, ...]
    "events": [],   # button: [t, t, ...]
}


def _store() -> StateFile:
    return StateFile(settings.data_dir / "ref_recorder.json", default=dict(_DEFAULT))


def start(mode: str) -> dict:
    """Begin a new recording, discarding any previous one. Raises
    ``ValueError`` if ``mode`` is not recognized."""
    if mode not in MODES:
        raise ValueError(f"unknown reference mode: {mode!r}")
    doc = {"recording": True, "mode": mode, "points": [], "events": []}
    _store().write(doc)
    return status()


def mark(value: float, t: float | None = None) -> dict:
    """Record a sweep sample. No-op (returns current status) if not recording in
    sweep mode.

    ``t`` is the moment the sample is true, on the server clock. A vision read
    passes the time the frame was GRABBED, not now: the AI read takes a couple of
    seconds and that latency varies per frame, so stamping at read-return time
    smears the reference against the capture and no single lag can realign it.
    Stamping at grab time keeps every point lined up with the frames the capture
    recorded. Defaults to now for a live sweep where the value is true as it is
    marked."""
    store = _store()
    doc = store.read()
    if not doc.get("recording") or doc.get("mode") != "sweep":
        return status()
    doc.setdefault("points", []).append({"t": float(t) if t is not None else time.time(),
                                          "value": float(value)})
    store.write(doc)
    return status()


def event() -> dict:
    """Record a button press at the current time. No-op (returns current
    status) if not recording in button mode."""
    store = _store()
    doc = store.read()
    if not doc.get("recording") or doc.get("mode") != "button":
        return status()
    doc.setdefault("events", []).append(time.time())
    store.write(doc)
    return status()


def status() -> dict:
    doc = _store().read()
    mode = doc.get("mode")
    count = len(doc.get("points") or []) if mode == "sweep" else len(doc.get("events") or [])
    return {"recording": bool(doc.get("recording")), "mode": mode, "count": count}


def stop() -> dict:
    """Stop recording (leaving whatever was captured in place) and return
    the current status."""
    store = _store()
    doc = store.read()
    doc["recording"] = False
    store.write(doc)
    return status()


def get() -> dict:
    """The raw recording: sweep mode returns its ``{t, value}`` points,
    button mode returns its raw press timestamps. Either can be empty."""
    doc = _store().read()
    return {
        "mode": doc.get("mode"),
        "points": list(doc.get("points") or []),
        "events": list(doc.get("events") or []),
    }


def clear() -> dict:
    _store().write(dict(_DEFAULT))
    return status()
