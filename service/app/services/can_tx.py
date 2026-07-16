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
import random
import threading
import time
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


def burst(channel: str, arbitration_id: int, data, *, period_ms: int = 10,
          duration_ms: int = 1000, is_fd: bool = False, is_extended_id: bool = False,
          protection: dict | None = None) -> int:
    """Send the frame every ``period_ms`` for ``duration_ms``, then stop.

    A momentary command that fights a genuine broadcaster (an ECU resending the
    real value every ~100 ms) loses if you send it once: the real value arrives
    right after and wins. Flooding the command faster than the broadcaster for a
    short window gets it accepted. When ``protection`` is given (a rolling counter
    and/or checksum spec from the analyzer), each frame gets a fresh, advancing
    counter and a recomputed checksum, so a protected message is not rejected.
    Returns the number of frames actually sent (0 when the channel is
    unavailable). Blocks for up to ``duration_ms``; callers that must not block (a
    cockpit key press) run this in a thread."""
    from ..can import Frame, get_channel
    provider = get_channel(channel, fd=True if is_fd else None)
    if not getattr(provider, "available", False):
        return 0
    base = list(data or [])
    fixed_frame = None
    if not protection:
        fixed_frame = Frame(arbitration_id=arbitration_id, data=base,
                            is_fd=bool(is_fd), is_extended_id=bool(is_extended_id))
    period = max(0.002, int(period_ms) / 1000.0)
    deadline = time.monotonic() + max(0.0, int(duration_ms) / 1000.0)
    sent = 0
    tick = 0
    while time.monotonic() < deadline:
        if fixed_frame is not None:
            frame = fixed_frame
        else:
            from ..can import reverse as rev
            frame = Frame(arbitration_id=arbitration_id,
                          data=rev.apply_protection(base, arbitration_id, protection, tick),
                          is_fd=bool(is_fd), is_extended_id=bool(is_extended_id))
        try:
            if provider.send(frame):
                sent += 1
        except Exception as exc:  # a bus that drops out should not raise to the caller
            log.info("burst CAN tx failed on %s: %s", channel, exc)
            break
        tick += 1
        time.sleep(period)
    return sent


def fuzz(channel: str, arbitration_id: int, template, fuzz_bytes, *, count: int = 100,
         period_ms: int = 50, is_fd: bool = False, is_extended_id: bool = False,
         rng: "random.Random | None" = None) -> list[dict]:
    """Send ``count`` frames on ``arbitration_id``, randomizing the byte positions
    in ``fuzz_bytes`` on each frame while holding the rest at ``template``, paced
    by ``period_ms``. Returns the exact payloads sent (capped list), so a reaction
    on the bus can be traced to the frame that caused it. Bounded and blocking; a
    deliberate action. ``rng`` is injectable for deterministic tests."""
    from ..can import Frame, get_channel
    rng = rng or random.Random()
    provider = get_channel(channel, fd=True if is_fd else None)
    if not getattr(provider, "available", False):
        return []
    base = [int(b) & 0xFF for b in (template or [])] or [0] * 8
    idx = [i for i in (fuzz_bytes or []) if 0 <= i < len(base)] or list(range(len(base)))
    count = max(1, min(int(count), 512))
    period = max(0.002, int(period_ms) / 1000.0)
    sent: list[dict] = []
    for _ in range(count):
        data = list(base)
        for i in idx:
            data[i] = rng.randrange(256)
        frame = Frame(arbitration_id=arbitration_id, data=data, is_fd=bool(is_fd),
                      is_extended_id=bool(is_extended_id))
        try:
            if provider.send(frame):
                sent.append({"data": data})
        except Exception as exc:
            log.info("fuzz CAN tx failed on %s: %s", channel, exc)
            break
        time.sleep(period)
    return sent


def replay(channel: str, frames: list[dict], *, speed: float = 1.0, backend: str = "socketcan",
           max_frames: int = 20000, max_seconds: float = 60.0) -> int:
    """Replay captured frames onto ``channel`` at their original relative timing
    (scaled by ``speed``), for reproducing a sequence while probing. Bounded by
    ``max_frames`` and ``max_seconds`` so a huge capture cannot run away. Returns
    the number of frames sent. Blocking; a deliberate action."""
    from ..can import Frame, get_channel
    ordered = sorted((f for f in frames if f.get("data") is not None),
                     key=lambda f: float(f.get("timestamp", 0.0)))[:max(1, int(max_frames))]
    if not ordered:
        return 0
    any_fd = any(f.get("is_fd") for f in ordered)
    provider = get_channel(channel, backend=backend, fd=True if any_fd else None)
    if not getattr(provider, "available", False):
        return 0
    speed = max(0.1, min(float(speed), 100.0))
    t0 = float(ordered[0].get("timestamp", 0.0))
    started = time.monotonic()
    sent = 0
    for f in ordered:
        target = (float(f.get("timestamp", 0.0)) - t0) / speed
        while True:
            elapsed = time.monotonic() - started
            if elapsed >= max_seconds:
                return sent
            wait = target - elapsed
            if wait <= 0:
                break
            time.sleep(min(wait, 0.25))
        frame = Frame(arbitration_id=int(f.get("arbitration_id") or 0), data=list(f.get("data") or []),
                      is_fd=bool(f.get("is_fd")), is_extended_id=bool(f.get("is_extended_id")))
        try:
            if provider.send(frame):
                sent += 1
        except Exception as exc:
            log.info("replay CAN tx failed on %s: %s", channel, exc)
            break
    return sent


def burst_async(channel: str, arbitration_id: int, data, **kwargs) -> None:
    """Fire-and-forget burst on a background thread, for a control press that
    must return immediately."""
    threading.Thread(target=lambda: burst(channel, arbitration_id, data, **kwargs),
                      name=f"can-burst-{_key(channel, arbitration_id)}", daemon=True).start()


def stop_all() -> None:
    with _lock:
        entries = list(_active.values())
        _active.clear()
    for entry in entries:
        entry["stop"].set()


def _loop(channel: str, arbitration_id: int, data, period_ms: int,
          is_fd: bool, is_extended_id: bool, stop_ev: threading.Event) -> None:
    from ..can import Frame, get_channel
    # A CAN-FD frame needs an fd=True socket; a classic socket rejects it and the
    # periodic send transmits nothing. Force fd for an FD frame and leave classic
    # frames on the channel's configured mode (fd=None does not override).
    provider = get_channel(channel, fd=True if is_fd else None)
    frame = Frame(arbitration_id=arbitration_id, data=data, is_fd=is_fd, is_extended_id=is_extended_id)
    interval = period_ms / 1000.0
    while not stop_ev.wait(interval):
        try:
            provider.send(frame)
        except Exception as exc:  # a bus that goes away should not kill the thread
            log.info("periodic CAN tx failed on %s: %s", channel, exc)
