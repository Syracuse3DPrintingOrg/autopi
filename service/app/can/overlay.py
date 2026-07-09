"""Actuate a found control by changing only its bits on the live frame.

A control found by the Signal Finder is a field inside a shared message, not a
whole frame. Arbitration id 0x5C6 typically carries several signals at once (a
button, a message counter, a rolling checksum), and the ECU broadcasts it every
cycle. Replaying the entire captured frame therefore clobbers the other signals
in that message, races the real sender, and ships a stale counter and checksum
that a gateway drops on the next cycle. That is why a verbatim replay usually
does nothing.

The right unit of work is the field: read the current frame for that id off the
bus, change only the bits the control owns, and leave every other byte at its
live value. The bit math here is pure and unit tested; the live read takes an
injected provider so it is testable without hardware.

Rolling-counter and CRC recompute (needed on buses that checksum) is the next
layer and is tracked separately; overlay-on-live is the foundation it builds on,
and it already works on buses that do not checksum.
"""
from __future__ import annotations

import time
from collections import Counter
from typing import Any


def derive_mask(frames: list[dict], byte: int) -> dict:
    """Work out which bits of ``byte`` a control toggles, from captured frames.

    ``resting`` is the most common value of that byte (the control at rest);
    ``active`` is the captured value furthest from resting (the pressed state);
    ``mask`` is the set of bits that differ between them. Pure.
    """
    vals: list[int] = []
    for f in frames:
        data = f.get("data") or []
        vals.append(int(data[byte]) if 0 <= byte < len(data) else 0)
    if not vals:
        return {"byte": byte, "mask": 0, "active": 0, "resting": 0}
    resting = Counter(vals).most_common(1)[0][0]
    active = max(vals, key=lambda v: abs(v - resting))
    mask = (resting ^ active) & 0xFF
    return {"byte": byte, "mask": mask, "active": active & mask, "resting": resting}


def overlay_byte(live_byte: int, mask: int, active_bits: int) -> int:
    """Set only the masked bits of ``live_byte`` to their active state."""
    mask = int(mask) & 0xFF
    return (int(live_byte) & (~mask & 0xFF)) | (int(active_bits) & mask)


def apply_overlay(base_data, byte: int, mask: int, active_bits: int) -> list[int]:
    """Return a copy of ``base_data`` with the control bits set on ``byte``.

    Grows the frame with zero bytes if it is shorter than the target byte, so a
    resting template that happens to be short still produces a valid overlay.
    """
    data = [int(b) & 0xFF for b in (base_data or [])]
    while len(data) <= byte:
        data.append(0)
    data[byte] = overlay_byte(data[byte], mask, active_bits)
    return data


def read_latest_frame(provider, arbitration_id: int, window_s: float = 0.15):
    """Most recent frame seen for ``arbitration_id`` within ``window_s``.

    Returns a :class:`~app.can.base.Frame` or ``None`` when the id is not on the
    bus in that window. ``provider`` only needs a ``recv(timeout)`` method, so a
    fake provider can drive this in tests.
    """
    latest = None
    deadline = time.monotonic() + max(0.0, float(window_s))
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            frame = provider.recv(timeout=min(0.05, remaining))
        except Exception:
            break
        if frame is not None and getattr(frame, "arbitration_id", None) == arbitration_id:
            latest = frame
    return latest


def overlaid_data(provider, arbitration_id: int, byte: int, mask: int,
                  active_bits: int, *, template, window_s: float = 0.15) -> tuple[list[int], str]:
    """Read the live frame for ``arbitration_id`` and overlay the control bits.

    Falls back to ``template`` (the resting/captured bytes) when the id is not
    currently on the bus, so a control still actuates on a quiet bus. Returns
    ``(data, source)`` where source is ``"live"`` or ``"resting"``.
    """
    live = None
    if provider is not None:
        live = read_latest_frame(provider, arbitration_id, window_s=window_s)
    if live is not None:
        return apply_overlay(list(live.data), byte, mask, active_bits), "live"
    return apply_overlay(list(template or []), byte, mask, active_bits), "resting"
