"""Signal Finder API: statistically reverse engineer which CAN field carries
a signal a bench technician can see or trigger by hand, from a capture plus a
reference series they recorded while operating the real control.

A thin REST wrapper over :mod:`app.can.reverse`'s pure search and statistics;
the algorithm itself never touches the database or a capture file, only
plain lists of frame records and reference points.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import llm
from ..can import capture as cap
from ..can import get_channel
from ..can import registry as can_registry
from ..can import reverse as rev
from ..db import CanDatabase, session_scope
from ..services import ref_recorder as rec

router = APIRouter(prefix="/reverse", tags=["can-reverse"])

MAX_LIVE_SECONDS = 30.0

# Remembers whether /reference/start also started an inhale capture, so
# /reference/stop knows whether to stop and save one. Keyed by nothing (one
# reference recording at a time, matching ref_recorder's own single-slot
# state); reset whenever a new recording starts.
_reference_capture: dict = {"channel": None, "backend": None, "name": None}


class ReferencePoint(BaseModel):
    t: float
    value: float
    available: bool = True


def _capture_or_404(capture_id: str) -> dict:
    capture = cap.get_capture(capture_id)
    if capture is None:
        raise HTTPException(404, "No such capture")
    return capture


def _frames_for_id(capture: dict, arbitration_id: int) -> list[dict]:
    return [f for f in capture.get("frames", []) if f.get("arbitration_id") == arbitration_id]


def _frames_by_id(capture: dict) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for frame in capture.get("frames", []):
        grouped.setdefault(frame.get("arbitration_id"), []).append(frame)
    return grouped


def _capture_factory(channel: str, backend: str):
    """A socket opener for live captures that resolves fd/bitrate explicitly from
    the interface config (and forces fd when the live link is CAN-FD), the same
    way the working sniff does. This keeps a capture from opening a classic
    socket on a CAN-FD bus (which receives nothing) even if the implicit lookup
    inside open_channel does not match this channel."""
    open_kwargs: dict = {}
    try:
        from ..services import can_interfaces
        for entry in can_interfaces.list_interfaces():
            if entry.get("channel") == channel and entry.get("backend", "socketcan") == backend:
                open_kwargs["fd"] = bool(entry.get("fd"))
                if entry.get("bitrate"):
                    open_kwargs["bitrate"] = entry["bitrate"]
                if entry.get("data_bitrate"):
                    open_kwargs["data_bitrate"] = entry["data_bitrate"]
                break
    except Exception:
        pass
    if backend == "socketcan" and can_registry._link_is_fd(channel):
        open_kwargs["fd"] = True

    def factory(ch: str, backend: str = "socketcan", **kw):
        merged = {**open_kwargs, **{k: v for k, v in kw.items() if v is not None}}
        return can_registry.open_channel(ch, backend=backend, **merged)

    return factory


def _run_live_capture(channel: str, backend: str, seconds: float, name: str = "") -> dict:
    """Run a short, bounded inhale on a live channel and block until it is
    saved, so a caller gets a capture_id back in one request instead of
    needing to poll. Returns ``{"ok": True, "capture": {...}}`` or
    ``{"ok": False, "error": ...}``; never raises for an unavailable or
    already-busy channel, since a bench technician driving this from the UI
    needs an honest message, not a 500.
    """
    provider = get_channel(channel, backend=backend)
    if not provider.available:
        return {"ok": False, "error": getattr(provider, "last_error", None)
                or f"Channel {channel!r} is not available. Bring the interface up first."}

    capped_seconds = max(0.5, min(float(seconds), MAX_LIVE_SECONDS))
    before = can_registry.link_stats(channel)
    session = cap.get_inhale_session(channel, backend=backend,
                                     channel_factory=_capture_factory(channel, backend))
    if not session.start(name, max_duration_s=capped_seconds):
        return {"ok": False, "error": "A capture is already running on that channel"}

    # InhaleSession only checks its own duration limit right after a frame
    # arrives, so a silent channel would otherwise run forever; enforce the
    # bound here regardless of whether any frames showed up.
    deadline = time.time() + capped_seconds + 1.0
    while session.is_running() and time.time() < deadline:
        time.sleep(0.05)
    saved = session.stop()
    frame_count = len(saved.get("frames", [])) if saved else 0
    if saved is None or frame_count == 0:
        note = _explain_empty_capture(channel, before, can_registry.link_stats(channel))
        result: dict = {"ok": False, "error": note, "note": note}
        if saved is not None:
            result["capture"] = saved
        return result
    return {"ok": True, "capture": saved}


def _explain_empty_capture(channel: str, before: dict | None, after: dict | None) -> str:
    """Say *why* a live capture came back empty, from the interface's link state
    and kernel rx counter, instead of a bare "nothing". Distinguishes an idle
    port (rx counter did not move: wrong channel) from a port that is receiving
    frames the socket did not read (rx climbed: a CAN-FD-vs-classic mode issue)."""
    after = after or {}
    if not after.get("present"):
        return f"{channel} is not present on this device."
    state = after.get("operstate")
    if state not in ("up", "unknown", None):
        return f"{channel} is not up (state: {state}). Bring the interface up first."
    # Receive errors climbing means the bus is active but the frames arrive
    # corrupt: a CAN-FD bit-timing or termination mismatch, not an idle port and
    # not the app. This is the error-passive case.
    err0 = (before or {}).get("rx_errors")
    err1 = after.get("rx_errors")
    erroring = err0 is not None and err1 is not None and err1 > err0
    if erroring:
        return (f"{channel} is receiving bus errors, not clean frames (rx errors +{err1 - err0} during "
                f"the capture) — a CAN-FD bit-timing or termination problem, not the app. Check the HAT's "
                f"terminator jumper for this port is OFF if the bus is already terminated elsewhere, and "
                f"that the data bitrate, sample point, and oscillator match the bus.")
    rx0 = (before or {}).get("rx_packets")
    rx1 = after.get("rx_packets")
    climbed = rx0 is not None and rx1 is not None and rx1 > rx0
    if climbed:
        fd_note = (" This bus is CAN-FD; a classic socket receives none of its frames." if after.get("fd")
                   else "")
        return (f"Frames are reaching {channel} (kernel rx +{rx1 - rx0} during the capture) but the capture "
                f"read none.{fd_note} If the app was just updated, it may still be running older code: "
                f"restart it (cd /opt/autopi-src && sudo docker compose up -d) and try again.")
    return (f"No frames reached {channel} during the capture (its kernel rx counter did not move), so this "
            f"port is idle. Your traffic is almost certainly on the other CAN interface: on the Waveshare "
            f"HAT the Linux name and the board's CAN0/CAN1 label can be crossed, so try the other channel.")


class CaptureLiveIn(BaseModel):
    channel: str
    backend: str = "socketcan"
    seconds: float = 5.0
    name: str = ""


@router.post("/capture-live")
def capture_live_route(body: CaptureLiveIn):
    """Run the Signal Finder against a live bus without a trip to the CAN
    console first: capture a few seconds on the given channel and hand back
    its capture_id, ready to survey or bitsearch."""
    result = _run_live_capture(body.channel, body.backend, body.seconds, body.name)
    if not result["ok"]:
        return result
    saved = result["capture"]
    return {"ok": True, "capture_id": saved["id"], "frame_count": len(saved.get("frames", []))}


class SnapshotIn(BaseModel):
    channel: str
    backend: str = "socketcan"
    seconds: float = 3.0


@router.post("/snapshot")
def snapshot_route(body: SnapshotIn):
    """Capture a few seconds live and summarize which arbitration ids are
    active and which of their bytes are changing, with no reference needed,
    so a user can see what is on can1/can2 before hunting a specific
    signal."""
    result = _run_live_capture(body.channel, body.backend, body.seconds, "snapshot")
    if not result["ok"]:
        return result
    saved = result["capture"]
    grouped = _frames_by_id(saved)
    ranked = rev.activity_survey(grouped)
    return {"ok": True, "capture_id": saved["id"], "ids": ranked}


@router.get("/captures")
def list_captures():
    """Captures available to reverse engineer (the same inhale buffers the
    CAN console records)."""
    return {"captures": cap.list_captures()}


@router.get("/captures/{capture_id}/ids")
def list_ids(capture_id: str):
    """Arbitration ids present in one capture, with a frame count each, so
    the UI can populate an id picker without shipping every frame."""
    capture = _capture_or_404(capture_id)
    grouped = _frames_by_id(capture)
    ids = [
        {"arbitration_id": arb_id, "frame_count": len(frames)}
        for arb_id, frames in grouped.items()
    ]
    ids.sort(key=lambda entry: entry["arbitration_id"])
    return {"ids": ids}


class BitActivityIn(BaseModel):
    capture_id: str
    arbitration_id: int


@router.post("/bit-activity")
def bit_activity_route(body: BitActivityIn):
    capture = _capture_or_404(body.capture_id)
    frames = _frames_for_id(capture, body.arbitration_id)
    if not frames:
        raise HTTPException(404, "No frames with that arbitration id in this capture")
    return rev.bit_activity(frames)


class SurveyIn(BaseModel):
    capture_id: str
    reference: list[ReferencePoint]
    opts: dict = {}


@router.post("/survey")
def survey_route(body: SurveyIn):
    capture = _capture_or_404(body.capture_id)
    grouped = _frames_by_id(capture)
    reference = [p.model_dump() for p in body.reference]
    ranked = rev.survey(grouped, reference, body.opts or {})
    return {"ranked": ranked}


class BitsearchIn(BaseModel):
    capture_id: str
    arbitration_id: int
    reference: list[ReferencePoint]
    opts: dict = {}


@router.post("/bitsearch")
def bitsearch_route(body: BitsearchIn):
    capture = _capture_or_404(body.capture_id)
    frames = _frames_for_id(capture, body.arbitration_id)
    if not frames:
        raise HTTPException(404, "No frames with that arbitration id in this capture")
    reference = [p.model_dump() for p in body.reference]
    candidates = rev.bitsearch(frames, reference, body.opts or {})
    return {"candidates": candidates}


class SaveIn(BaseModel):
    database_id: int
    name: str
    candidate: dict
    message_name: str | None = None
    unit: str = ""
    comment: str = ""


@router.post("/save")
def save_route(body: SaveIn):
    if not body.name.strip():
        raise HTTPException(400, "Signal needs a name")
    derived = rev.derive_scale_offset(body.candidate)
    definition = rev.to_dbc_signal(body.name.strip(), derived, unit=body.unit, comment=body.comment)
    with session_scope() as s:
        database = s.get(CanDatabase, body.database_id)
        if database is None:
            raise HTTPException(404, "No such CAN database")
        try:
            rev.add_signal_to_database(
                s, database, int(body.candidate["arbitration_id"]), body.name.strip(),
                definition, message_name=body.message_name,
            )
        except Exception as exc:
            raise HTTPException(400, f"Could not save signal: {exc}")
        s.flush()
        return {"ok": True, "database": database.to_dict(with_messages=True),
                "candidate": derived}


# --------------------------------------------------------------------------
# CAN-based reference: use a known, decodable signal already in the capture
# (OBD2 speed/RPM, or a signal reverse engineered earlier) as the reference,
# instead of sweeping or button-pressing by hand. The most precise option.
# --------------------------------------------------------------------------

def _dbc_text_or_404(database_id: int) -> str:
    with session_scope() as s:
        database = s.get(CanDatabase, database_id)
        if database is None:
            raise HTTPException(404, "No such CAN database")
        if not database.dbc_text:
            raise HTTPException(400, "That database has no DBC text to decode with")
        return database.dbc_text


def _known_signals_summary(database_id: int | None, limit: int = 60) -> str:
    """A short 'arb_id: signal' list of what a database already knows, to give
    the LLM context so it does not re-propose known signals and hallucinates
    less. Empty string when no database is given or it has no messages."""
    if not database_id:
        return ""
    try:
        from ..db import CanMessage
        with session_scope() as s:
            rows = s.query(CanMessage).filter_by(database_id=database_id).all()
            lines = []
            for m in rows:
                for sig in m.signals:
                    lines.append(f"0x{m.arbitration_id:X}: {sig.name}")
                    if len(lines) >= limit:
                        return "\n".join(lines)
            return "\n".join(lines)
    except Exception:
        return ""


class ReferenceFromSignalIn(BaseModel):
    capture_id: str
    database_id: int
    arbitration_id: int
    signal: str


@router.post("/reference/from-signal")
def reference_from_signal_route(body: ReferenceFromSignalIn):
    """Build a reference series from a known signal decoded out of the capture,
    ready to feed straight into /survey and /bitsearch."""
    capture = _capture_or_404(body.capture_id)
    frames = _frames_for_id(capture, body.arbitration_id)
    if not frames:
        raise HTTPException(404, "No frames with that arbitration id in this capture")
    dbc_text = _dbc_text_or_404(body.database_id)
    reference = rev.reference_from_signal(frames, dbc_text, body.arbitration_id, body.signal)
    if not reference:
        return {"ok": False, "error": "That signal did not decode on any frame of this capture."}
    return {"ok": True, "reference": reference, "points": len(reference)}


class VerifyIn(BaseModel):
    capture_id: str
    candidate: dict
    reference: list[ReferencePoint]


@router.post("/verify")
def verify_route(body: VerifyIn):
    """Decode a candidate across the capture and return it alongside the
    reference, both as time series, so the UI can plot decoded-vs-reference and
    the user can confirm the field is really the signal (the article's result
    plot)."""
    capture = _capture_or_404(body.capture_id)
    try:
        arbitration_id = int(body.candidate["arbitration_id"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "candidate needs an arbitration_id")
    frames = _frames_for_id(capture, arbitration_id)
    series = rev.field_series(frames, body.candidate)
    scale = float(body.candidate.get("scale", 1.0) or 1.0)
    offset = float(body.candidate.get("offset", 0.0) or 0.0)
    decoded = [{"t": t, "value": raw * scale + offset} for t, raw in series]
    reference = [{"t": p.t, "value": p.value} for p in body.reference if p.available]
    return {"decoded": decoded, "reference": reference}


# --------------------------------------------------------------------------
# "Find a control": capture every active bus at once, have the user operate the
# control and mark each press, and rank the message that reacts. No reference
# sweep, no timing sync, no guessing which bus a control is on.
# --------------------------------------------------------------------------

_hunt: dict = {"active": False, "channels": [], "backend": "socketcan", "events": []}


@router.post("/hunt/start")
def hunt_start():
    from ..can import detect
    channels = [i["name"] for i in detect.list_can_interfaces() if i.get("up")]
    if not channels:
        return {"ok": False, "error": "No CAN interfaces are up. Bring at least one up on the CAN settings page first."}
    started = []
    for ch in channels:
        session = cap.get_inhale_session(ch, backend="socketcan",
                                         channel_factory=_capture_factory(ch, "socketcan"))
        if session.start(f"hunt {ch}"):
            started.append(ch)
    if not started:
        return {"ok": False, "error": "Could not start a capture on any bus (one may already be running)."}
    _hunt.update({"active": True, "channels": started, "backend": "socketcan", "events": []})
    return {"ok": True, "channels": started}


@router.post("/hunt/mark")
def hunt_mark():
    if not _hunt.get("active"):
        return {"ok": False, "error": "Not listening. Press Start first."}
    _hunt["events"].append(time.time())
    return {"ok": True, "marks": len(_hunt["events"])}


@router.post("/hunt/stop")
def hunt_stop():
    if not _hunt.get("active"):
        return {"ok": False, "error": "Not listening."}
    events = list(_hunt.get("events") or [])
    records: list[dict] = []
    capture_ids: dict[str, str] = {}
    for ch in _hunt.get("channels") or []:
        session = cap.get_inhale_session(ch, backend=_hunt.get("backend", "socketcan"))
        saved = session.stop()
        if saved:
            if saved.get("id"):
                capture_ids[ch] = saved["id"]
            for frame in saved.get("frames") or []:
                record = dict(frame)
                record["channel"] = ch
                records.append(record)
    channels = list(_hunt.get("channels") or [])
    _hunt.update({"active": False, "channels": [], "events": []})
    if not events:
        return {"ok": False, "error": "No presses were marked. Press Start, do the action a few times tapping Mark "
                "(or the spacebar) each time, then Stop.", "capture_ids": capture_ids}
    candidates = rev.event_responders(records, events)
    reference = rev.reference_from_events(events)
    return {"ok": True, "events": len(events), "channels": channels,
            "candidates": candidates, "capture_ids": capture_ids, "reference": reference}


# --------------------------------------------------------------------------
# Optional LLM assist (app/llm.py): name and interpret signals. Every route
# degrades to {"available": False, ...} when no API key is configured, so the
# UI can offer these without them ever 500-ing on an unconfigured device.
# --------------------------------------------------------------------------

@router.get("/llm/status")
def llm_status():
    return llm.status()


class InterpretIn(BaseModel):
    capture_id: str
    arbitration_id: int
    context_hint: str = ""
    database_id: int | None = None


@router.post("/llm/interpret")
def llm_interpret(body: InterpretIn):
    ready = llm.status()
    if not ready["available"]:
        return ready
    capture = _capture_or_404(body.capture_id)
    frames = _frames_for_id(capture, body.arbitration_id)
    if not frames:
        raise HTTPException(404, "No frames with that arbitration id in this capture")
    activity = rev.bit_activity(frames)
    try:
        return llm.interpret_message(activity, frames, body.context_hint,
                                     known_signals=_known_signals_summary(body.database_id))
    except RuntimeError as exc:
        return {"available": True, "error": str(exc)}


class NameIn(BaseModel):
    candidate: dict
    reference_hint: str = ""
    context_hint: str = ""
    database_id: int | None = None


@router.post("/llm/name")
def llm_name(body: NameIn):
    ready = llm.status()
    if not ready["available"]:
        return ready
    try:
        return llm.suggest_name(body.candidate, body.reference_hint, body.context_hint,
                                known_signals=_known_signals_summary(body.database_id))
    except RuntimeError as exc:
        return {"available": True, "error": str(exc)}


# --------------------------------------------------------------------------
# Reference recorder: record a reference by interacting with the vehicle
# --------------------------------------------------------------------------

class ReferenceStartIn(BaseModel):
    mode: str
    channel: str | None = None
    backend: str = "socketcan"
    capture_name: str = ""


@router.post("/reference/start")
def reference_start(body: ReferenceStartIn):
    """Begin recording a reference. When ``channel`` is given, also starts an
    inhale capture on that channel so the bus and the reference record
    together (marks/events line up with captured frames automatically, since
    both use the server clock)."""
    if body.mode not in rec.MODES:
        raise HTTPException(400, f"mode must be one of {rec.MODES}")
    try:
        status = rec.start(body.mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    _reference_capture["channel"] = None
    _reference_capture["backend"] = None
    _reference_capture["name"] = None
    if body.channel:
        session = cap.get_inhale_session(body.channel, backend=body.backend,
                                         channel_factory=_capture_factory(body.channel, body.backend))
        started = session.start(body.capture_name)
        if not started:
            rec.stop()
            raise HTTPException(400, "A capture is already running on that channel")
        _reference_capture["channel"] = body.channel
        _reference_capture["backend"] = body.backend
        _reference_capture["name"] = body.capture_name
    return {"ok": True, "status": status, "capturing": bool(body.channel)}


class ReferenceMarkIn(BaseModel):
    value: float


@router.post("/reference/mark")
def reference_mark(body: ReferenceMarkIn):
    return rec.mark(body.value)


@router.post("/reference/event")
def reference_event():
    return rec.event()


@router.get("/reference/status")
def reference_status():
    return rec.status()


@router.post("/reference/stop")
def reference_stop():
    """Stop the recorder (and the inhale capture it started, if any, saving
    it) and hand back a capture id plus a ready-to-use reference series."""
    raw = rec.get()
    rec.stop()

    channel = _reference_capture.get("channel")
    backend = _reference_capture.get("backend") or "socketcan"
    capture_id = None
    span = None
    if channel:
        session = cap.get_inhale_session(channel, backend=backend)
        saved = session.stop()
        if saved is not None:
            capture_id = saved.get("id")
            frames = saved.get("frames") or []
            if frames:
                timestamps = [f.get("timestamp", 0.0) for f in frames]
                span = (min(timestamps), max(timestamps))
        _reference_capture["channel"] = None
        _reference_capture["backend"] = None
        _reference_capture["name"] = None

    if raw.get("mode") == "button":
        reference = rev.reference_from_events(raw.get("events") or [], span=span)
    else:
        reference = [{"t": p["t"], "value": p["value"], "available": True} for p in raw.get("points") or []]

    return {"capture_id": capture_id, "mode": raw.get("mode"), "reference": reference}


@router.post("/reference/clear")
def reference_clear():
    return rec.clear()
