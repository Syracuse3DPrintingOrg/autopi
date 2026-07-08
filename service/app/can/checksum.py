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


def _gen_crc8_table(poly: int) -> list[int]:
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
        table.append(crc)
    return table


# SAE J1850 CRC-8 lookup (poly 0x1D), matching opendbc's CRC8J1850.
CRC8J1850 = _gen_crc8_table(0x1D)

# Per-address final XOR for the FCA Giorgio checksum (opendbc fca_giorgio_checksum):
# the three special addresses are the EPS messages (0xDE/0x106/0x122), all else 0x0A.
_GIORGIO_XOR = {0xDE: 0x10, 0x106: 0xF6, 0x122: 0xF1}


def fca_giorgio_checksum(address: int, data: bytes) -> int:
    """FCA Giorgio checksum (opendbc fca_giorgio_checksum), MIT.

    A J1850 CRC-8 over all bytes except the last (the checksum byte), then a
    final XOR that depends on the message's arbitration id. Alfa Romeo Giulia /
    Stelvio and Maserati Grecale (the Giorgio platform) use this.
    """
    crc = 0
    for i in range(len(data) - 1):
        crc ^= data[i]
        crc = CRC8J1850[crc]
    return crc ^ _GIORGIO_XOR.get(address, 0x0A)


def finalize(algorithm: str, data: list[int], address: int | None = None) -> list[int]:
    """Apply a checksum algorithm to a frame's bytes in place (returns it).

    The counter, if any, must already be set in ``data`` (encode does that from
    the COUNTER signal). This only recomputes the checksum byte. ``address`` is
    the message arbitration id, needed by algorithms whose result depends on it
    (fca_giorgio).
    """
    if not algorithm or not data:
        return data
    out = list(data)
    if algorithm == "chrysler":
        out[-1] = chrysler_checksum(bytes(out))
    elif algorithm == "fca_giorgio":
        out[-1] = fca_giorgio_checksum(int(address or 0), bytes(out))
    return out


SUPPORTED = ("chrysler", "fca_giorgio")
