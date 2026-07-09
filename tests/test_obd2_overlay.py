"""OBD2 overlay: decode a standard OBD-II mode-01 response frame generically,
and merge it on top of a database decode in the monitor path."""
from __future__ import annotations

from app.can import diagnostics, monitor


def test_decode_obd2_frame_speed():
    # 0x7E8 single frame: [len=3, 0x41 (mode1 resp), 0x0D (speed PID), value]
    assert diagnostics.decode_obd2_frame(0x7E8, [0x03, 0x41, 0x0D, 0x50, 0, 0, 0, 0]) == {"Vehicle speed": 0x50}


def test_decode_obd2_frame_rpm():
    out = diagnostics.decode_obd2_frame(0x7E8, [0x04, 0x41, 0x0C, 0x1A, 0xF8, 0, 0, 0])
    assert out == {"Engine RPM": ((0x1A * 256) + 0xF8) / 4.0}


def test_decode_obd2_frame_ignores_non_responses():
    assert diagnostics.decode_obd2_frame(0x123, [0x03, 0x41, 0x0D, 0x50]) == {}   # not an OBD2 id
    assert diagnostics.decode_obd2_frame(0x7E8, [0x10, 0x14, 0x41, 0x0D]) == {}    # multi-frame (first frame)
    assert diagnostics.decode_obd2_frame(0x7E8, [0x03, 0x7F, 0x01, 0x12]) == {}    # negative response
    assert diagnostics.decode_obd2_frame(0x7E9, []) == {}                          # empty


def test_decode_record_merges_overlay_over_none_and_dbc():
    rec = {"arbitration_id": 0x7E8, "data": [0x03, 0x41, 0x0D, 0x28]}
    assert monitor.decode_record(rec, None, obd2_overlay=True) == {"Vehicle speed": 0x28}
    # No overlay and no database -> nothing to decode.
    assert monitor.decode_record(rec, None, obd2_overlay=False) is None
