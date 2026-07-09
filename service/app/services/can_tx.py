"""Periodic CAN transmit registry.

Send a frame repeatedly on a channel until toggled off. Many vehicle controls
only take effect while their message is transmitted every cycle (the ECU expects
it continuously), so a one-shot send does nothing; this holds the state. Driven
from the ``can`` action driver (period_ms) and, through it, a cockpit key. One
background thread per active transmit; a send on an unavailable channel is a
silent no-op, so toggling one on a laptop with no bus never errors.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

log = logging.getLogger(__name__)

_lock = threading.Lock()
_active: dict[str, dict[str, Any]] = {}


def _key(channel: str, arbitration_id: int) -> str:
    return f"{channel}:{arbitration_id:X}"


def is_running(channel: str, arbitration_id: int) -> bool:
    with _lock:
        return _key(channel, arbitration_id) in _active


def list_active() -> list[dict[str, Any]]:
    with _lock:
        return [{"channel": v["channel"], "arbitration_id": v["arbitration_id"],
                 "period_ms": v["period_ms"]} for v in _active.values()]


def start(channel: str, arbitration_id: int, data, period_ms: int = 100,
          is_fd: bool = False, is_extended_id: bool = False) -> bool:
    """Begin sending the frame every ``period_ms``. False if already running."""
    key = _key(channel, arbitration_id)
    with _lock:
        if key in _active:
            return False
        stop_ev = threading.Event()
        thread = threading.Thread(
            target=_loop, name=f"can-tx-{key}", daemon=True,
            args=(channel, arbitration_id, list(data or []), max(5, int(period_ms)),
                  bool(is_fd), bool(is_extended_id), stop_ev))
        _active[key] = {"channel": channel, "arbitration_id": arbitration_id,
                        "period_ms": int(period_ms), "stop": stop_ev, "thread": thread}
        thread.start()
    return True


def stop(channel: str, arbitration_id: int) -> bool:
    key = _key(channel, arbitration_id)
    with _lock:
        entry = _active.pop(key, None)
    if not entry:
        return False
    entry["stop"].set()
    entry["thread"].join(timeout=1.0)
    return True


def toggle(channel: str, arbitration_id: int, data, period_ms: int = 100,
           is_fd: bool = False, is_extended_id: bool = False) -> bool:
    """Flip periodic sending on/off. Returns True if it is now ON."""
    if is_running(channel, arbitration_id):
        stop(channel, arbitration_id)
        return False
    start(channel, arbitration_id, data, period_ms, is_fd=is_fd, is_extended_id=is_extended_id)
    return True


def stop_all() -> None:
    with _lock:
        entries = list(_active.values())
        _active.clear()
    for entry in entries:
        entry["stop"].set()


def _loop(channel: str, arbitration_id: int, data, period_ms: int,
          is_fd: bool, is_extended_id: bool, stop_ev: threading.Event) -> None:
    from ..can import Frame, get_channel
    provider = get_channel(channel)
    frame = Frame(arbitration_id=arbitration_id, data=data, is_fd=is_fd, is_extended_id=is_extended_id)
    interval = period_ms / 1000.0
    while not stop_ev.wait(interval):
        try:
            provider.send(frame)
        except Exception as exc:  # a bus that goes away should not kill the thread
            log.info("periodic CAN tx failed on %s: %s", channel, exc)
