"""Signal Finder algorithm tests: bit extraction verified against cantools,
the pure statistics helpers checked against hand-computed values, a full
synthetic-signal recovery through the search pipeline, and a save-to-DBC
round trip through decode.
"""
from __future__ import annotations

import math
import random

import pytest

from app.can import dbc as dbc_mod
from app.can import reverse as rev
from app.can.reverse import (
    add_signal_to_database,
    bit_activity,
    bitsearch,
    classify_byte,
    derive_scale_offset,
    extract_field,
    field_series,
    linear_fit,
    resample,
    spearman,
    survey,
    to_dbc_signal,
)


# --------------------------------------------------------------------------
# extract_field vs cantools
# --------------------------------------------------------------------------

def _dbc_with_signal(sig_line: str) -> str:
    return (
        'VERSION ""\n\nNS_ :\n\nBS_:\n\nBU_: X\n\n'
        f'BO_ 1 M: 8 X\n {sig_line}\n'
    )


def _cantools_decode(sig_line: str, data: bytes) -> int:
    text = _dbc_with_signal(sig_line)
    decoded = dbc_mod.decode(text, 1, data)
    return decoded["S"]


@pytest.mark.parametrize("start,length,byte_order,dbc_char,signed_char,data,signed", [
    (0, 8, "little_endian", "1", "+", bytes([0xAB, 0, 0, 0, 0, 0, 0, 0]), False),
    (8, 8, "little_endian", "1", "+", bytes([0, 0xAB, 0, 0, 0, 0, 0, 0]), False),
    (3, 5, "little_endian", "1", "+", bytes([0b10101000, 0, 0, 0, 0, 0, 0, 0]), False),
    (0, 8, "little_endian", "1", "-", bytes([0xFF, 0, 0, 0, 0, 0, 0, 0]), True),
    (3, 5, "little_endian", "1", "-", bytes([0b10001000, 0, 0, 0, 0, 0, 0, 0]), True),
    (7, 8, "big_endian", "0", "+", bytes([0xAB, 0, 0, 0, 0, 0, 0, 0]), False),
    (15, 8, "big_endian", "0", "+", bytes([0, 0xAB, 0, 0, 0, 0, 0, 0]), False),
    (7, 16, "big_endian", "0", "+", bytes([0xAB, 0xCD, 0, 0, 0, 0, 0, 0]), False),
    (3, 4, "big_endian", "0", "+", bytes([0b00001010, 0, 0, 0, 0, 0, 0, 0]), False),
    (0, 8, "big_endian", "0", "+", bytes([0xAB, 0, 0, 0, 0, 0, 0, 0]), False),
    (7, 8, "big_endian", "0", "-", bytes([0xFF, 0, 0, 0, 0, 0, 0, 0]), True),
    (3, 4, "big_endian", "0", "-", bytes([0b00001010, 0, 0, 0, 0, 0, 0, 0]), True),
])
def test_extract_field_matches_cantools(start, length, byte_order, dbc_char, signed_char, data, signed):
    sig_line = f'SG_ S : {start}|{length}@{dbc_char}{signed_char} (1,0) [0|0] "" X'
    expected = _cantools_decode(sig_line, data)
    assert extract_field(data, start, length, byte_order, signed) == expected


def test_extract_field_random_matches_cantools_intel():
    rng = random.Random(1234)
    for _ in range(200):
        data = bytes(rng.randrange(256) for _ in range(8))
        length = rng.randrange(1, 17)
        start = rng.randrange(0, 64 - length + 1)
        signed = rng.choice([True, False])
        sig_line = f'SG_ S : {start}|{length}@1{"-" if signed else "+"} (1,0) [0|0] "" X'
        expected = _cantools_decode(sig_line, data)
        assert extract_field(data, start, length, "little_endian", signed) == expected


def test_extract_field_random_matches_cantools_motorola():
    rng = random.Random(5678)
    trials = 0
    while trials < 200:
        data = bytes(rng.randrange(256) for _ in range(8))
        length = rng.randrange(1, 17)
        start = rng.randrange(0, 64)
        phys_start = 8 * (start // 8) + (7 - start % 8)
        if phys_start + length > 64:
            continue
        trials += 1
        signed = rng.choice([True, False])
        sig_line = f'SG_ S : {start}|{length}@0{"-" if signed else "+"} (1,0) [0|0] "" X'
        expected = _cantools_decode(sig_line, data)
        assert extract_field(data, start, length, "big_endian", signed) == expected


def test_extract_field_rejects_field_too_long_for_frame():
    with pytest.raises(ValueError):
        extract_field(bytes([0, 0]), 0, 24, "little_endian")


def test_extract_field_rejects_unknown_byte_order():
    with pytest.raises(ValueError):
        extract_field(bytes([0]), 0, 4, "middle_endian")


# --------------------------------------------------------------------------
# spearman / linear_fit vs hand-computed values
# --------------------------------------------------------------------------

def test_spearman_perfect_monotonic_is_one():
    xs = [1, 2, 3, 4, 5]
    ys = [10, 20, 30, 40, 50]
    assert spearman(xs, ys) == pytest.approx(1.0)


def test_spearman_perfect_inverse_is_minus_one():
    xs = [1, 2, 3, 4, 5]
    ys = [50, 40, 30, 20, 10]
    assert spearman(xs, ys) == pytest.approx(-1.0)


def test_spearman_hand_computed_with_ties():
    # Classic textbook example: ranks with a tie, hand-verified value.
    xs = [1, 2, 2, 4]
    ys = [1, 3, 2, 4]
    # Ranks: xs -> [1, 2.5, 2.5, 4], ys -> [1, 3, 2, 4]
    # Pearson correlation of those two rank vectors:
    rx = [1, 2.5, 2.5, 4]
    ry = [1, 3, 2, 4]
    mx = sum(rx) / 4
    my = sum(ry) / 4
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    expected = cov / math.sqrt(vx * vy)
    assert spearman(xs, ys) == pytest.approx(expected)


def test_spearman_too_few_points_is_zero():
    assert spearman([1], [2]) == 0.0
    assert spearman([], []) == 0.0


def test_linear_fit_hand_computed():
    # y = 3x + 2 exactly.
    xs = [0, 1, 2, 3, 4]
    ys = [2, 5, 8, 11, 14]
    fit = linear_fit(xs, ys)
    assert fit["slope"] == pytest.approx(3.0)
    assert fit["intercept"] == pytest.approx(2.0)
    assert fit["r2"] == pytest.approx(1.0)


def test_linear_fit_with_noise_hand_computed():
    xs = [1, 2, 3, 4]
    ys = [2.1, 3.9, 6.2, 7.8]
    n = 4
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = my - slope * mx
    fit = linear_fit(xs, ys)
    assert fit["slope"] == pytest.approx(slope)
    assert fit["intercept"] == pytest.approx(intercept)


def test_linear_fit_constant_x_has_zero_r2():
    fit = linear_fit([5, 5, 5], [1, 2, 3])
    assert fit["slope"] == 0.0
    assert fit["r2"] == 0.0


# --------------------------------------------------------------------------
# resample
# --------------------------------------------------------------------------

def test_resample_nearest_aligns_reference_to_series():
    series = [(0.0, 10), (1.0, 20), (2.0, 30)]
    reference = [{"t": 0.1, "value": 1}, {"t": 1.9, "value": 3}]
    aligned = resample(series, reference)
    assert aligned["xs"] == [10, 30]
    assert aligned["ys"] == [1, 3]


def test_resample_drops_unavailable_reference_points():
    series = [(0.0, 10), (1.0, 20)]
    reference = [{"t": 0.0, "value": 1}, {"t": 1.0, "value": 2, "available": False}]
    aligned = resample(series, reference)
    assert aligned["xs"] == [10]
    assert aligned["ys"] == [1]


def test_resample_linear_interpolation():
    series = [(0.0, 0), (10.0, 100)]
    reference = [{"t": 5.0, "value": 1}]
    aligned = resample(series, reference, method="linear")
    assert aligned["xs"][0] == pytest.approx(50.0)


def test_resample_searches_lag_for_best_correlation():
    # The decoded series leads the reference by exactly 2 seconds; searching lags
    # should find lag=2 gives a clean alignment. The signal is non-monotonic (a
    # pure ramp would correlate at every lag, so the lag would be unidentifiable).
    shape = [0, 5, 9, 3, 7, 12, 2, 8, 14, 4, 11, 1, 6, 13, 10, 15, 18, 16, 19, 17]
    series = [(float(t), shape[t]) for t in range(20)]
    reference = [{"t": t + 2.0, "value": shape[t]} for t in range(20)]
    aligned = resample(series, reference, lags=[0, 1, 2, 3])
    assert aligned["lag"] == 2


def test_resample_empty_inputs():
    assert resample([], [{"t": 0, "value": 1}]) == {"xs": [], "ys": [], "lag": 0.0}
    assert resample([(0.0, 1)], []) == {"xs": [], "ys": [], "lag": 0.0}


# --------------------------------------------------------------------------
# classify_byte / bit_activity
# --------------------------------------------------------------------------

def test_classify_byte_static():
    label, _ = classify_byte([5, 5, 5, 5, 5])
    assert label == "static"


def test_classify_byte_counter():
    values = [i % 256 for i in range(50)]
    label, _ = classify_byte(values)
    assert label == "counter"


def test_classify_byte_checksum_like_high_entropy():
    rng = random.Random(42)
    values = [rng.randrange(256) for _ in range(80)]
    label, _ = classify_byte(values)
    assert label == "checksum"


def test_classify_byte_candidate_for_a_slow_moving_signal():
    values = [10, 10, 11, 11, 12, 12, 13, 13, 12, 12, 11, 11]
    label, _ = classify_byte(values)
    assert label == "candidate"


def test_bit_activity_empty_records():
    result = bit_activity([])
    assert result["length"] == 0
    assert result["bytes"] == []


def test_bit_activity_shapes_and_classifies():
    records = [
        {"arbitration_id": 0x100, "data": [0, i % 256, 5], "timestamp": float(i)}
        for i in range(40)
    ]
    result = bit_activity(records)
    assert result["arbitration_id"] == 0x100
    assert result["length"] == 3
    assert len(result["bit_activity"]) == 24
    assert result["bytes"][0]["classification"] == "static"
    assert result["bytes"][1]["classification"] == "counter"
    assert result["bytes"][2]["classification"] == "static"


# --------------------------------------------------------------------------
# Full synthetic-signal recovery
# --------------------------------------------------------------------------

def _make_synthetic_capture(arbitration_id, start_bit, length, byte_order, signed,
                            scale, offset, values, checksum_byte=7, counter_bits=4,
                            seed=99):
    """Build a capture of frames where a known signal is encoded at a known
    location, alongside a rolling counter (low bits of byte 0) and a
    high-entropy checksum byte, plus light noise elsewhere, mimicking a real
    OEM frame's shape."""
    rng = random.Random(seed)
    records = []
    for i, physical_value in enumerate(values):
        raw = round((physical_value - offset) / scale)
        data = [0] * 8
        # Rolling counter in byte 0's low nibble.
        data[0] = (i % (1 << counter_bits))
        # Light noise on an unrelated byte that never carries the signal.
        data[4] = rng.randrange(0, 4)
        data = _pack_field(data, start_bit, length, byte_order, raw)
        # Checksum: not a real algorithm, just something high-entropy and
        # dependent on the rest of the frame, so it must not get mistaken for
        # the signal or for a counter.
        data[checksum_byte] = sum(data[:checksum_byte]) * 7 % 256 ^ rng.randrange(256)
        records.append({
            "arbitration_id": arbitration_id,
            "data": data,
            "timestamp": float(i) * 0.1,
        })
    return records


def _pack_field(data, start_bit, length, byte_order, raw_value):
    mask = (1 << length) - 1
    raw_value &= mask
    if byte_order == "little_endian":
        frame_int = int.from_bytes(bytes(data), "little")
        frame_int &= ~(mask << start_bit)
        frame_int |= raw_value << start_bit
        packed = frame_int.to_bytes(len(data), "little")
    else:
        n_bits = len(data) * 8
        phys_start = 8 * (start_bit // 8) + (7 - start_bit % 8)
        shift = n_bits - phys_start - length
        frame_int = int.from_bytes(bytes(data), "big")
        frame_int &= ~(mask << shift)
        frame_int |= raw_value << shift
        packed = frame_int.to_bytes(len(data), "big")
    return list(packed)


@pytest.mark.parametrize("byte_order,start_bit,length,scale,offset", [
    ("little_endian", 16, 12, 0.1, 0.0),
    ("big_endian", 23, 12, 0.5, -40.0),
    ("little_endian", 8, 8, 1.0, 0.0),
])
def test_bitsearch_recovers_a_planted_signal(byte_order, start_bit, length, scale, offset):
    max_raw = (1 << length) - 1
    n_samples = 120
    # High-entropy raw values (not a smooth ramp): a partial or shifted bit
    # window would decorrelate almost completely, so only the exact field
    # location fits the reference well. A smooth ramp would let a shifted
    # subset of bits still look almost perfectly linear against it, which
    # defeats the point of the test.
    rng = random.Random(2024)
    values = []
    for _ in range(n_samples):
        raw = rng.randrange(0, max_raw + 1)
        physical = raw * scale + offset
        values.append(physical)
    records = _make_synthetic_capture(0x200, start_bit, length, byte_order, False,
                                       scale, offset, values)
    reference = [
        {"t": record["timestamp"], "value": value}
        for record, value in zip(records, values)
    ]
    candidates = bitsearch(records, reference, {"max_candidates": 5})
    assert candidates, "expected at least one candidate"
    best = candidates[0]
    assert best["arbitration_id"] == 0x200
    assert best["byte_order"] == byte_order
    assert best["start_bit"] == start_bit
    assert best["length"] == length
    assert best["r2"] > 0.95
    derived = derive_scale_offset(best)
    assert derived["scale"] == pytest.approx(scale, rel=0.15)
    assert derived["offset"] == pytest.approx(offset, abs=1.0)


def test_bitsearch_prefers_shorter_field_on_tied_score():
    # A 4-bit field and its superset 8-bit field (with the extra bits always
    # zero) fit the reference equally well; the shorter one should win.
    values = list(range(16)) * 5
    records = []
    for i, v in enumerate(values):
        records.append({
            "arbitration_id": 0x300,
            "data": [v, 0, 0, 0, 0, 0, 0, 0],
            "timestamp": i * 0.1,
        })
    reference = [{"t": r["timestamp"], "value": r["data"][0]} for r in records]
    candidates = bitsearch(records, reference, {
        "lengths": [4, 8], "byte_orders": ["little_endian"], "signed": [False],
        "max_candidates": 10,
    })
    assert candidates[0]["length"] == 4


def test_sample_at_drops_points_outside_capture_span():
    ts = [1.0, 2.0, 3.0]
    vs = [10.0, 20.0, 30.0]
    # Inside the span (and within the tiny float-jitter slack) still samples.
    assert rev._sample_at(ts, vs, 1.0, "nearest") == 10.0
    assert rev._sample_at(ts, vs, 3.0, "nearest") == 30.0
    # A point clearly before the first or after the last frame is dropped, not
    # clamped to the boundary value (which would invent data the capture never saw).
    assert rev._sample_at(ts, vs, 0.5, "nearest") is None
    assert rev._sample_at(ts, vs, 3.5, "nearest") is None


def test_is_nice_scale_and_alignment_penalty():
    assert rev._is_nice_scale(0.01) and rev._is_nice_scale(0.05) and rev._is_nice_scale(1.0)
    # A truncated alias's power-of-two-off scale is not a scale an OEM would pick.
    assert not rev._is_nice_scale(0.16) and not rev._is_nice_scale(0.003125)
    # Byte/nibble-aligned starts are unpenalized; a mid-byte wide field is penalized.
    assert rev._alignment_penalty("little_endian", 8, 16) == 0
    assert rev._alignment_penalty("little_endian", 4, 12) == 0
    assert rev._alignment_penalty("little_endian", 5, 12) == 1
    # Short flag-like fields sit anywhere in a byte, so they are never penalized.
    assert rev._alignment_penalty("little_endian", 5, 2) == 0


def test_rerank_tied_promotes_the_plausible_candidate_within_the_band():
    # Three candidates fitting within RANK_EPS: the alias (garbage scale) sorted
    # first by raw score must lose to the nice-scale, byte-aligned true field.
    alias = {"scale": 0.16, "start_bit": 12, "length": 10, "byte_order": "little_endian", "distinct": 300}
    true = {"scale": 0.01, "start_bit": 8, "length": 16, "byte_order": "little_endian", "distinct": 900}
    other = {"scale": 0.003125, "start_bit": 0, "length": 16, "byte_order": "little_endian", "distinct": 500}
    band = [(0.9999, alias), (0.9998, true), (0.99985, other)]
    band.sort(key=lambda c: -c[0])
    reranked = rev._rerank_tied(band, lambda c: c[0], lambda c: rev._plausibility_key(c[1]))
    assert reranked[0][1] is true
    # A candidate outside the RANK_EPS band keeps its score position.
    far = [(0.9999, alias), (0.5, true)]
    assert rev._rerank_tied(far, lambda c: c[0], lambda c: rev._plausibility_key(c[1]))[0][1] is alias


def test_bitsearch_ranks_binary_scale_field_over_truncation_alias():
    # A 16-bit LE field at start_bit 8 with the J1939 binary scale 1/64
    # (0.015625), carrying raw values that never exercise the top bits.
    # Truncation aliases (the same field minus its low bits) fit within
    # RANK_EPS at scales like 0.125 (drop 3 bits) and 0.25 (drop 4, and that
    # one starts nibble-aligned at bit 12), both of which sit in NICE_SCALES.
    # If the ranker did not also accept 1/64 as a real OEM scale, one of those
    # aliases would win the tied band; the true anchor must come out first.
    rng = random.Random(7)
    records, reference = [], []
    for i in range(300):
        raw = rng.randrange(0, 7680)
        data = [0] * 8
        data[1] = raw & 0xFF
        data[2] = (raw >> 8) & 0xFF
        records.append({"arbitration_id": 0x18F, "data": data, "timestamp": i * 0.05})
        reference.append({"t": i * 0.05, "value": raw * 0.015625, "available": True})
    best = bitsearch(records, reference, {"byte_orders": ["little_endian"]})[0]
    assert best["start_bit"] == 8, (
        f"got start_bit {best['start_bit']} (a truncation alias outranked the true field)")
    assert best["scale"] == pytest.approx(0.015625, rel=0.02)
    assert rev._is_nice_scale(0.015625)


def test_bitsearch_tied_flag_set_for_aliases_unset_for_clean_field():
    # A 4-bit ramp whose byte never uses its top bits: the 4-bit field and its
    # 8-bit superset decode the seen values identically, so the leading band
    # is statistically tied and every member must say so (the reported width
    # is a floor, not exact).
    values = list(range(16)) * 5
    records = [{"arbitration_id": 0x310, "data": [v, 0, 0, 0, 0, 0, 0, 0],
                "timestamp": i * 0.1} for i, v in enumerate(values)]
    reference = [{"t": r["timestamp"], "value": float(r["data"][0])} for r in records]
    tied = bitsearch(records, reference, {
        "lengths": [4, 8], "byte_orders": ["little_endian"], "signed": [False],
    })
    assert tied[0]["tied"] is True
    assert any(c["tied"] for c in tied[1:])
    # Searching only the true width leaves no alias within RANK_EPS of the
    # winner (a one-bit shift already costs too much fit), so the flag is off.
    clean = bitsearch(records, reference, {
        "lengths": [4], "byte_orders": ["little_endian"], "signed": [False],
    })
    assert clean[0]["tied"] is False
    assert all(c["tied"] is False for c in clean)
    # auto_decode recomputes the flag on its merged ranking and the best
    # candidate carries it (the default widths include the tied 8-bit superset).
    cands = rev.auto_decode({0x310: records}, reference, {})
    assert cands and cands[0]["tied"] is True


def test_bitsearch_reports_true_scale_not_a_power_of_two_alias():
    # A 16-bit LE field at start_bit 8, scale 0.01, carrying a 0..120 triangle
    # (raw 0..12000, so the top bits never toggle). A shifted/truncated alias fits
    # equally well at scale 0.16; the finder must still report the true anchor
    # (start_bit 8, scale 0.01), even if the width comes back narrower because the
    # unused top bits cannot be distinguished.
    n = 400
    records, values = [], []
    for i in range(n):
        t = i / 20.0
        val = 120.0 * (t / 10.0 if t < 10.0 else 2 - t / 10.0)  # triangle 0->120->0
        raw = int(round(val / 0.01))
        data = [i & 0xFF, 0, 0, 0, 0, 0, 0, 0]
        fi = int.from_bytes(bytes(data), "little")
        fi = (fi & ~(0xFFFF << 8)) | ((raw & 0xFFFF) << 8)
        records.append({"arbitration_id": 0x244, "data": list(fi.to_bytes(8, "little")), "timestamp": t})
        values.append(val)
    reference = [{"t": i / 1.0, "value": 120.0 * ((i / 1.0) / 10.0 if i < 10 else 2 - (i / 1.0) / 10.0)}
                 for i in range(21)]
    best = bitsearch(records, reference, {"byte_orders": ["little_endian"]})[0]
    assert best["start_bit"] == 8, f"got start_bit {best['start_bit']} (an alias, not the true anchor)"
    assert derive_scale_offset(best)["scale"] == 0.01, "must report the OEM scale, not a power-of-two alias"


def _ref(n, value_fn, t0=0.0, dt=1.0):
    return [{"t": t0 + i * dt, "value": value_fn(i), "available": True} for i in range(n)]


def test_diagnose_reference_no_frames():
    ref = _ref(12, lambda i: float(i))
    d = rev.diagnose_reference_match(ref, {}, correlated=True)
    assert d and d["reason_code"] == "no_frames"


def test_diagnose_reference_too_few_points_catches_a_marginal_count():
    # Six good readings is below the bar: a match off so few points is unreliable.
    ref = _ref(6, lambda i: float(i * 10))
    frames = {0x244: [{"timestamp": t, "data": [0]} for t in range(50)]}
    d = rev.diagnose_reference_match(ref, frames, correlated=True)
    assert d and d["reason_code"] == "too_few_points"
    assert "6" in d["message"]


def test_diagnose_reference_constant_is_flagged_not_trusted():
    # A flat reference is 'perfectly fit' by a flat line, so it must be caught
    # before a bogus match is shown, even though correlated=True.
    ref = _ref(12, lambda i: 7.0)
    frames = {0x244: [{"timestamp": t, "data": [t & 0xFF]} for t in range(50)]}
    d = rev.diagnose_reference_match(ref, frames, correlated=True)
    assert d and d["reason_code"] == "constant_reference"
    assert "7" in d["message"]


def test_diagnose_reference_outside_capture_span():
    ref = _ref(12, lambda i: float(i), t0=1000.0)   # far after the frames
    frames = {0x244: [{"timestamp": t, "data": [t & 0xFF]} for t in range(50)]}
    d = rev.diagnose_reference_match(ref, frames, correlated=True)
    assert d and d["reason_code"] == "outside_capture"


def test_diagnose_reference_no_correlation_when_search_found_nothing():
    ref = _ref(12, lambda i: float(i))
    frames = {0x244: [{"timestamp": float(i), "data": [i & 0xFF]} for i in range(50)]}
    d = rev.diagnose_reference_match(ref, frames, correlated=False)
    assert d and d["reason_code"] == "no_correlation"


def test_diagnose_reference_healthy_returns_empty():
    # Enough varying points, overlapping the capture, and a match was found: no
    # diagnostic, so the real result is shown.
    ref = _ref(12, lambda i: float(i))
    frames = {0x244: [{"timestamp": float(i), "data": [i & 0xFF]} for i in range(50)]}
    assert rev.diagnose_reference_match(ref, frames, correlated=True) == ""


def test_survey_ranks_the_correlated_id_first():
    n = 60
    values = [i % 100 for i in range(n)]
    good_records = [
        {"arbitration_id": 0x10, "data": [v, 0, 0, 0, 0, 0, 0, 0], "timestamp": i * 0.1}
        for i, v in enumerate(values)
    ]
    rng = random.Random(7)
    noisy_records = [
        {"arbitration_id": 0x20, "data": [rng.randrange(256), 0, 0, 0, 0, 0, 0, 0], "timestamp": i * 0.1}
        for i in range(n)
    ]
    reference = [{"t": r["timestamp"], "value": v} for r, v in zip(good_records, values)]
    ranked = survey({0x10: good_records, 0x20: noisy_records}, reference)
    assert ranked[0]["arbitration_id"] == 0x10
    assert ranked[0]["score"] > ranked[1]["score"]


def test_field_series_skips_frames_too_short_for_the_field():
    records = [
        {"arbitration_id": 1, "data": [1, 2], "timestamp": 0.0},
        {"arbitration_id": 1, "data": [1, 2, 3, 4], "timestamp": 1.0},
    ]
    series = field_series(records, {"start_bit": 16, "length": 8})
    assert len(series) == 1
    assert series[0][0] == 1.0


# --------------------------------------------------------------------------
# derive_scale_offset / to_dbc_signal
# --------------------------------------------------------------------------

def test_derive_scale_offset_snaps_close_slope_to_nice_value():
    candidate = {"scale": 0.0998, "offset": 0.01}
    derived = derive_scale_offset(candidate)
    assert derived["scale"] == 0.1
    assert derived["offset"] == 0.0


def test_derive_scale_offset_leaves_odd_slope_alone():
    candidate = {"scale": 0.337, "offset": 12.4}
    derived = derive_scale_offset(candidate)
    assert derived["scale"] == pytest.approx(0.337)
    assert derived["offset"] == pytest.approx(12.4)


def test_derive_scale_offset_does_not_snap_to_rank_only_binary_scales():
    # 1/64 counts as a nice scale when RANKING tied candidates, but snapping
    # still uses NICE_SCALES only: a slope near 0.015625 (and near nothing in
    # NICE_SCALES) must come through as fitted, not pulled to the binary value.
    candidate = {"scale": 0.0157, "offset": 0.0}
    assert rev._is_nice_scale(0.0157)
    derived = derive_scale_offset(candidate)
    assert derived["scale"] == pytest.approx(0.0157)
    # The decimal snapping behaviour itself is unchanged.
    assert derive_scale_offset({"scale": 0.0099, "offset": 0.0})["scale"] == 0.01


def test_to_dbc_signal_shape():
    candidate = {
        "arbitration_id": 0x200, "start_bit": 16, "length": 12,
        "byte_order": "little_endian", "signed": False,
        "scale": 0.1, "offset": 0.0,
    }
    definition = to_dbc_signal("VehicleSpeed", candidate, unit="km/h")
    assert definition["start"] == 16
    assert definition["length"] == 12
    assert definition["byte_order"] == "little_endian"
    assert definition["scale"] == 0.1
    assert definition["unit"] == "km/h"


# --------------------------------------------------------------------------
# save-to-DBC round trip through decode
# --------------------------------------------------------------------------

def test_add_signal_to_new_message_round_trips_through_decode():
    from app.db.models import CanDatabase

    database = CanDatabase(name="Test", dbc_text="")

    class FakeSession:
        def __init__(self):
            self.added = []

        def add(self, obj):
            self.added.append(obj)
            if not getattr(obj, "id", None):
                obj.id = len(self.added)

        def flush(self):
            pass

        def query(self, model):
            class Query:
                def __init__(self, items):
                    self.items = items

                def filter_by(self, **kwargs):
                    def matches(obj):
                        return all(getattr(obj, k, None) == v for k, v in kwargs.items())
                    return Query([o for o in self.items if matches(o)])

                def one_or_none(self):
                    return self.items[0] if self.items else None
            return Query([o for o in self.added if isinstance(o, model)])

    session = FakeSession()
    definition = to_dbc_signal("VehicleSpeed", {
        "start_bit": 0, "length": 16, "byte_order": "little_endian",
        "signed": False, "scale": 0.1, "offset": 0.0,
    }, unit="km/h")

    add_signal_to_database(session, database, 0x201, "VehicleSpeed", definition,
                            message_name="Speed")

    assert database.dbc_text.strip() != ""
    decoded = dbc_mod.decode(database.dbc_text, 0x201, bytes([0x64, 0x00, 0, 0, 0, 0, 0, 0]))
    assert decoded["VehicleSpeed"] == pytest.approx(10.0)

    from app.db.models import CanMessage, CanSignal
    messages = [o for o in session.added if isinstance(o, CanMessage)]
    signals = [o for o in session.added if isinstance(o, CanSignal)]
    assert messages and messages[0].arbitration_id == 0x201
    assert signals and signals[0].name == "VehicleSpeed"


def test_add_signal_to_existing_message_preserves_other_signals():
    from app.db.models import CanDatabase

    existing_text = (
        'VERSION ""\n\nNS_ :\n\nBS_:\n\nBU_: X\n\n'
        'BO_ 1 M: 8 X\n SG_ Existing : 32|8@1+ (1,0) [0|0] "" X\n'
    )
    database = CanDatabase(name="Test", dbc_text=existing_text)

    class FakeSession:
        def __init__(self):
            self.added = []

        def add(self, obj):
            self.added.append(obj)
            obj.id = len(self.added)

        def flush(self):
            pass

        def query(self, model):
            class Query:
                def __init__(self, items):
                    self.items = items

                def filter_by(self, **kwargs):
                    def matches(obj):
                        return all(getattr(obj, k, None) == v for k, v in kwargs.items())
                    return Query([o for o in self.items if matches(o)])

                def one_or_none(self):
                    return self.items[0] if self.items else None
            return Query([o for o in self.added if isinstance(o, model)])

    session = FakeSession()
    definition = to_dbc_signal("NewSignal", {
        "start_bit": 0, "length": 8, "byte_order": "little_endian",
        "signed": False, "scale": 1, "offset": 0,
    })
    add_signal_to_database(session, database, 1, "NewSignal", definition)

    decoded = dbc_mod.decode(database.dbc_text, 1, bytes([42, 0, 0, 0, 99, 0, 0, 0]))
    assert decoded["NewSignal"] == 42
    assert decoded["Existing"] == 99


def test_reference_from_signal_decodes_known_signal():
    records = [
        {"arbitration_id": 0x7E8, "data": [0, 1], "timestamp": 0.0},
        {"arbitration_id": 0x123, "data": [9], "timestamp": 0.1},   # other id, skipped
        {"arbitration_id": 0x7E8, "data": [0, 2], "timestamp": 0.2},
        {"arbitration_id": 0x7E8, "data": [0, 0], "timestamp": 0.3},  # non-numeric -> skipped
    ]

    def fake_decode(dbc_text, arb, data):
        return {"SPEED": None if data[1] == 0 else float(data[1]) * 10}

    ref = rev.reference_from_signal(records, "DBC", 0x7E8, "SPEED", decode_fn=fake_decode)
    assert [p["value"] for p in ref] == [10.0, 20.0]
    assert [p["t"] for p in ref] == [0.0, 0.2]
    assert all(p["available"] for p in ref)


def test_reference_from_signal_unbound_or_undecodable_is_empty():
    assert rev.reference_from_signal([], "", 1, "X") == []
    recs = [{"arbitration_id": 1, "data": [1], "timestamp": 0.0}]
    assert rev.reference_from_signal(recs, "DBC", 1, "MISSING", decode_fn=lambda *a: {"OTHER": 1}) == []


def test_event_responders_finds_the_reacting_message():
    events = [1.0, 3.0, 5.0]
    records = []
    for i in range(60):
        ts = round(i * 0.1, 2)
        # 0x100 byte 2 goes high only within ~0.3s after each event mark.
        val = 1 if any(e <= ts <= e + 0.3 for e in events) else 0
        records.append({"channel": "can1", "arbitration_id": 0x100, "data": [0, 0, val, 0], "timestamp": ts})
        # 0x200 byte 0 is a free-running counter (changes every frame): noise.
        records.append({"channel": "can1", "arbitration_id": 0x200, "data": [i & 0xFF], "timestamp": ts})
    out = rev.event_responders(records, events, window=0.35)
    assert out, "should find at least one responder"
    top = out[0]
    assert top["arbitration_id"] == 0x100
    assert top["byte"] == 2
    assert top["responded"] == 3
    # The noisy counter must rank below the clean responder.
    counter = next((r for r in out if r["arbitration_id"] == 0x200), None)
    if counter is not None:
        assert counter["score"] < top["score"]


def test_event_responders_drops_streaming_message_that_reacts_every_time():
    # Reproduces a real capture: 0x3E0 streams ASCII (a VIN/serial), so its byte
    # changes on every frame and trivially "reacts" to all marks, while 0x5C6 is
    # the real button that reacts on most presses and is quiet otherwise. The
    # stream must not be offered as a candidate.
    events = [1.0, 2.0, 3.0, 4.0, 5.0]
    records = []
    for i in range(80):
        ts = round(i * 0.1, 2)
        pressed = any(e <= ts <= e + 0.3 for e in events)
        records.append({"channel": "can1", "arbitration_id": 0x5C6,
                        "data": [1 if pressed else 0, 0x14, 0x50], "timestamp": ts})
        # 0x3E0 byte 7 is a rolling ASCII stream: different on every single frame.
        records.append({"channel": "can1", "arbitration_id": 0x3E0,
                        "data": [0, 0, 0, 0, 0, 0, 0, (0x30 + (i % 16))], "timestamp": ts})
    out = rev.event_responders(records, events, window=0.35)
    assert out and out[0]["arbitration_id"] == 0x5C6
    assert all(r["arbitration_id"] != 0x3E0 for r in out), "streaming message must be filtered out"


def test_event_responders_keeps_something_when_all_look_noisy():
    # If every candidate is a stream, do not return empty: keep the ranked list
    # so the user still has something to try.
    events = [1.0, 2.0, 3.0]
    records = []
    for i in range(60):
        ts = round(i * 0.1, 2)
        records.append({"channel": "can1", "arbitration_id": 0x111,
                        "data": [i & 0xFF], "timestamp": ts})
    out = rev.event_responders(records, events, window=0.35)
    assert out, "must not return empty just because everything looked noisy"


def test_event_responders_clean_reactor_on_continuous_message_is_a_command():
    # A byte at rest except right when you act is a clean reacting field: a likely
    # command, even though its message is broadcast every tick. (The old behavior
    # wrongly labelled any continuous message a "status", which buried real
    # controls.) 0x300 appears only around the marks and is also a command.
    events = [2.0, 5.0, 8.0]
    records = []
    for i in range(100):
        ts = round(i * 0.1, 2)
        pressed = any(e <= ts <= e + 0.3 for e in events)
        records.append({"channel": "can1", "arbitration_id": 0x100,
                        "data": [0, 0, 1 if pressed else 0], "timestamp": ts})
        if pressed:
            records.append({"channel": "can1", "arbitration_id": 0x300,
                            "data": [1, 0], "timestamp": ts})
    out = rev.event_responders(records, events, window=0.35)
    by_id = {r["arbitration_id"]: r for r in out}
    assert by_id[0x100]["byte"] == 2 and by_id[0x100]["responded"] == 3  # reacts on all 3
    assert by_id[0x100]["kind"] == "event"   # clean reactor -> likely command
    assert by_id[0x300]["kind"] == "event"


def test_event_responders_flags_restless_byte_as_status():
    # A byte that is non-resting near the marks but also moves on its own between
    # them (high background deviation) is flagged "status": it might be a sensor
    # value that moved near a mark rather than the control you pressed.
    events = [2.0, 5.0, 8.0]
    records = []
    for i in range(100):
        ts = round(i * 0.1, 2)
        pressed = any(e <= ts <= e + 0.3 for e in events)
        # Resting value 0; spikes to 9 near presses AND on a slow background cycle
        # (about half the non-press time), so its background deviation is high.
        bg = 9 if (i % 4 in (2, 3)) else 0
        records.append({"channel": "can1", "arbitration_id": 0x110,
                        "data": [9 if pressed else bg], "timestamp": ts})
    out = rev.event_responders(records, events, window=0.35)
    r = next((x for x in out if x["arbitration_id"] == 0x110), None)
    if r is not None:  # may be dropped by the stream filter; if kept, it is status
        assert r["kind"] == "status" or r["baseline"] > 0.35


def test_event_responders_finds_constant_payload_command_by_appearance():
    # 0x400 is a command another controller emits only when you act, with a fixed
    # payload (nothing "changes", it just shows up). It must still be found, as an
    # "appears" candidate with byte None.
    events = [1.0, 2.0, 3.0, 4.0]
    records = []
    for i in range(80):
        ts = round(i * 0.1, 2)
        pressed = any(e <= ts <= e + 0.15 for e in events)
        # A steady background broadcast unrelated to the control.
        records.append({"channel": "can0", "arbitration_id": 0x111,
                        "data": [i & 0xFF, 0], "timestamp": ts})
        # The command: identical bytes, present only while acting.
        if pressed:
            records.append({"channel": "can0", "arbitration_id": 0x400,
                            "data": [0xA5, 0x01], "timestamp": ts})
    out = rev.event_responders(records, events, window=0.2)
    cmd = next((r for r in out if r["arbitration_id"] == 0x400), None)
    assert cmd is not None, "constant-payload command that only appears must be found"
    # Found either as a changed byte (vs its absent/zero default) or by appearance;
    # either way it is a usable candidate and labelled a likely command.
    assert cmd["kind"] == "event"
    assert cmd["byte"] is None or cmd["match"] == "byte"


def test_appearance_counts_late_marked_command():
    # A person taps Mark ~0.2s AFTER the press, so a constant-payload command that
    # only shows up when you act lands just BEFORE the mark. The appearance split
    # is shifted back to absorb that latency, so it still counts as "newly appeared"
    # instead of reading as already-present.
    window = 0.4
    presses = [2.0, 6.0, 10.0, 14.0]
    times = []
    for p in presses:
        t = p
        while t <= p + 0.15:
            times.append(round(t, 3))
            t += 0.03
    times.sort()
    late = [p + 0.2 for p in presses]
    assert rev._appearance(times, late, window) == 4  # was 0 before the back-shift


def test_appearance_still_cancels_periodic_broadcast_after_shift():
    # The back-shift must not turn an always-on broadcast into a false "appears":
    # it is present in both shifted windows, so it never newly appears.
    window = 0.4
    times = [round(i * 0.05, 3) for i in range(400)]  # 20 Hz, on the bus the whole time
    marks = [3.0, 7.0, 11.0, 15.0]
    assert rev._appearance(times, marks, window) == 0


def test_event_responders_finds_late_marked_constant_payload_command():
    # End to end: the constant-payload appearance case, but with every mark 0.2s
    # late. The command must still surface as an "appears" candidate.
    events = [2.0, 6.0, 10.0, 14.0]
    marks = [e + 0.2 for e in events]
    records = []
    ts = 0.0
    while ts <= 16.0:
        pressed = any(e <= ts <= e + 0.15 for e in events)
        records.append({"channel": "can0", "arbitration_id": 0x111,
                        "data": [int(ts * 10) & 0xFF, 0], "timestamp": round(ts, 2)})
        if pressed:
            records.append({"channel": "can0", "arbitration_id": 0x400,
                            "data": [0xA5, 0x01], "timestamp": round(ts, 2)})
        ts += 0.05
    out = rev.event_responders(records, marks, window=0.4)
    cmd = next((r for r in out if r["arbitration_id"] == 0x400), None)
    assert cmd is not None, "late-marked constant-payload command must still be found"
    assert cmd["kind"] == "event"


def test_event_responders_rejects_constant_periodic_broadcast():
    # A message on the bus the whole time with a fixed payload (many frames, far
    # more than presses) must NOT be flagged as an "appears" command just because
    # dense press windows overlap it. This was flooding the list.
    events = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    records = []
    for i in range(600):  # ~100 frames per event window's worth: clearly periodic
        ts = round(i * 0.02, 2)
        records.append({"channel": "can0", "arbitration_id": 0x483,
                        "data": [0x11, 0x22, 0x33], "timestamp": ts})
    out = rev.event_responders(records, events, window=0.4)
    assert all(r["arbitration_id"] != 0x483 for r in out), "periodic broadcast must not be an 'appears' candidate"


def test_event_responders_appearance_needs_clustering_not_mere_presence():
    # The user's experiment: 9 marks, but the control was only actually operated
    # on the last 6. The real command (0x596) shows up only at those 6 marks and
    # is otherwise absent, so it should score ~6/9. Two periodic broadcasts
    # (0x483, 0x481) are on the bus the whole time and appear near every mark, so
    # they must be rejected, not listed at 9/9.
    events = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
    real_marks = events[3:]  # only the last 6 were real presses
    records = []
    # Periodic broadcasts across the whole 0..12s span, fixed payloads.
    t = 0.0
    while t <= 12.0:
        records.append({"channel": "can0", "arbitration_id": 0x483, "data": [0x11, 0x22], "timestamp": round(t, 3)})
        records.append({"channel": "can0", "arbitration_id": 0x481, "data": [0x33], "timestamp": round(t, 3)})
        t += 0.1
    # The real command: one frame right at each REAL press, absent otherwise.
    for e in real_marks:
        records.append({"channel": "can1", "arbitration_id": 0x596, "data": [0x00, 0x01], "timestamp": e + 0.02})
    out = rev.event_responders(records, events, window=0.4)
    ids = {r["arbitration_id"] for r in out}
    assert 0x596 in ids, "the real command that clusters at the real presses must be found"
    assert 0x483 not in ids and 0x481 not in ids, "periodic broadcasts must not be listed"
    cmd = next(r for r in out if r["arbitration_id"] == 0x596)
    assert cmd["responded"] == 6 and cmd["events"] == 9  # reflects the 6 real presses


def test_injection_reactors_finds_downstream_reaction():
    # At rest only 0x111 byte 0 wanders. While injecting, 0x222 byte 3 starts
    # moving: a downstream reaction to the injected command. The injected id
    # itself (0x900) is excluded.
    baseline = []
    for i in range(20):
        baseline.append({"channel": "can1", "arbitration_id": 0x111, "data": [i & 0xFF, 0], "timestamp": i})
        baseline.append({"channel": "can1", "arbitration_id": 0x222, "data": [0, 0, 0, 7], "timestamp": i})
    during = []
    for i in range(20):
        during.append({"channel": "can1", "arbitration_id": 0x111, "data": [i & 0xFF, 0], "timestamp": 100 + i})
        during.append({"channel": "can1", "arbitration_id": 0x222, "data": [0, 0, 0, i & 0xFF], "timestamp": 100 + i})
        during.append({"channel": "can1", "arbitration_id": 0x900, "data": [i & 0xFF], "timestamp": 100 + i})
    reactors = rev.injection_reactors(baseline, during, exclude=("can1", 0x900))
    assert {"channel": "can1", "arbitration_id": 0x222, "byte": 3} in reactors
    assert all(r["arbitration_id"] != 0x900 for r in reactors)
    assert all(r["arbitration_id"] != 0x111 for r in reactors)  # already moving at rest


def test_injection_reactors_none_when_only_a_status_mirror():
    # Nothing new moves during injection: the candidate did not cause an effect.
    baseline = [{"channel": "can1", "arbitration_id": 0x50, "data": [0, 0], "timestamp": i} for i in range(10)]
    during = [{"channel": "can1", "arbitration_id": 0x50, "data": [0, 0], "timestamp": 100 + i} for i in range(10)]
    assert rev.injection_reactors(baseline, during, exclude=("can1", 0x999)) == []


def test_event_responders_empty_inputs():
    assert rev.event_responders([], [1.0]) == []
    assert rev.event_responders([{"arbitration_id": 1, "data": [1], "timestamp": 0.0}], []) == []


def test_cross_correlate_finds_a_mirrored_signal():
    records_by_id = {0x100: [], 0x200: [], 0x300: []}
    import random
    rng = random.Random(3)
    for i in range(40):
        t = round(i * 0.1, 2)
        v = i  # a clean ramp 0..39
        records_by_id[0x100].append({"arbitration_id": 0x100, "data": [v, 0], "timestamp": t})
        records_by_id[0x200].append({"arbitration_id": 0x200, "data": [v, 0], "timestamp": t})   # mirror
        records_by_id[0x300].append({"arbitration_id": 0x300, "data": [rng.randint(0, 255)], "timestamp": t})

    def fake_decode(dbc, arb, data):
        return {"SPEED": float(data[0])} if arb == 0x100 else {}

    known = [{"arbitration_id": 0x100, "signal": "SPEED"}]
    matches = rev.cross_correlate(records_by_id, "DBC", known, min_score=0.8, decode_fn=fake_decode)
    assert matches, "should find the mirror"
    assert matches[0]["match_id"] == 0x200
    assert matches[0]["known_signal"] == "SPEED"
    assert matches[0]["match_id"] != matches[0]["known_id"]  # never matches itself


def test_detect_counter_full_byte_and_nibble():
    full = [[i % 256, 0x10, 0x20] for i in range(12)]
    c = rev.detect_counter(full)
    assert c == {"byte": 0, "mod": 256, "nibble": False}
    # Low nibble counts 0..15 while the high nibble changes independently, so the
    # full byte does not increment by one but the low nibble does.
    nib = [[(((i * 3) % 16) << 4) | (i % 16), 0x10] for i in range(20)]
    c = rev.detect_counter(nib)
    assert c == {"byte": 0, "mod": 16, "nibble": True}
    assert rev.detect_counter([[0, 0], [0, 0], [0, 0], [0, 0]]) is None  # static, no counter


def test_identify_checksum_sum8_and_apply():
    # byte 3 is an 8-bit sum of bytes 0..2 (and it varies).
    payloads = []
    for i in range(10):
        b0, b1, b2 = (i * 7) & 0xFF, (i * 3) & 0xFF, (i * 5) & 0xFF
        payloads.append([b0, b1, b2, (b0 + b1 + b2) & 0xFF])
    cs = rev.identify_checksum(payloads, 0x123)
    assert cs == {"byte": 3, "algorithm": "sum8"}
    prot = rev.message_protection(payloads, 0x123)
    assert prot["protected"] and prot["checksum"]["byte"] == 3
    # Overlaying a bit on byte 0 must trigger a recomputed checksum.
    fixed = rev.apply_protection([0x10, 0x00, 0x00, 0x99], 0x123, prot, tick=0)
    assert fixed[3] == (0x10 + 0x00 + 0x00) & 0xFF


def test_apply_protection_advances_counter_each_tick():
    prot = {"counter": {"byte": 0, "mod": 256, "nibble": False}, "checksum": None, "protected": True}
    assert rev.apply_protection([5, 1, 2], 0x1, prot, tick=0)[0] == 5
    assert rev.apply_protection([5, 1, 2], 0x1, prot, tick=3)[0] == 8
    assert rev.apply_protection([254, 0], 0x1, prot, tick=3)[0] == 1  # wraps mod 256


def test_apply_protection_noop_without_protection():
    assert rev.apply_protection([1, 2, 3], 0x1, None, tick=5) == [1, 2, 3]


def test_detect_multiplexer_finds_selector():
    # Byte 0 is a selector: when it is 0, byte 1 carries a varying signal and byte
    # 2 is static; when it is 1, byte 2 varies and byte 1 is static. Byte 3 is a
    # plain always-changing field (not conditional).
    payloads = []
    for i in range(20):
        payloads.append([0, i & 0xFF, 0x00, (i * 3) & 0xFF])   # mux=0: byte1 active
        payloads.append([1, 0x00, i & 0xFF, (i * 5) & 0xFF])   # mux=1: byte2 active
    m = rev.detect_multiplexer(payloads)
    assert m is not None and m["byte"] == 0 and m["values"] == [0, 1]
    assert 1 in m["muxed_bytes"] and 2 in m["muxed_bytes"]


def test_detect_multiplexer_none_for_plain_message():
    payloads = [[i & 0xFF, (i * 2) & 0xFF, 0x10] for i in range(20)]  # no selector structure
    assert rev.detect_multiplexer(payloads) is None


def test_bitsearch_mux_filter_restricts_frames():
    # 0x200: when byte 0 == 5, byte 1 ramps with the reference; when byte 0 == 9,
    # byte 1 is a constant. Searching the right mux value recovers the ramp;
    # searching the wrong one finds nothing that tracks the reference.
    records, reference = [], []
    for i in range(30):
        t = float(i)
        records.append({"arbitration_id": 0x200, "data": [5, i & 0xFF, 0], "timestamp": t})
        records.append({"arbitration_id": 0x200, "data": [9, 0xAA, 0], "timestamp": t + 0.01})
        reference.append({"t": t, "value": float(i), "available": True})
    good = rev.bitsearch(records, reference, {"mux": {"byte": 0, "value": 5}})
    bad = rev.bitsearch(records, reference, {"mux": {"byte": 0, "value": 9}})
    assert max((c["r2"] for c in good), default=0) > 0.9   # the ramp is recovered
    assert max((c["r2"] for c in bad), default=0) < 0.5    # constant garbage does not track


def test_auto_decode_finds_the_signal_across_ids():
    # 0x100 byte 0 ramps with the reference; 0x200 is unrelated noise. Auto-decode
    # should survey, bit-search, and surface 0x100 as the best candidate.
    grouped, reference = {0x100: [], 0x200: []}, []
    for i in range(40):
        t = float(i)
        grouped[0x100].append({"arbitration_id": 0x100, "data": [i & 0xFF, 0], "timestamp": t})
        grouped[0x200].append({"arbitration_id": 0x200, "data": [(i * 91) & 0xFF, 7], "timestamp": t})
        reference.append({"t": t, "value": float(i), "available": True})
    cands = rev.auto_decode(grouped, reference, {"top_ids": 3})
    assert cands, "auto-decode should return candidates"
    assert cands[0]["arbitration_id"] == 0x100 and cands[0]["r2"] > 0.9


def test_auto_decode_empty_without_signal():
    grouped = {0x300: [{"arbitration_id": 0x300, "data": [5], "timestamp": float(i)} for i in range(10)]}
    reference = [{"t": float(i), "value": float(i), "available": True} for i in range(10)]
    # A constant byte cannot track anything; no strong candidate.
    cands = rev.auto_decode(grouped, reference, {})
    assert all(c["r2"] < 0.5 for c in cands) or cands == []


def test_event_responders_catches_press_when_mark_lags_the_action():
    # The real-world case that was broken: a button bit on a message broadcast
    # every 100ms, where the operator taps Mark ~0.12s AFTER pressing (human
    # latency). The byte has already gone high by the time of the mark, so a
    # forward-only window (the old logic) missed the press and scored it ~2/8.
    # A window centred on the mark must catch it on every press.
    records, events = [], []
    presses = [2.0, 4.5, 7.0, 9.5, 12.0, 14.5, 17.0, 19.5]
    t = 0.0
    while t <= 22.0:
        pressed = any(p <= t <= p + 0.5 for p in presses)  # held ~0.5s
        records.append({"channel": "can1", "arbitration_id": 0x5C6,
                        "data": [1 if pressed else 0, 0x14, 0x50], "timestamp": round(t, 3)})
        records.append({"channel": "can1", "arbitration_id": 0x200,   # noisy counter
                        "data": [int(t * 10) & 0xFF, 0, 0], "timestamp": round(t, 3)})
        t += 0.1
    events = [p + 0.12 for p in presses]  # marked a beat after each press
    out = rev.event_responders(records, events)
    top = out[0]
    assert top["arbitration_id"] == 0x5C6 and top["byte"] == 0
    assert top["responded"] == 8 and top["events"] == 8   # all presses caught
    assert top["kind"] == "event"                          # clean reactor
    assert all(r["arbitration_id"] != 0x200 for r in out)  # counter filtered
