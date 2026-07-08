"""Transmit simulation: periodic and one-shot CAN frame playback.

A transmit list holds entries that either send raw hex data or encode named
signal values against an imported DBC (see :mod:`app.can.dbc`). A background
scheduler thread walks the enabled periodic entries on a short tick and sends
whichever are due; one-shot entries (``period_ms`` 0) send only on demand
through :meth:`SimEngine.send_once`. The scheduling decision
(:meth:`SimEngine.tick`) is pure with respect to the clock and entry list
passed in, so a test can drive it directly without a real thread or CAN
hardware: the socketcan provider already degrades to a safe no-op when there
is no adapter attached (see :mod:`app.can.socketcan`).

The transmit list persists in a JSON state file (``can_sim.json`` under
data_dir) through the same atomic :class:`~app.services.state.StateFile`
pattern used for the layout and action library, so it survives a restart and
stays consistent across uvicorn workers.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Callable

from ..config import settings
from ..services.state import StateFile
from .base import STANDARD_ID_MAX, Frame, parse_arbitration_id, parse_data_bytes
from .registry import get_channel

log = logging.getLogger(__name__)

# Scheduler poll granularity: an entry fires no later than this long after
# its period elapses.
TICK_SECONDS = 0.05


def _store() -> StateFile:
    return StateFile(settings.data_dir / "can_sim.json", default={"entries": []})


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# -- persistence --------------------------------------------------------

def list_entries() -> list[dict[str, Any]]:
    return _store().read().get("entries", [])


def get_entry(entry_id: str) -> dict[str, Any] | None:
    for entry in list_entries():
        if entry.get("id") == entry_id:
            return entry
    return None


def create_entry(data: dict[str, Any]) -> dict[str, Any]:
    entry = dict(data)
    entry["id"] = entry.get("id") or _new_id()
    store = _store()
    doc = store.read()
    entries = doc.get("entries", [])
    entries.append(entry)
    doc["entries"] = entries
    store.write(doc)
    return entry


def update_entry(entry_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    store = _store()
    doc = store.read()
    entries = doc.get("entries", [])
    for i, entry in enumerate(entries):
        if entry.get("id") == entry_id:
            updated = dict(entry)
            updated.update(data)
            updated["id"] = entry_id
            entries[i] = updated
            doc["entries"] = entries
            store.write(doc)
            return updated
    return None


def delete_entry(entry_id: str) -> bool:
    store = _store()
    doc = store.read()
    entries = doc.get("entries", [])
    remaining = [e for e in entries if e.get("id") != entry_id]
    if len(remaining) == len(entries):
        return False
    doc["entries"] = remaining
    store.write(doc)
    return True


def set_enabled(entry_id: str, enabled: bool) -> dict[str, Any] | None:
    return update_entry(entry_id, {"enabled": enabled})


# -- frame building (pure) -----------------------------------------------

def build_frame(entry: dict[str, Any], dbc_text: str | None = None,
                counter: int | None = None) -> Frame:
    """Build the :class:`Frame` a transmit entry describes.

    Uses ``database_id`` + ``message`` + ``signals`` to encode via cantools
    when all three are present on the entry (the caller must resolve and pass
    the database's ``dbc_text``); otherwise sends the entry's raw hex
    ``data``. Raises ``ValueError`` with a user-facing message on anything
    malformed, so callers can surface it directly.
    """
    arbitration_id = entry.get("arbitration_id")
    if arbitration_id is None or arbitration_id == "":
        raise ValueError("Entry has no arbitration id")
    if isinstance(arbitration_id, str):
        arbitration_id = parse_arbitration_id(arbitration_id)

    uses_database = (
        entry.get("database_id")
        and entry.get("message") not in (None, "")
        and entry.get("signals") is not None
    )
    if uses_database:
        if not dbc_text:
            raise ValueError("No DBC text available to encode this entry's signals")
        from .dbc import encode as dbc_encode
        data = dbc_encode(dbc_text, entry["message"], entry.get("signals") or {},
                          counter=counter, checksum=entry.get("checksum", ""))
    else:
        raw = entry.get("data") or ""
        data = parse_data_bytes(raw) if isinstance(raw, str) else list(raw)

    is_fd = bool(entry.get("is_fd", False))
    is_extended = bool(entry.get("is_extended_id") or arbitration_id > STANDARD_ID_MAX)
    frame = Frame(arbitration_id=arbitration_id, data=data, is_fd=is_fd, is_extended_id=is_extended)
    error = frame.validate()
    if error:
        raise ValueError(error)
    return frame


DbcTextResolver = Callable[[int], "str | None"]
FrameSender = Callable[[str, str, Frame], bool]


def _default_dbc_text_resolver(database_id: int) -> str | None:
    from ..db import session_scope
    from ..db.models import CanDatabase
    with session_scope() as s:
        database = s.get(CanDatabase, database_id)
        return database.dbc_text if database else None


def _default_sender(backend: str, channel: str, frame: Frame) -> bool:
    return get_channel(channel, backend=backend).send(frame)


# -- scheduler --------------------------------------------------------------

class SimEngine:
    """Background scheduler for periodic transmit entries.

    :meth:`tick` is the pure scheduling decision: given the current entries
    and a clock value, send whichever enabled periodic entries are due and
    return what happened. The background thread (started by :meth:`start`)
    just calls :meth:`tick` in a loop on a daemon thread, so tests exercise
    the scheduling logic by calling ``tick`` directly with a synthetic clock
    and entry list, with no real timers and no hardware.
    """

    def __init__(
        self,
        dbc_text_resolver: DbcTextResolver | None = None,
        sender: FrameSender | None = None,
    ) -> None:
        self._dbc_text_resolver = dbc_text_resolver or _default_dbc_text_resolver
        self._sender = sender or _default_sender
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._next_due: dict[str, float] = {}

    def _resolve_dbc_text(self, entry: dict[str, Any]) -> str | None:
        database_id = entry.get("database_id")
        if not database_id:
            return None
        try:
            return self._dbc_text_resolver(database_id)
        except Exception as exc:
            log.info("Could not resolve DBC text for database %s: %s", database_id, exc)
            return None

    def send_entry(self, entry: dict[str, Any]) -> tuple[bool, str | None]:
        """Build and send one entry's frame now. Returns ``(ok, error)``."""
        try:
            dbc_text = self._resolve_dbc_text(entry)
            # A checksum-protected message needs a rolling counter that
            # increments each transmit, so a real module accepts the frame.
            counter = None
            if entry.get("checksum"):
                from . import checksum as checksum_mod
                counter = checksum_mod.next_counter(str(entry.get("id") or entry.get("name")))
            frame = build_frame(entry, dbc_text, counter=counter)
        except ValueError as exc:
            return False, str(exc)
        backend = entry.get("backend") or "socketcan"
        channel = entry.get("channel") or "can0"
        try:
            ok = self._sender(backend, channel, frame)
        except Exception as exc:
            log.info("CAN sim send failed for entry %s: %s", entry.get("id"), exc)
            return False, str(exc)
        return ok, (None if ok else "send failed")

    def send_once(self, entry_id: str) -> tuple[bool, str | None]:
        entry = get_entry(entry_id)
        if entry is None:
            return False, "No such transmit entry"
        return self.send_entry(entry)

    def tick(
        self,
        now: float | None = None,
        entries: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Send every enabled periodic entry due at ``now``.

        ``now`` and ``entries`` default to the real clock and the persisted
        transmit list, but a test can pass both explicitly to drive the
        scheduling decision deterministically. Returns one result dict per
        entry that fired: ``{"id", "ok", "error"}``.
        """
        now = time.monotonic() if now is None else now
        entries = list_entries() if entries is None else entries
        results = []
        seen_ids = set()
        for entry in entries:
            entry_id = entry.get("id")
            seen_ids.add(entry_id)
            period_ms = entry.get("period_ms") or 0
            if not entry.get("enabled") or period_ms <= 0:
                continue
            due = self._next_due.get(entry_id)
            if due is None:
                # First time seeing this entry: fire it immediately, then
                # settle into its regular period.
                due = now
            if now >= due:
                ok, error = self.send_entry(entry)
                self._next_due[entry_id] = now + period_ms / 1000.0
                results.append({"id": entry_id, "ok": ok, "error": error})
        # Drop bookkeeping for entries that no longer exist, so a deleted and
        # later recreated entry (even reusing an id) starts its schedule
        # fresh instead of inheriting a stale due time.
        for stale_id in set(self._next_due) - seen_ids:
            self._next_due.pop(stale_id, None)
        return results

    def is_running(self) -> bool:
        return self._running

    def start(self) -> bool:
        """Start the background thread. Returns False if already running."""
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._thread = threading.Thread(target=self._loop, daemon=True, name="can-sim")
            self._thread.start()
            return True

    def stop(self) -> bool:
        """Stop the background thread. Returns False if it was not running."""
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
        while self._running:
            try:
                self.tick()
            except Exception as exc:
                log.info("CAN sim tick failed: %s", exc)
            time.sleep(TICK_SECONDS)


# Module-level singleton shared by the router and anything else in-process.
engine = SimEngine()
