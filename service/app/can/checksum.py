"""Message counter and checksum finalizers for CAN frames.

Many OEMs protect messages with a rolling counter and a checksum that the
receiving module validates, so a frame with a wrong (or zero) checksum is
ignored. To send a message a real cluster or ECU will accept, the counter must
increment each transmit and the checksum must be recomputed over the frame.

Currently supported: the Chrysler/Stellantis CUSW checksum (from comma.ai's
opendbc, MIT). The algorithm is reproduced exactly; it computes the value for
the last byte of the frame over the preceding bytes. New algorithms register
here by name.
"""
from __future__ import annotations

import threading

# Per-key rolling counters (key is usually a message id or a sim entry id).
_counters: dict[str, int] = {}
_lock = threading.Lock()


def next_counter(key: str, modulo: int = 16) -> int:
    """Return the next rolling counter value for a key (0..modulo-1)."""
    with _lock:
        value = _counters.get(key, -1)
        value = (value + 1) % modulo
        _counters[key] = value
        return value


def chrysler_checksum(data: bytes) -> int:
    """Chrysler/Stellantis CUSW checksum (opendbc chrysler_checksum), MIT.

    Computes the checksum byte over all bytes of ``data`` except the last one
    (the checksum byte position). Returns the value to place in that last byte.
    """
    checksum = 0xFF
    for j in range(len(data) - 1):
        curr = data[j]
        shift = 0x80
        for _ in range(8):
            bit_sum = curr & shift
            temp_chk = checksum & 0x80
            if bit_sum:
                bit_sum = 0x1C
                if temp_chk:
                    bit_sum = 1
                checksum = (checksum << 1) & 0xFF
                temp_chk = checksum | 1
                bit_sum ^= temp_chk
            else:
                if temp_chk:
                    bit_sum = 0x1D
                checksum = (checksum << 1) & 0xFF
                bit_sum ^= checksum
            checksum = bit_sum & 0xFF
            shift >>= 1
    return (~checksum) & 0xFF


def finalize(algorithm: str, data: list[int]) -> list[int]:
    """Apply a checksum algorithm to a frame's bytes in place (returns it).

    The counter, if any, must already be set in ``data`` (encode does that from
    the COUNTER signal). This only recomputes the checksum byte.
    """
    if not algorithm or not data:
        return data
    out = list(data)
    if algorithm == "chrysler":
        out[-1] = chrysler_checksum(bytes(out))
    return out


SUPPORTED = ("chrysler",)
