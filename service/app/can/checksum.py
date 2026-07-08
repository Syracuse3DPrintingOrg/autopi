"""Message counter and checksum finalizers for CAN frames.

Many OEMs protect messages with a rolling counter and a checksum that the
receiving module validates, so a frame with a wrong (or zero) checksum is
ignored. To send a message a real cluster or ECU will accept, the counter must
increment each transmit and the checksum must be recomputed over the frame.

Currently supported, all reproduced exactly from comma.ai's opendbc (MIT):
Chrysler/Stellantis CUSW, FCA Giorgio, Toyota, Honda, and Hyundai/Kia CAN FD.
Chrysler, Giorgio, and Toyota write a whole checksum byte (the last byte of
the frame); Honda's checksum is a 4-bit nibble sharing a byte with its
counter, and Hyundai CAN FD's is a 16-bit CRC in the first two bytes, so those
two are applied by name through the DBC's own ``CHECKSUM`` signal rather than
by splicing a byte position (see ``compute()`` and how ``dbc.encode()`` uses
it). New algorithms register here by name.
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


def toyota_checksum(address: int, data: bytes) -> int:
    """Toyota checksum (opendbc toyota_checksum), MIT.

    A plain byte sum of the frame length, the arbitration id's bytes, and all
    data bytes except the last (the checksum byte), truncated to 8 bits.
    """
    s = len(data)
    addr = address
    while addr:
        s += addr & 0xFF
        addr >>= 8
    for i in range(len(data) - 1):
        s += data[i]
    return s & 0xFF


def honda_checksum(address: int, data: bytes) -> int:
    """Honda checksum (opendbc honda_checksum), MIT.

    A 4-bit nibble sum of the arbitration id and every nibble of the frame
    (the last byte contributes only its high nibble, since the low nibble
    holds the counter/checksum itself), two's-complemented to 4 bits. Extended
    (29-bit) ids add a fixed +3.
    """
    s = 0
    extended = address > 0x7FF
    addr = address
    while addr:
        s += addr & 0xF
        addr >>= 4
    for i in range(len(data)):
        x = data[i]
        if i == len(data) - 1:
            x >>= 4
        s += (x & 0xF) + (x >> 4)
    s = 8 - s
    if extended:
        s += 3
    return s & 0xF


def _gen_crc16_table(poly: int) -> list[int]:
    table = []
    for i in range(256):
        crc = i << 8
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
        table.append(crc)
    return table


# CRC-16/XMODEM lookup (poly 0x1021), matching opendbc's CRC16_XMODEM.
CRC16_XMODEM = _gen_crc16_table(0x1021)

# Hyundai/Kia CAN FD final XOR, keyed by frame length in bytes (opendbc
# hkg_can_fd_checksum); other lengths are not covered by any real message.
_HKG_CANFD_XOR = {8: 0x5F29, 16: 0x041D, 24: 0x819D, 32: 0x9F5B}


def hyundai_canfd_checksum(address: int, data: bytes) -> int:
    """Hyundai/Kia CAN FD checksum (opendbc hkg_can_fd_checksum), MIT.

    A CRC-16/XMODEM over the data bytes from index 2 on (skipping the 16-bit
    checksum field itself, which sits in bytes 0-1), then the two arbitration
    id bytes fed through the same CRC, then a final XOR keyed by frame length.
    Used by the Hyundai/Kia/Genesis CAN FD platform (2021+ models with the
    newer 32/24/16-byte CAN FD messages).
    """
    crc = 0
    for i in range(2, len(data)):
        crc = ((crc << 8) ^ CRC16_XMODEM[(crc >> 8) ^ data[i]]) & 0xFFFF
    crc = ((crc << 8) ^ CRC16_XMODEM[(crc >> 8) ^ (address & 0xFF)]) & 0xFFFF
    crc = ((crc << 8) ^ CRC16_XMODEM[(crc >> 8) ^ ((address >> 8) & 0xFF)]) & 0xFFFF
    return crc ^ _HKG_CANFD_XOR.get(len(data), 0)


def finalize(algorithm: str, data: list[int], address: int | None = None) -> list[int]:
    """Apply a whole-byte checksum algorithm to a frame's bytes (returns it).

    The counter, if any, must already be set in ``data`` (encode does that from
    the COUNTER signal). This only recomputes the checksum byte. ``address`` is
    the message arbitration id, needed by algorithms whose result depends on it
    (fca_giorgio, toyota). Only for algorithms whose checksum occupies the
    entire last byte; ``honda`` and ``hyundai_canfd`` do not (see ``compute()``
    and ``SIGNAL_ORIENTED``) and are ignored here.
    """
    if not algorithm or not data:
        return data
    out = list(data)
    if algorithm == "chrysler":
        out[-1] = chrysler_checksum(bytes(out))
    elif algorithm == "fca_giorgio":
        out[-1] = fca_giorgio_checksum(int(address or 0), bytes(out))
    elif algorithm == "toyota":
        out[-1] = toyota_checksum(int(address or 0), bytes(out))
    return out


def compute(algorithm: str, address: int, data: list[int]) -> int:
    """Compute a signal-oriented checksum's raw value (not embedded in bytes).

    Used for algorithms whose checksum signal is not a whole trailing byte
    (Honda's 4-bit nibble, Hyundai CAN FD's 16-bit little-endian field);
    the caller re-encodes the DBC's own ``CHECKSUM`` signal with this value so
    cantools places it at the correct bit position.
    """
    if algorithm == "honda":
        return honda_checksum(address, bytes(data))
    if algorithm == "hyundai_canfd":
        return hyundai_canfd_checksum(address, bytes(data))
    return 0


# Algorithms applied via `finalize()` (they own the whole last byte).
BYTE_ORIENTED = ("chrysler", "fca_giorgio", "toyota")
# Algorithms applied via `compute()` + a named CHECKSUM signal re-encode.
SIGNAL_ORIENTED = ("honda", "hyundai_canfd")

SUPPORTED = BYTE_ORIENTED + SIGNAL_ORIENTED
