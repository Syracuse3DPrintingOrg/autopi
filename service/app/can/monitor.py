"""Live CAN bus monitor: a background reader per channel that keeps a ring
buffer of recently received frames, optionally decoded against a DBC.

The ring buffer update and the decode step are pure functions of a
:class:`~app.can.base.Frame` (or a plain frame record dict) so they are
unit-testable without a real thread or CAN hardware: a test injects frames
directly into :func:`ingest_frame` and :func:`decode_record`. The background
reader (:class:`MonitorChannel`) is a thin daemon-thread loop around
``get_channel(channel).recv(timeout)`` and :func:`ingest_frame`; when the
channel's provider is unavailable (no hardware, no python-can), ``recv``
already degrades to returning ``None`` on every call (see
:mod:`app.can.socketcan`), so the reader just idles and :meth:`status`
reports ``live: False`` instead of raising.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

from .base import Frame
from .registry import get_channel

log = logging.getLogger(__name__)

# How many recent frames to keep per channel.
DEFAULT_BUFFER_SIZE = 500

# Ceiling on distinct arbitration ids tracked for the by-id view. A normal bus
# shows tens to low hundreds; this only bounds memory if a bus sprays randomised
# extended ids. Ids already tracked keep updating once the cap is reached.
MAX_TRACKED_IDS = 4096
# How long recv() blocks waiting for a frame before checking the stop flag.
RECV_TIMEOUT = 0.5


def _frame_to_record(frame: Frame, timestamp: float) -> dict[str, Any]:
    """Turn a :class:`Frame` into the plain-dict record kept in the buffer."""
    return {
        "arbitration_id": frame.arbitration_id,
        "data": list(frame.data),
        "hex": " ".join(f"{b:02X}" for b in frame.data),
        "timestamp": timestamp,
        "is_extended_id": frame.is_extended_id,
        "is_fd": frame.is_fd,
        "is_remote": frame.is_remote,
    }


def ingest_frame(
    buffer: deque,
    counts: dict[int, int],
    frame: Frame,
    timestamp: float | None = None,
    latest: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Append one received frame to a ring buffer and bump its id count.

    Pure with respect to the ``buffer``/``counts`` passed in (a
    ``collections.deque(maxlen=...)`` handles the ring trimming itself), so a
    test can drive it directly with a synthetic clock and hand-built
    :class:`Frame` values, no thread or hardware involved. Returns the record
    that was appended.

    ``latest``, when given, is updated with this id's newest record and is NOT
    ring-trimmed: the ring buffer only holds the last few hundred frames, so on a
    busy bus an id that stops transmitting scrolls out of it within a second and
    would disappear from any view built from the buffer. Keeping the newest record
    per id separately is what lets a by-id view show every id ever seen, with the
    payload it last sent, including ids that have gone quiet.
    """
    timestamp = time.time() if timestamp is None else timestamp
    record = _frame_to_record(frame, timestamp)
    counts[frame.arbitration_id] = counts.get(frame.arbitration_id, 0) + 1
    record["count"] = counts[frame.arbitration_id]
    buffer.append(record)
    if latest is not None:
        previous = latest.get(frame.arbitration_id)
        entry = dict(record)
        # first_seen lets the UI tell a long-standing id from one that just
        # appeared, which is often the interesting one when hunting a control.
        entry["first_seen"] = previous["first_seen"] if previous else timestamp
        if len(latest) < MAX_TRACKED_IDS or frame.arbitration_id in latest:
            latest[frame.arbitration_id] = entry
    return record


def decode_record(record: dict[str, Any], dbc_text: str | None,
                  *, obd2_overlay: bool = False) -> dict[str, Any] | None:
    """Decode one frame record against a DBC, and (when ``obd2_overlay`` is on)
    also as a standard OBD-II response, merging the two. Returns ``None`` if
    neither produces anything.

    Never raises: an id the database does not define, a malformed DBC, or a
    missing ``dbc_text`` all just mean "no decode available" for this frame,
    which is the normal case for most traffic on a bus until the right
    database is picked. The OBD2 overlay adds the standard diagnostics signals
    (speed, RPM, coolant, ...) on top of whatever database is active, since those
    responses decode the same on any vehicle without a vehicle-specific database.
    """
    out: dict[str, Any] = {}
    if dbc_text:
        from . import dbc as dbc_mod
        try:
            decoded = dbc_mod.decode(dbc_text, record["arbitration_id"], bytes(record["data"]))
            if decoded:
                out.update(decoded)
        except Exception:
            pass
    if obd2_overlay:
        from . import diagnostics
        out.update(diagnostics.decode_obd2_frame(record["arbitration_id"], record.get("data") or []))
    return out or None


class MonitorChannel:
    """Background reader for one CAN channel, with a bounded frame history."""

    def __init__(self, channel: str, backend: str = "socketcan",
                 buffer_size: int = DEFAULT_BUFFER_SIZE) -> None:
        self.channel = channel
        self.backend = backend
        self._buffer: deque = deque(maxlen=buffer_size)
        self._counts: dict[int, int] = {}
        # Newest record per arbitration id, never ring-trimmed, so the by-id view
        # keeps showing an id (and what it last sent) after it goes quiet.
        self._latest: dict[int, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._error: str | None = None

    def is_running(self) -> bool:
        return self._running

    def is_live(self) -> bool:
        """Whether the underlying provider could plausibly deliver frames."""
        try:
            return get_channel(self.channel, backend=self.backend).available
        except Exception:
            return False

    def frames(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._buffer)

    def latest_by_id(self) -> list[dict[str, Any]]:
        """The newest record for every arbitration id seen since the last clear,
        lowest id first. Ids that have stopped transmitting stay in this list with
        the payload they last sent, which is what makes a by-id view usable for
        spotting which byte moves when you operate a control."""
        with self._lock:
            return [dict(entry) for _, entry in sorted(self._latest.items())]

    def clear(self) -> None:
        """Forget everything seen so far (frames, per-id counts, and the by-id
        table), so a fresh look at the bus is not coloured by earlier traffic."""
        with self._lock:
            self._buffer.clear()
            self._counts.clear()
            self._latest.clear()

    def status(self) -> dict[str, Any]:
        with self._lock:
            frame_count = len(self._buffer)
            unique_ids = len(self._counts)
        return {
            "channel": self.channel,
            "backend": self.backend,
            "running": self._running,
            "live": self.is_live(),
            "frame_count": frame_count,
            "unique_ids": unique_ids,
            "error": self._error,
        }

    def start(self) -> bool:
        """Start the background reader thread. Returns False if already running."""
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._error = None
            self._thread = threading.Thread(
                target=self._loop, daemon=True, name=f"can-monitor-{self.channel}")
            self._thread.start()
            return True

    def stop(self) -> bool:
        """Stop the background reader. Returns False if it was not running."""
        with self._lock:
            if not self._running:
                return False
            self._running = False
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None
        return True

    def _loop(self) -> None:
        provider = get_channel(self.channel, backend=self.backend)
        while self._running:
            try:
                frame = provider.recv(timeout=RECV_TIMEOUT)
            except Exception as exc:
                # A provider must never raise out of recv(), but stay
                # resilient anyway: log, note the error, and keep polling
                # rather than let the reader thread die silently.
                log.info("CAN monitor recv failed on %s: %s", self.channel, exc)
                with self._lock:
                    self._error = str(exc)
                time.sleep(RECV_TIMEOUT)
                continue
            if frame is None:
                continue
            with self._lock:
                ingest_frame(self._buffer, self._counts, frame, latest=self._latest)


# -- module-level registry, one MonitorChannel per (backend, channel) -------

_monitors: dict[str, MonitorChannel] = {}


def _key(channel: str, backend: str) -> str:
    return f"{backend}:{channel}"


def get_monitor(channel: str, backend: str = "socketcan") -> MonitorChannel:
    """Return the shared monitor for this channel, creating it on first use."""
    key = _key(channel, backend)
    monitor = _monitors.get(key)
    if monitor is None:
        monitor = MonitorChannel(channel, backend=backend)
        _monitors[key] = monitor
    return monitor


def start_monitor(channel: str, backend: str = "socketcan") -> bool:
    return get_monitor(channel, backend=backend).start()


def stop_monitor(channel: str, backend: str = "socketcan") -> bool:
    key = _key(channel, backend)
    monitor = _monitors.get(key)
    if monitor is None:
        return False
    return monitor.stop()


def list_statuses() -> list[dict[str, Any]]:
    return [m.status() for m in _monitors.values()]


def reset_monitors() -> None:
    """Stop and drop every cached monitor. Mainly for tests."""
    for monitor in _monitors.values():
        try:
            monitor.stop()
        except Exception:
            pass
    _monitors.clear()
