"""Chrysler counter/checksum finalization for CAN frames."""
import random

import pytest

from app.can import checksum as ck
from app.can import dbc as dbc_mod


def _reference(d):
    # opendbc chrysler_checksum, reproduced independently for a known-answer test.
    checksum = 0xFF
    for j in range(len(d) - 1):
        curr = d[j]; shift = 0x80
        for _ in range(8):
            bit_sum = curr & shift; temp_chk = checksum & 0x80
            if bit_sum:
                bit_sum = 0x1C
                if temp_chk: bit_sum = 1
                checksum = (checksum << 1) & 0xFF; temp_chk = checksum | 1; bit_sum ^= temp_chk
            else:
                if temp_chk: bit_sum = 0x1D
                checksum = (checksum << 1) & 0xFF; bit_sum ^= checksum
            checksum = bit_sum & 0xFF; shift >>= 1
    return (~checksum) & 0xFF


def test_chrysler_checksum_matches_opendbc_reference():
    for _ in range(500):
        b = bytes(random.randrange(256) for _ in range(8))
        assert ck.chrysler_checksum(b) == _reference(b)


def test_counter_rolls_0_to_15():
    seq = [ck.next_counter("t") for _ in range(17)]
    assert seq[:3] == [0, 1, 2]
    assert seq[15] == 15 and seq[16] == 0


def test_finalize_sets_last_byte_to_chrysler_checksum():
    data = [0x12, 0x34, 0x00]
    out = ck.finalize("chrysler", data)
    assert out[-1] == ck.chrysler_checksum(bytes(data))
    assert out[:-1] == data[:-1]


def test_finalize_noop_without_algorithm():
    assert ck.finalize("", [1, 2, 3]) == [1, 2, 3]


DBC = '''VERSION ""
BU_: PI
BO_ 496 CLUSTER_1: 8 PI
 SG_ SPEEDOMETER : 19|12@0+ (0.01065,0) [0|1] "m/s" PI
 SG_ COUNTER : 51|4@0+ (1,0) [0|1] "" PI
 SG_ CHECKSUM : 63|8@0+ (1,0) [0|1] "" PI
'''


@pytest.mark.skipif(not dbc_mod.available(), reason="cantools not installed")
def test_encode_applies_counter_and_checksum():
    # Encoding with a counter and chrysler checksum sets the counter nibble and
    # a valid checksum byte (nonzero, and consistent with the algorithm).
    data = dbc_mod.encode(DBC, "CLUSTER_1", {"SPEEDOMETER": 16.0}, counter=7, checksum="chrysler")
    assert data[-1] == ck.chrysler_checksum(bytes(data))
    # A different counter changes the frame (and thus the checksum).
    other = dbc_mod.encode(DBC, "CLUSTER_1", {"SPEEDOMETER": 16.0}, counter=8, checksum="chrysler")
    assert other != data
