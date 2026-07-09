"""Bit-overlay actuation: change only a control's bits on the live frame."""
from app.can.base import Frame
from app.can import overlay as ov
from app.actions.drivers.can import _parse_overlay, _parse_frame


class FakeProvider:
    """Minimal recv-only provider: hands back queued frames then None."""

    def __init__(self, frames):
        self._frames = list(frames)

    def recv(self, timeout=None):
        return self._frames.pop(0) if self._frames else None


def _cap(byte_values):
    """Captured frames of one id, varying only the target byte (index 0)."""
    return [{"data": [v, 0x14, 0x50], "is_fd": False} for v in byte_values]


def test_derive_mask_finds_the_toggled_bits():
    # Resting byte 0 is 0x11 (most common); a press flips bit 0 -> 0x10 vs 0x11.
    spec = ov.derive_mask(_cap([0x11, 0x11, 0x11, 0x10]), byte=0)
    assert spec["byte"] == 0
    assert spec["resting"] == 0x11
    assert spec["mask"] == (0x11 ^ 0x10)  # 0x01
    assert spec["active"] == (0x10 & spec["mask"])  # 0x00: the bit went low


def test_derive_mask_empty_is_zero():
    spec = ov.derive_mask([], byte=2)
    assert spec == {"byte": 2, "mask": 0, "active": 0, "resting": 0}


def test_overlay_byte_touches_only_masked_bits():
    # Live byte 0b1010_1010, set bit0 high via mask 0x01/active 0x01.
    assert ov.overlay_byte(0b10101010, mask=0x01, active_bits=0x01) == 0b10101011
    # A masked bit driven low clears it, everything else preserved.
    assert ov.overlay_byte(0b11111111, mask=0x01, active_bits=0x00) == 0b11111110


def test_apply_overlay_preserves_other_bytes():
    live = [0x11, 0x14, 0x50, 0x50, 0x52]
    out = ov.apply_overlay(live, byte=0, mask=0x01, active_bits=0x00)
    assert out == [0x10, 0x14, 0x50, 0x50, 0x52]  # only byte 0 changed
    assert live[0] == 0x11  # input not mutated


def test_apply_overlay_grows_short_frame():
    assert ov.apply_overlay([0x01], byte=3, mask=0x0F, active_bits=0x0A) == [0x01, 0, 0, 0x0A]


def test_read_latest_frame_returns_newest_match():
    frames = [Frame(0x100, [1]), Frame(0x123, [2]), Frame(0x123, [9])]
    got = ov.read_latest_frame(FakeProvider(frames), 0x123, window_s=0.05)
    assert got is not None and list(got.data) == [9]


def test_read_latest_frame_none_when_absent():
    got = ov.read_latest_frame(FakeProvider([Frame(0x100, [1])]), 0x123, window_s=0.02)
    assert got is None


def test_overlaid_data_uses_live_frame():
    live = FakeProvider([Frame(0x5C6, [0x11, 0x99, 0x99])])
    data, source = ov.overlaid_data(live, 0x5C6, byte=0, mask=0x01, active_bits=0x00,
                                    template=[0x00, 0x00, 0x00], window_s=0.05)
    assert source == "live"
    assert data == [0x10, 0x99, 0x99]  # live bytes kept, only bit 0 changed


def test_overlaid_data_falls_back_to_template():
    empty = FakeProvider([])  # id not on the bus
    data, source = ov.overlaid_data(empty, 0x5C6, byte=0, mask=0x01, active_bits=0x00,
                                    template=[0x11, 0x14, 0x50], window_s=0.02)
    assert source == "resting"
    assert data == [0x10, 0x14, 0x50]


def test_overlaid_data_no_provider_uses_template():
    data, source = ov.overlaid_data(None, 0x5C6, byte=1, mask=0xFF, active_bits=0xAB,
                                    template=[0x00, 0x00])
    assert source == "resting"
    assert data == [0x00, 0xAB]


def test_parse_overlay_reads_mask_from_action_params():
    spec = _parse_overlay({"overlay_byte": 0, "overlay_mask": 1, "overlay_value": 0})
    assert spec == {"byte": 0, "mask": 0x01, "active": 0x00}
    # Hex string form is accepted too.
    spec = _parse_overlay({"overlay_byte": 2, "overlay_mask": "0x0F", "overlay_value": "0x0A"})
    assert spec == {"byte": 2, "mask": 0x0F, "active": 0x0A}


def test_parse_overlay_none_for_legacy_action():
    assert _parse_overlay({}) is None
    assert _parse_overlay({"overlay_mask": "0"}) is None
    assert _parse_overlay({"overlay_mask": "0x00"}) is None


def test_parse_frame_carries_overlay_field():
    parsed = _parse_frame({"channel": "can0", "arbitration_id": "0x5C6", "data": "11 14 50",
                           "overlay_byte": 0, "overlay_mask": 1, "overlay_value": 0})
    assert parsed["overlay"] == {"byte": 0, "mask": 0x01, "active": 0x00}
    # A plain fixed-data action has no overlay.
    assert _parse_frame({"arbitration_id": "0x7DF", "data": "02 01 0C"})["overlay"] is None
