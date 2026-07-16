"""Signal Finder API: statistically reverse engineer which CAN field carries
a signal a bench technician can see or trigger by hand, from a capture plus a
reference series they recorded while operating the real control.

A thin REST wrapper over :mod:`app.can.reverse`'s pure search and statistics;
the algorithm itself never touches the database or a capture file, only
plain lists of frame records and reference points.
"""
from __future__ import annotations

import re
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import llm
from ..actions import registry as action_registry
from ..actions.registry import ActionSpec
from ..can import capture as cap
from ..can import get_channel
from ..can import registry as can_registry
from ..can import reverse as rev
from ..db import CanDatabase, session_scope
from ..services import cockpit as cockpit_svc
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


class CrossCorrelateIn(BaseModel):
    capture_id: str
    database_id: int


@router.post("/cross-correlate")
def cross_correlate_route(body: CrossCorrelateIn):
    """Automatically find unknown fields that mirror a signal the database
    already decodes (redundant or higher-resolution proprietary copies), with no
    reference to record by hand."""
    capture = _capture_or_404(body.capture_id)
    dbc_text = _dbc_text_or_404(body.database_id)
    grouped = _frames_by_id(capture)
    from ..db import CanMessage
    known: list[dict] = []
    with session_scope() as s:
        for message in s.query(CanMessage).filter_by(database_id=body.database_id).all():
            for sig in message.signals:
                known.append({"arbitration_id": message.arbitration_id, "signal": sig.name})
    matches = rev.cross_correlate(grouped, dbc_text, known)
    return {"matches": matches, "known_count": len(known)}


def _pick_active_frame(frames: list[dict], byte: int | None) -> dict:
    """A representative 'the control was active' frame to replay: the one whose
    target byte is furthest from its resting (most common) value, so firing it
    reproduces the pressed state. Falls back to the last frame."""
    if byte is None or not frames:
        return frames[-1] if frames else {}
    from collections import Counter
    vals = []
    for f in frames:
        data = f.get("data") or []
        vals.append(data[byte] if byte < len(data) else 0)
    resting = Counter(vals).most_common(1)[0][0]
    best = max(range(len(frames)), key=lambda i: abs(vals[i] - resting))
    return frames[best]


class FireIn(BaseModel):
    capture_id: str
    arbitration_id: int
    channel: str = ""
    byte: int | None = None
    # Flood mode: send the frame every period_ms for burst_ms, to out-rate a
    # genuine broadcaster so the ECU accepts the command. 0 = a single send.
    burst_ms: int = 0
    period_ms: int = 10


@router.post("/fire")
def fire_route(body: FireIn):
    """Actuate a found control to test what it does. When a target byte is known,
    this changes only the bits that control owns on the frame that is live on the
    bus right now, leaving the other signals in that message untouched. Without a
    target byte it falls back to replaying a representative captured frame.
    Sending onto a live vehicle bus can have real effects, so the UI confirms
    first."""
    from ..can import Frame
    from ..can import overlay as ov
    capture = _capture_or_404(body.capture_id)
    frames = _frames_for_id(capture, body.arbitration_id)
    if not frames:
        raise HTTPException(404, "No frames with that id in this capture")
    channel = body.channel or capture.get("channel") or "can0"
    backend = capture.get("backend") or "socketcan"
    # A representative captured frame is only the fallback template, used to size
    # the frame and to fill in when the id is not currently on the bus.
    template = _pick_active_frame(frames, body.byte)
    template_data = list(template.get("data") or [])
    is_fd = bool(template.get("is_fd"))
    is_extended_id = bool(template.get("is_extended_id"))
    # A CAN-FD frame must go out on a socket opened fd=True; a classic socket
    # rejects it and the send silently transmits nothing. Force fd when the
    # frame is FD so an FD control actually fires (classic frames pass fd=None,
    # leaving the channel's configured mode untouched).
    provider = get_channel(channel, backend=backend, fd=True if is_fd else None)
    if not provider.available:
        return {"ok": False, "error": getattr(provider, "last_error", None) or f"{channel} is not available."}
    if body.byte is None:
        data, source = template_data, "frame"
    else:
        spec = ov.derive_mask(frames, body.byte)
        data, source = ov.overlaid_data(provider, body.arbitration_id, spec["byte"],
                                        spec["mask"], spec["active"], template=template_data)
    # If the message carries a rolling counter and/or checksum, an ECU rejects a
    # frame whose counter is stale or whose checksum is wrong (overlaying a bit
    # breaks it). Regenerate a valid frame: fix the checksum for a single send,
    # and advance the counter per frame during a flood.
    protection = rev.message_protection([list(f.get("data") or []) for f in frames[:120]],
                                        body.arbitration_id)
    if body.burst_ms and body.burst_ms > 0:
        from ..services import can_tx
        period = max(2, int(body.period_ms or 10))
        duration = min(5000, int(body.burst_ms))
        n = can_tx.burst(channel, body.arbitration_id, data, period_ms=period,
                         duration_ms=duration, is_fd=is_fd, is_extended_id=is_extended_id,
                         protection=protection if protection["protected"] else None)
        if n == 0:
            return {"ok": False, "error": f"Could not flood 0x{body.arbitration_id:X} on {channel} "
                    "(interface not accepting the frame; classic vs CAN-FD?)."}
        return {"ok": True, "channel": channel, "arbitration_id": body.arbitration_id,
                "data": data, "source": source, "mode": "burst", "injected": n,
                "period_ms": period, "burst_ms": duration, "protected": protection["protected"]}
    if protection["protected"]:
        data = rev.apply_protection(data, body.arbitration_id, protection, tick=0)
    try:
        sent = provider.send(Frame(arbitration_id=body.arbitration_id, data=data,
                                   is_fd=is_fd, is_extended_id=is_extended_id))
    except Exception as exc:
        return {"ok": False, "error": f"Send failed: {exc}"}
    if not sent:
        return {"ok": False, "error": "The interface did not accept the frame (is it up?)."}
    return {"ok": True, "channel": channel, "arbitration_id": body.arbitration_id,
            "data": data, "source": source, "mode": "single", "protected": protection["protected"]}


def _send_suggestion(frames: list[dict]) -> dict:
    """Suggest one-shot vs periodic from how often the message is on the bus. A
    message sent many times a second is usually a state the ECU expects every
    cycle (periodic to have effect); a sparse message is a one-off event."""
    ts = sorted(float(f.get("timestamp", 0.0)) for f in frames)
    if len(ts) < 3 or (ts[-1] - ts[0]) <= 0:
        return {"mode": "oneshot", "period_ms": 0, "rate_hz": 0.0,
                "reason": "This message appears rarely, so a single send per press is likely right."}
    rate = (len(ts) - 1) / (ts[-1] - ts[0])
    if rate >= 5:
        period = max(10, int(round((1000.0 / rate) / 10.0)) * 10)
        return {"mode": "periodic", "period_ms": period, "rate_hz": round(rate, 1),
                "reason": f"This message is sent about {round(rate)} times a second, so it likely needs to be "
                          f"sent continuously (every {period} ms) to have an effect."}
    return {"mode": "oneshot", "period_ms": 0, "rate_hz": round(rate, 1),
            "reason": "This message appears only occasionally, so sending it once per press is likely right."}


class SendSuggestionIn(BaseModel):
    capture_id: str
    arbitration_id: int


@router.post("/send-suggestion")
def send_suggestion_route(body: SendSuggestionIn):
    capture = _capture_or_404(body.capture_id)
    frames = _frames_for_id(capture, body.arbitration_id)
    if not frames:
        raise HTTPException(404, "No frames with that id in this capture")
    return _send_suggestion(frames)


class AddToCockpitIn(BaseModel):
    capture_id: str
    arbitration_id: int
    channel: str = ""
    byte: int | None = None
    name: str
    period_ms: int = 0
    burst_ms: int = 0
    cockpit_id: int | None = None
    new_cockpit_name: str = ""


@router.post("/add-to-cockpit")
def add_to_cockpit_route(body: AddToCockpitIn):
    """Find -> save -> cockpit in one call: make a CAN-send action from the
    found message (one-shot or periodic) and drop it on a cockpit as a key."""
    capture = _capture_or_404(body.capture_id)
    frames = _frames_for_id(capture, body.arbitration_id)
    if not frames:
        raise HTTPException(404, "No frames with that id in this capture")
    from ..can import overlay as ov
    channel = body.channel or capture.get("channel") or "can0"
    frame = _pick_active_frame(frames, body.byte)
    # The captured bytes are stored only as a resting template (the fallback the
    # driver overlays onto when the id is not live). The control itself is stored
    # as a bit mask so the driver changes only its bits on the live frame.
    data_hex = " ".join(f"{int(b) & 0xFF:02X}" for b in (frame.get("data") or []))
    name = (body.name or "").strip() or f"CAN {body.arbitration_id:X}"
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:32] or "can"
    action_id = f"can_{slug}_{body.arbitration_id:X}"
    params = {"channel": channel, "arbitration_id": f"0x{body.arbitration_id:X}",
              "data": data_hex, "is_fd": bool(frame.get("is_fd")),
              "is_extended_id": bool(frame.get("is_extended_id")),
              "period_ms": int(body.period_ms or 0), "burst_ms": int(body.burst_ms or 0)}
    if body.byte is not None:
        spec = ov.derive_mask(frames, body.byte)
        if spec["mask"]:
            params.update({"overlay_byte": spec["byte"], "overlay_mask": spec["mask"],
                           "overlay_value": spec["active"]})
    action_registry.upsert_action(ActionSpec.from_dict({
        "id": action_id, "label": name, "driver": "can",
        "params": params,
        "icon": "bi-dpad-fill", "color": "#F2006E", "category": "CAN",
    }))
    if body.cockpit_id:
        cockpit_id = body.cockpit_id
    else:
        cockpit_id = cockpit_svc.create_cockpit(name=(body.new_cockpit_name or "My cockpit"))["id"]
    element = cockpit_svc.add_element(cockpit_id, {"type": "key", "action_id": action_id, "label": name})
    return {"ok": True, "action_id": action_id, "cockpit_id": cockpit_id,
            "periodic": bool(body.period_ms), "data": data_hex, "element": element}


def _command_from_capture(capture: dict, arbitration_id: int, byte: int | None,
                          channel: str, period_ms: int) -> dict:
    """Build a reusable command dict (the shape the can driver and the command
    library share) from a found control: the frame's resting template plus, when
    a target byte is known, the overlay bit mask so only its bits change."""
    from ..can import overlay as ov
    frames = _frames_for_id(capture, arbitration_id)
    frame = _pick_active_frame(frames, byte)
    command = {
        "channel": channel or capture.get("channel") or "can0",
        "arbitration_id": f"0x{arbitration_id:X}",
        "data": " ".join(f"{int(b) & 0xFF:02X}" for b in (frame.get("data") or [])),
        "is_fd": bool(frame.get("is_fd")), "is_extended_id": bool(frame.get("is_extended_id")),
        "period_ms": int(period_ms or 0),
    }
    if byte is not None:
        spec = ov.derive_mask(frames, byte)
        if spec["mask"]:
            command.update({"overlay_byte": spec["byte"], "overlay_mask": spec["mask"],
                            "overlay_value": spec["active"]})
    return command


class SaveCommandIn(BaseModel):
    capture_id: str
    arbitration_id: int
    channel: str = ""
    byte: int | None = None
    name: str = ""
    period_ms: int = 0
    to_library: bool = True
    to_vehicle_slot: str = ""


@router.post("/save-command")
def save_command_route(body: SaveCommandIn):
    """Save a found command to the shared library, to a slot on the active
    vehicle, or both. The command carries the overlay mask so it changes only the
    control's bits when replayed."""
    from ..services import command_library as library_svc
    from ..services import profiles as profiles_svc
    capture = _capture_or_404(body.capture_id)
    if not _frames_for_id(capture, body.arbitration_id):
        raise HTTPException(404, "No frames with that id in this capture")
    name = (body.name or "").strip() or f"CAN {body.arbitration_id:X}"
    command = _command_from_capture(capture, body.arbitration_id, body.byte, body.channel, body.period_ms)
    saved = {"library": False, "vehicle": False}
    if body.to_library:
        library_svc.add_command(name, command)
        saved["library"] = True
    if body.to_vehicle_slot:
        active_id = profiles_svc.get_active_profile_id()
        if active_id is None:
            return {"ok": False, "error": "No active vehicle. Pick one from the top selector first.",
                    "saved": saved}
        profiles_svc.set_control(active_id, body.to_vehicle_slot, command, label=name, source="finder")
        saved["vehicle"] = True
    return {"ok": True, "saved": saved, "name": name, "command": command}


class ToWorkbenchIn(BaseModel):
    capture_id: str
    arbitration_id: int
    channel: str = ""
    byte: int | None = None
    name: str = ""
    period_ms: int = 0


@router.post("/to-workbench")
def to_workbench_route(body: ToWorkbenchIn):
    """Push a found control into the transmit workbench (the Simulate/send panel)
    as a ready-to-edit entry, so you can tweak the bytes live and adjust the rate
    while it transmits."""
    from ..can import simulation as sim
    capture = _capture_or_404(body.capture_id)
    if not _frames_for_id(capture, body.arbitration_id):
        raise HTTPException(404, "No frames with that id in this capture")
    name = (body.name or "").strip() or f"CAN {body.arbitration_id:X}"
    command = _command_from_capture(capture, body.arbitration_id, body.byte, body.channel, body.period_ms)
    entry = sim.create_entry({
        "name": name, "channel": command["channel"],
        "arbitration_id": int(body.arbitration_id), "data": command["data"],
        "period_ms": int(body.period_ms or 0), "is_fd": command["is_fd"],
        "is_extended_id": command["is_extended_id"], "enabled": False,
    })
    return {"ok": True, "entry_id": entry.get("id"), "name": name}


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
        # Keep hunt captures in memory only (they stay in the recent-captures
        # cache the Bits view reads from) instead of writing tens of thousands of
        # frames to the SD card on a busy CAN-FD bus, which stalls the device. Cap
        # the frame count so a firehose bus cannot exhaust memory.
        if session.start(f"hunt {ch}", persist=False, max_frames=200000):
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


class VerifyControlIn(BaseModel):
    capture_id: str
    arbitration_id: int
    channel: str
    byte: int | None = None
    baseline_s: float = 1.2
    inject_s: float = 1.5
    period_ms: int = 20


@router.post("/verify-control")
def verify_control_route(body: VerifyControlIn):
    """Prove whether a found control is a real command or just a status mirror.

    Listens to every bus at rest, then injects the candidate for a moment while
    still listening, and reports any byte that starts moving only while the
    candidate is being sent. A downstream reaction means the frame actually does
    something; no reaction means it is almost certainly a status the module
    reports and the real command is elsewhere. This transmits on a live bus, so
    it is a deliberate action."""
    from ..can import Frame, detect
    from ..can import overlay as ov
    capture = _capture_or_404(body.capture_id)
    frames = _frames_for_id(capture, body.arbitration_id)
    if not frames:
        raise HTTPException(404, "No frames with that id in this capture")
    template = _pick_active_frame(frames, body.byte)
    template_data = list(template.get("data") or [])
    is_fd = bool(template.get("is_fd"))
    is_extended_id = bool(template.get("is_extended_id"))
    # Open the transmit channel fd=True for a CAN-FD frame; a classic socket
    # rejects the FD send and injects 0 frames, which used to read as "no
    # effect" and made a real control look like a status mirror.
    provider = get_channel(body.channel, backend=capture.get("backend") or "socketcan",
                           fd=True if is_fd else None)
    if not provider.available:
        return {"ok": False, "error": getattr(provider, "last_error", None) or f"{body.channel} is not available."}
    if body.byte is None:
        send_data = template_data
    else:
        spec = ov.derive_mask(frames, body.byte)
        send_data = ov.apply_overlay(template_data, spec["byte"], spec["mask"], spec["active"])
    send_frame = Frame(arbitration_id=body.arbitration_id, data=send_data,
                       is_fd=is_fd, is_extended_id=is_extended_id)
    # Catch a frame that cannot go out before we mislead the user: an invalid
    # length or a CAN-FD frame on a classic channel would otherwise fail silently
    # inside the loop and look like "no effect".
    invalid = send_frame.validate()
    if invalid:
        return {"ok": False, "error": f"Cannot inject 0x{body.arbitration_id:X}: {invalid}"}

    try:
        channels = [i["name"] for i in detect.list_can_interfaces() if i.get("up")] or [body.channel]
    except Exception:
        channels = [body.channel]
    started: list[str] = []
    try:
        for ch in channels:
            session = cap.get_inhale_session(ch, backend="socketcan",
                                             channel_factory=_capture_factory(ch, "socketcan"))
            # Verify only diffs frames in memory: never write these captures to
            # disk (that thrashes the SD card on a busy CAN-FD bus), and cap the
            # frame count so a firehose bus cannot exhaust memory.
            if session.start(f"verify {ch}", persist=False, max_frames=200000):
                started.append(ch)
    except Exception as exc:
        for ch in started:
            try:
                cap.get_inhale_session(ch, backend="socketcan").stop()
            except Exception:
                pass
        return {"ok": False, "error": f"Could not start listening on the bus: {exc}"}
    if not started:
        return {"ok": False, "error": "Could not listen on any bus (a capture may already be running)."}

    injected = 0
    send_failures = 0
    send_error: str | None = None
    inject_start = time.time()
    try:
        time.sleep(max(0.0, min(5.0, body.baseline_s)))
        inject_start = time.time()
        period = max(0.005, body.period_ms / 1000.0)
        deadline = inject_start + max(0.1, min(5.0, body.inject_s))
        while time.time() < deadline:
            try:
                if provider.send(send_frame):
                    injected += 1
                else:
                    send_failures += 1
            except Exception as exc:
                send_error = str(exc)
                send_failures += 1
                # If nothing is going out at all, stop wasting the window.
                if injected == 0 and send_failures >= 3:
                    break
            time.sleep(period)
    finally:
        records: list[dict] = []
        for ch in started:
            try:
                saved = cap.get_inhale_session(ch, backend="socketcan").stop()
            except Exception:
                saved = None
            for frame in (saved or {}).get("frames") or []:
                rec_frame = dict(frame)
                rec_frame["channel"] = ch
                records.append(rec_frame)

    # Nothing actually went out: report that plainly instead of calling it a
    # status. A silent send failure was the bug that made a status and a failed
    # injection look identical.
    if injected == 0:
        reason = send_error or ("the interface did not accept the frame for transmit. Check that "
                                f"{body.channel} is up and that the frame type matches the bus "
                                "(classic vs CAN-FD).")
        return {"ok": False, "channel": body.channel, "arbitration_id": body.arbitration_id,
                "injected": 0, "error": f"Could not inject 0x{body.arbitration_id:X} on {body.channel}: {reason}"}

    baseline = [r for r in records if float(r.get("timestamp", 0.0)) < inject_start]
    during = [r for r in records if float(r.get("timestamp", 0.0)) >= inject_start]
    reactors = rev.injection_reactors(baseline, during, exclude=(body.channel, body.arbitration_id))
    return {"ok": True, "channel": body.channel, "arbitration_id": body.arbitration_id,
            "injected": injected, "buses": started, "data": send_data,
            "effect": bool(reactors), "reactors": reactors[:25]}


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
