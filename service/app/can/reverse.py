"""Signal Finder: deterministic CAN reverse engineering.

Implements the pipeline described in CSS Electronics' write-up on
statistically reverse engineering CAN signals (no LLM needed to run it): take
a captured run of frames for one arbitration id plus a reference signal (a
value you recorded by hand while operating the real control, or an
already-decoded signal used as ground truth), enumerate plausible bit fields,
correlate each decoded field against the reference, and rank the candidates
by fit quality. The winner's scale and offset are derived from a linear fit,
rounded to an OEM-realistic step when close, and can be saved as a named
signal onto an existing CAN database.

Every function here is pure and dependency-free (no numpy/scipy): plain
Python integer and float math only, so the whole pipeline is unit-testable
without hardware, a database, or a running app. The one exception is
:func:`add_signal_to_database`, which talks to cantools and a SQLAlchemy
session to persist a result; the search and statistics that lead up to it
never touch either.

Bit numbering matches the DBC/cantools convention exactly (verified in
``tests/test_can_reverse.py`` against cantools' own decode):

- Intel (``little_endian``): ``start_bit`` is the field's least significant
  bit, numbered as ``byte_index * 8 + bit_index_in_byte`` (bit 0 of byte 0 is
  the LSB of the whole frame), and the field's more significant bits sit at
  increasing bit numbers.
- Motorola (``big_endian``): ``start_bit`` is the field's most significant
  bit, numbered so that byte 0's bit 7 (its own MSB) is DBC bit 0, byte 0's
  bit 0 (its own LSB) is DBC bit 7, byte 1's bit 7 is DBC bit 8, and so on;
  the field then reads towards *decreasing* bit-in-byte positions and wraps
  into the next byte's bit 7 the same way a normal big-endian integer would.
"""
from __future__ import annotations

import bisect
import math
from collections import Counter
from typing import Any, Iterable, Sequence

BYTE_ORDERS = ("little_endian", "big_endian")

# Bit widths worth trying by default. Real OEM signals overwhelmingly land on
# one of these; searching every width from 1 to 64 would be needlessly slow
# and would not turn up anything a human would actually choose to encode.
DEFAULT_LENGTHS = (1, 2, 3, 4, 6, 8, 10, 12, 14, 16, 20, 24, 32)

# "Nice" scale factors an OEM signal is likely to use. A fitted slope close
# to one of these is snapped to it.
NICE_SCALES = (1, 0.1, 0.01, 0.001, 0.5, 0.25, 0.125, 0.05, 0.02, 0.2, 2, 5, 10)


# --------------------------------------------------------------------------
# Bit-level field extraction
# --------------------------------------------------------------------------

def extract_field(data: bytes | Sequence[int], start_bit: int, length: int,
                   byte_order: str = "little_endian", signed: bool = False) -> int:
    """Pull one field out of a frame's data bytes.

    ``start_bit``/``length``/``byte_order`` follow the DBC/cantools bit
    numbering described in the module docstring. Raises ``ValueError`` if the
    field does not fit inside ``data`` or ``byte_order`` is not recognized.
    """
    if length <= 0:
        raise ValueError("length must be positive")
    if start_bit < 0:
        raise ValueError("start_bit must not be negative")
    raw = bytes(data)
    n_bits = len(raw) * 8
    if n_bits == 0:
        raise ValueError("data has no bytes")

    if byte_order == "little_endian":
        if start_bit + length > n_bits:
            raise ValueError("field does not fit in the frame")
        frame_int = int.from_bytes(raw, "little")
        value = (frame_int >> start_bit) & ((1 << length) - 1)
    elif byte_order == "big_endian":
        phys_start = 8 * (start_bit // 8) + (7 - start_bit % 8)
        if phys_start < 0 or phys_start + length > n_bits:
            raise ValueError("field does not fit in the frame")
        frame_int = int.from_bytes(raw, "big")
        shift = n_bits - phys_start - length
        value = (frame_int >> shift) & ((1 << length) - 1)
    else:
        raise ValueError(f"unknown byte order: {byte_order!r}")

    if signed and (value >> (length - 1)) & 1:
        value -= 1 << length
    return value


def _field_get(field: dict, key: str, default: Any = None) -> Any:
    return field.get(key, default) if isinstance(field, dict) else getattr(field, key, default)


def field_series(records: list[dict], field: dict) -> list[tuple[float, int]]:
    """Decode one field across every frame of an id: ``[(timestamp, raw), ...]``.

    ``field`` is a plain dict (or any object with matching attributes):
    ``start_bit``, ``length``, ``byte_order`` (default ``"little_endian"``),
    ``signed`` (default False). A frame too short for the field is skipped
    rather than raising, since a real capture sometimes mixes DLCs for one id.
    """
    start_bit = _field_get(field, "start_bit")
    length = _field_get(field, "length")
    byte_order = _field_get(field, "byte_order", "little_endian")
    signed = _field_get(field, "signed", False)
    out: list[tuple[float, int]] = []
    for record in records:
        data = record.get("data") or []
        try:
            value = extract_field(bytes(data), start_bit, length, byte_order, signed)
        except ValueError:
            continue
        out.append((float(record.get("timestamp", 0.0)), value))
    return out


# --------------------------------------------------------------------------
# Bit activity heatmap and per-byte classification
# --------------------------------------------------------------------------

def _byte_values(records: list[dict], byte_index: int) -> list[int]:
    values = []
    for record in records:
        data = record.get("data") or []
        values.append(data[byte_index] if byte_index < len(data) else 0)
    return values


def _bit_flip_rates(records: list[dict], n_bytes: int) -> list[float]:
    """Per-bit flip rate (fraction of consecutive frame pairs where the bit
    changed), indexed 0..n_bytes*8-1 in little-endian (Intel) bit numbering,
    which is the natural numbering for a raw activity heatmap regardless of
    what byte order the eventual signal turns out to use."""
    n_bits = n_bytes * 8
    frames = [record.get("data") or [] for record in records]
    rates = []
    for bit in range(n_bits):
        byte_idx, bit_idx = divmod(bit, 8)
        series = [
            (frame[byte_idx] >> bit_idx) & 1 if byte_idx < len(frame) else 0
            for frame in frames
        ]
        if len(series) < 2:
            rates.append(0.0)
            continue
        changes = sum(1 for i in range(1, len(series)) if series[i] != series[i - 1])
        rates.append(changes / (len(series) - 1))
    return rates


def _shannon_entropy(values: list[int]) -> float:
    if not values:
        return 0.0
    counts = Counter(values)
    total = len(values)
    return -sum((n / total) * math.log2(n / total) for n in counts.values())


def classify_byte(values: list[int]) -> tuple[str, float]:
    """Classify one byte's value sequence across a capture.

    Returns ``(label, score)`` where ``label`` is one of ``"static"``
    (never changes), ``"counter"`` (a regular rolling increment, the low
    bits of a frame counter or a clock), ``"checksum"`` (high-entropy,
    non-sequential: a byte that depends on everything else in the frame),
    or ``"candidate"`` (changes, but not in either of those recognizable
    ways: worth bitsearching). ``score`` is the confidence behind the
    classification, roughly 0..1.
    """
    if not values:
        return "static", 0.0
    if max(values) == min(values):
        return "static", 1.0

    if len(values) > 1:
        diffs = [(values[i] - values[i - 1]) % 256 for i in range(1, len(values))]
        counts = Counter(diffs)
        common_diff, hits = counts.most_common(1)[0]
        frac = hits / len(diffs)
        if common_diff != 0 and frac >= 0.6:
            return "counter", round(frac, 3)

    entropy = _shannon_entropy(values)
    total = len(values)
    max_possible = math.log2(min(256, total)) if total > 1 else 0.0
    norm_entropy = (entropy / max_possible) if max_possible > 0 else 0.0
    unique_fraction = len(set(values)) / total
    if norm_entropy >= 0.8 and unique_fraction >= 0.5:
        return "checksum", round(norm_entropy, 3)
    return "candidate", round(norm_entropy, 3)


def bit_activity(records: list[dict]) -> dict:
    """Per-bit flip-rate heatmap and per-byte classification for one
    arbitration id's frames, shaped for direct UI rendering."""
    if not records:
        return {"arbitration_id": None, "length": 0, "frame_count": 0,
                "bit_activity": [], "bytes": []}

    n_bytes = max(len(record.get("data") or []) for record in records)
    bit_rates = _bit_flip_rates(records, n_bytes)
    bytes_info = []
    for byte_index in range(n_bytes):
        values = _byte_values(records, byte_index)
        label, score = classify_byte(values)
        bytes_info.append({
            "index": byte_index,
            "classification": label,
            "score": score,
            "min": min(values) if values else 0,
            "max": max(values) if values else 0,
            "unique_values": len(set(values)),
            "bit_activity": [round(r, 3) for r in bit_rates[byte_index * 8:byte_index * 8 + 8]],
        })
    return {
        "arbitration_id": records[0].get("arbitration_id"),
        "length": n_bytes,
        "frame_count": len(records),
        "bit_activity": [round(r, 3) for r in bit_rates],
        "bytes": bytes_info,
    }


def activity_survey(records_by_id: dict[int, list[dict]]) -> list[dict]:
    """Reference-free survey of which arbitration ids are actually carrying
    live data in a short capture, and which of their bytes are changing, so a
    bench technician can see what is active on a bus and pick an id to
    bitsearch before they know what signal they are even looking for.

    Ranked with the busiest-looking ids (most changing bytes) first, and on a
    tie, by arbitration id. Each entry is a per-id :func:`bit_activity`
    summary plus ``changing_bytes``, the indices of the bytes classified as
    ``"counter"``, ``"checksum"``, or ``"candidate"`` (anything not
    ``"static"``).
    """
    results = []
    for arbitration_id, records in records_by_id.items():
        if not records:
            continue
        info = bit_activity(records)
        changing_bytes = [b["index"] for b in info["bytes"] if b["classification"] != "static"]
        results.append({
            "arbitration_id": arbitration_id,
            "frame_count": info["frame_count"],
            "length": info["length"],
            "changing_bytes": changing_bytes,
            "bytes": info["bytes"],
        })
    results.sort(key=lambda r: (-len(r["changing_bytes"]), r["arbitration_id"]))
    return results


# --------------------------------------------------------------------------
# Reference alignment
# --------------------------------------------------------------------------

def _sample_at(timestamps: list[float], values: list[float], target: float, method: str) -> float | None:
    if not timestamps:
        return None
    if target <= timestamps[0]:
        return values[0]
    if target >= timestamps[-1]:
        return values[-1]
    i = bisect.bisect_left(timestamps, target)
    if timestamps[i] == target:
        return values[i]
    lo, hi = i - 1, i
    t0, t1 = timestamps[lo], timestamps[hi]
    v0, v1 = values[lo], values[hi]
    if method == "linear" and t1 != t0:
        frac = (target - t0) / (t1 - t0)
        return v0 + frac * (v1 - v0)
    return v0 if (target - t0) <= (t1 - target) else v1


def resample(series: list[tuple[float, float]], reference: list[dict], *,
             lags: Iterable[float] | None = None, method: str = "nearest") -> dict:
    """Align a decoded field series and a reference series onto one timeline.

    ``series`` is ``[(t, value), ...]`` as returned by :func:`field_series`.
    ``reference`` is a list of ``{"t": ..., "value": ..., "available": bool}``
    points (a bench technician's manual sweep table, or an already-decoded
    signal used as ground truth); a point with ``available`` set to False is
    dropped (the technician could not confirm the state at that moment).

    Each surviving reference point is matched to the decoded series at its
    own timestamp minus a time lag, using nearest-sample or linear
    interpolation. When ``lags`` is given (a list of candidate lag values in
    seconds, positive meaning the decoded signal reacts *after* the
    reference), every candidate is tried and the one whose aligned pair has
    the strongest rank correlation is kept, absorbing a human's reaction
    delay when they typed a "reference true now" row a beat late. With no
    ``lags`` (the default), a lag of 0 is used.

    Returns ``{"xs": [...decoded...], "ys": [...reference...], "lag": ...}``.
    """
    ref_points = [(p["t"], p["value"]) for p in reference if p.get("available", True)]
    if not series or not ref_points:
        return {"xs": [], "ys": [], "lag": 0.0}

    sorted_series = sorted(series, key=lambda p: p[0])
    timestamps = [p[0] for p in sorted_series]
    values = [p[1] for p in sorted_series]

    candidate_lags = list(lags) if lags is not None else [0.0]
    best: tuple[float, float, list[float], list[float]] | None = None
    for lag in candidate_lags:
        xs: list[float] = []
        ys: list[float] = []
        for t, ref_value in ref_points:
            sampled = _sample_at(timestamps, values, t - lag, method)
            if sampled is None:
                continue
            xs.append(sampled)
            ys.append(ref_value)
        if not xs:
            continue
        # A lag can only be scored (and so compared against another lag) once
        # there are at least two aligned points with some spread on both
        # sides; otherwise keep it as a low-priority fallback so a single
        # matched point (or a single candidate lag, the common case) still
        # comes back instead of an empty result.
        if len(xs) >= 2 and len(set(xs)) > 1 and len(set(ys)) > 1:
            score = abs(spearman(xs, ys))
        else:
            score = -1.0
        if best is None or score > best[0]:
            best = (score, lag, xs, ys)

    if best is None:
        return {"xs": [], "ys": [], "lag": 0.0}
    _, lag, xs, ys = best
    return {"xs": xs, "ys": ys, "lag": lag}


def reference_from_events(event_times: Sequence[float], span: tuple[float, float] | None = None,
                           window: float = 0.4, high: float = 1.0,
                           samples: int | None = None) -> list[dict]:
    """Turn button-press timestamps into a pulse-train reference.

    Each press in ``event_times`` is treated as the control going high for
    ``window`` seconds (a bench technician holding a button, or just a quick
    tap the bus needs a moment to register); the reference reads ``high``
    for that window and ``0`` everywhere else, so the existing bitsearch
    (which already handles a length-1 field) can find the bit that toggles
    when the button is pressed.

    ``span`` is the ``(start, end)`` time range to sample across; defaults to
    the first press minus one window through the last press plus one window
    when omitted (so a lone press still produces a sensible low-high-low
    shape). ``samples`` is how many points to emit across the span; defaults
    to roughly 20 points per second of span (at least 2 points, and at least
    one point per press so no pulse is skipped by a low sample rate).
    """
    events = sorted(float(t) for t in event_times)
    if not events:
        return []
    if span is None:
        span = (events[0] - window, events[-1] + window)
    start, end = span
    if end < start:
        start, end = end, start

    if samples is None:
        duration = max(end - start, 0.0)
        samples = max(2, int(duration * 20), len(events) * 2)
    samples = max(2, int(samples))

    if end == start:
        times = [start]
    else:
        step = (end - start) / (samples - 1)
        times = [start + i * step for i in range(samples)]

    # Make sure every pulse actually shows up even if the sample grid steps
    # over it: add the window's rising/falling edges explicitly.
    edge_times: list[float] = []
    for t in events:
        edge_times.append(max(start, t))
        edge_times.append(min(end, t + window))
    all_times = sorted(set(times) | {t for t in edge_times if start <= t <= end})

    out = []
    for t in all_times:
        active = any(t0 <= t < t0 + window for t0 in events)
        out.append({"t": t, "value": high if active else 0.0, "available": True})
    return out


# --------------------------------------------------------------------------
# Pure statistics: rank correlation and least-squares fit
# --------------------------------------------------------------------------

def _last_index_before(times: list[float], target: float) -> int | None:
    """Index of the last timestamp strictly before ``target``, or None."""
    idx = bisect.bisect_left(times, target) - 1
    return idx if idx >= 0 else None


# Above this per-byte background change rate (fraction of frames where the byte
# differs from the one before), a byte is treated as a data stream or a
# free-running counter rather than a discrete control.
STREAM_FLIP_RATE = 0.75


# --------------------------------------------------------------------------
# Message protection: rolling counter + checksum. Many command messages carry a
# counter that increments every frame and a checksum over the payload; an ECU
# rejects a frame whose counter does not advance or whose checksum is wrong. So
# a plain replay (or an overlaid bit on a captured frame) is dropped no matter
# how fast it is flooded. Detect these so we can regenerate valid frames, and
# so the UI can warn when a control is protected. All pure over frame payloads.
# --------------------------------------------------------------------------

def detect_counter(payloads: list[list[int]]) -> dict | None:
    """Find a byte (or its low nibble) that increments by one every frame.

    Returns ``{"byte": i, "mod": 16|256, "nibble": bool}`` or None. Needs the
    step to hold across almost all consecutive frames, so a noisy data byte that
    happens to rise once is not mistaken for a counter."""
    if len(payloads) < 4:
        return None
    width = min((len(p) for p in payloads), default=0)
    for b in range(width):
        vals = [int(p[b]) for p in payloads]
        full_ok = sum(1 for i in range(1, len(vals)) if (vals[i] - vals[i - 1]) % 256 == 1)
        if full_ok >= (len(vals) - 1) * 0.9 and len(set(vals)) > 2:
            return {"byte": b, "mod": 256, "nibble": False}
        nib = [v & 0x0F for v in vals]
        nib_ok = sum(1 for i in range(1, len(nib)) if (nib[i] - nib[i - 1]) % 16 == 1)
        if nib_ok >= (len(nib) - 1) * 0.9 and len(set(nib)) > 2:
            return {"byte": b, "mod": 16, "nibble": True}
    return None


def _checksum_algorithms():
    """Common 8-bit automotive checksums as ``name -> f(other_bytes, arb_id)``."""
    return {
        "sum8": lambda other, arb: sum(other) & 0xFF,
        "xor8": lambda other, arb: _xor(other),
        "sum8_id": lambda other, arb: (sum(other) + (arb & 0xFF) + ((arb >> 8) & 0xFF)) & 0xFF,
        "twos_sum8": lambda other, arb: (-sum(other)) & 0xFF,
    }


def _xor(vals: list[int]) -> int:
    acc = 0
    for v in vals:
        acc ^= int(v) & 0xFF
    return acc


def identify_checksum(payloads: list[list[int]], arbitration_id: int,
                      counter_byte: int | None = None) -> dict | None:
    """Find a byte that equals a known checksum of the other bytes on every frame.

    Returns ``{"byte": i, "algorithm": name}`` or None. The checksum is computed
    over all payload bytes except the checksum byte itself (the counter is
    included, since real checksums cover it)."""
    if len(payloads) < 4:
        return None
    width = min((len(p) for p in payloads), default=0)
    algos = _checksum_algorithms()
    for c in range(width):
        if c == counter_byte:
            continue
        # A checksum byte should actually vary; a constant byte is not one.
        if len({int(p[c]) for p in payloads}) < 3:
            continue
        for name, fn in algos.items():
            ok = True
            for p in payloads:
                other = [int(p[i]) for i in range(width) if i != c]
                if fn(other, arbitration_id) != (int(p[c]) & 0xFF):
                    ok = False
                    break
            if ok:
                return {"byte": c, "algorithm": name}
    return None


def detect_multiplexer(payloads: list[list[int]]) -> dict | None:
    """Detect a multiplexer byte: a low-cardinality selector whose value decides
    what the rest of the payload means.

    A multiplexed message reuses the same bytes for different signals depending on
    a selector byte, so a signal that only exists for one selector value gets
    averaged away by a naive search. The tell: a byte with a few recurring values
    where at least one OTHER byte changes only within some of those values and is
    constant in the others. Returns ``{"byte": i, "values": [...], "muxed_bytes":
    [...]}`` or None. Pure."""
    if len(payloads) < 8:
        return None
    width = min((len(p) for p in payloads), default=0)
    best = None
    for b in range(width):
        groups: dict[int, list[list[int]]] = {}
        for p in payloads:
            groups.setdefault(int(p[b]), []).append(p)
        if not (2 <= len(groups) <= 16):
            continue
        if min(len(g) for g in groups.values()) < 2:  # each selector value must recur
            continue
        muxed = []
        for j in range(width):
            if j == b:
                continue
            changes = [len({int(q[j]) for q in g if j < len(q)}) > 1 for g in groups.values()]
            if any(changes) and not all(changes):  # active in some groups, static in others
                muxed.append(j)
        if muxed and (best is None or len(muxed) > len(best["muxed_bytes"])):
            best = {"byte": b, "values": sorted(groups.keys()), "muxed_bytes": muxed}
    return best


def message_protection(payloads: list[list[int]], arbitration_id: int) -> dict:
    """Detect the rolling counter and checksum of a message, if any.

    Returns ``{"counter": {...}|None, "checksum": {...}|None, "protected": bool}``.
    ``protected`` is True if either is present, meaning a plain replay will be
    rejected and frames must be regenerated with a fresh counter and checksum."""
    counter = detect_counter(payloads)
    checksum = identify_checksum(payloads, arbitration_id,
                                 counter_byte=counter["byte"] if counter else None)
    return {"counter": counter, "checksum": checksum,
            "protected": bool(counter or checksum)}


def apply_protection(data: list[int], arbitration_id: int, protection: dict | None,
                     tick: int) -> list[int]:
    """Return a copy of ``data`` with the counter advanced by ``tick`` and the
    checksum recomputed, so a regenerated frame is accepted. A no-op when there
    is no protection. ``tick`` is the frame number in a burst (0, 1, 2, ...)."""
    if not protection:
        return list(data)
    out = [int(b) & 0xFF for b in data]
    counter = protection.get("counter")
    if counter and counter["byte"] < len(out):
        b = counter["byte"]
        if counter.get("nibble"):
            base = out[b] & 0x0F
            out[b] = (out[b] & 0xF0) | ((base + tick) % 16)
        else:
            out[b] = (out[b] + tick) % 256
    checksum = protection.get("checksum")
    if checksum and checksum["byte"] < len(out):
        c = checksum["byte"]
        fn = _checksum_algorithms().get(checksum["algorithm"])
        if fn is not None:
            other = [out[i] for i in range(len(out)) if i != c]
            out[c] = fn(other, arbitration_id) & 0xFF
    return out

def _appearance(times: list[float], events: Sequence[float], window: float) -> int:
    """How many marks the message NEWLY appeared at: absent in ``window`` before
    the mark, present in ``window`` after it.

    This is what separates a real command from a periodic broadcast on a busy bus
    where marks are dense. A message that is on the bus regardless of what you do
    is present just before every mark too, so it never "newly appears" and scores
    zero; a command triggered by the press is absent before and shows up after, so
    it scores once per real press (and not at all at marks where you did nothing).
    Pure. ``times`` must be sorted."""
    if not times or not events:
        return 0

    def present(lo: float, hi: float) -> bool:
        i = bisect.bisect_left(times, lo)
        return i < len(times) and times[i] <= hi

    appear = 0
    for e in events:
        before = present(e - window, e - 1e-6)
        after = present(e, e + window)
        if after and not before:
            appear += 1
    return appear


def event_responders(records: list[dict], event_times: Sequence[float], *,
                     window: float = 0.4, max_results: int = 25) -> list[dict]:
    """Find the CAN message that reacts when a user does an action a few times.

    The intuitive alternative to recording a reference and correlating: capture
    every active bus, have the user operate the control (a button, a switch) and
    mark each time, and rank every ``(channel, arbitration_id)`` by how
    consistently one of its bytes changes right after each mark versus how much
    that byte changes on its own. A message whose byte flips on every press, and
    rarely otherwise, rises to the top.

    ``records`` are frame dicts with optional ``channel``, plus
    ``arbitration_id``, ``data`` (list[int]) and ``timestamp``. ``event_times``
    are the moments the user acted. Returns candidates
    ``{channel, arbitration_id, byte, responded, events, baseline, score}``
    sorted best-first. Pure and offline (a test drives it with synthetic
    frames)."""
    events = sorted(float(t) for t in event_times)
    if not events or not records:
        return []

    groups: dict[tuple, list[dict]] = {}
    for record in records:
        groups.setdefault((record.get("channel"), record.get("arbitration_id")), []).append(record)

    total = len(events)
    results = []
    payloads_by_key: dict[tuple, list[list[int]]] = {}
    for (channel, arb), frames in groups.items():
        frames = sorted(frames, key=lambda f: f.get("timestamp", 0.0))
        times = [float(f.get("timestamp", 0.0)) for f in frames]
        datas = [list(f.get("data") or []) for f in frames]
        if len(frames) < 2:
            continue
        n_bytes = max(len(d) for d in datas)
        payloads_by_key[(channel, arb)] = datas

        # Background change rate per byte: how often it differs frame-to-frame.
        flips = [0] * n_bytes
        for i in range(1, len(datas)):
            prev, cur = datas[i - 1], datas[i]
            for b in range(n_bytes):
                if (prev[b] if b < len(prev) else 0) != (cur[b] if b < len(cur) else 0):
                    flips[b] += 1
        flip_rate = [f / (len(datas) - 1) for f in flips]

        # For each event, which bytes changed within `window` of the mark. Only
        # count a change when the message actually existed just before the mark:
        # a message that is absent and then appears is not a byte "change" (that
        # is the appearance case below), and comparing it against a zero default
        # would otherwise fake a change on its first frame.
        responded = [0] * n_bytes
        for te in events:
            pre_idx = _last_index_before(times, te)
            if pre_idx is None:
                continue
            pre = datas[pre_idx]
            changed = [False] * n_bytes
            i = pre_idx + 1
            while i < len(frames) and times[i] <= te + window:
                cur = datas[i]
                for b in range(n_bytes):
                    if (pre[b] if b < len(pre) else 0) != (cur[b] if b < len(cur) else 0):
                        changed[b] = True
                i += 1
            for b in range(n_bytes):
                if changed[b]:
                    responded[b] += 1

        # Best byte: most event-responsive, discounted by its background noise.
        scored = [(responded[b] / total - flip_rate[b], b) for b in range(n_bytes)]
        best_score, best_byte = max(scored)
        if responded[best_byte] == 0:
            # No byte changed in response, but the message itself may appear only
            # when you act: a command another controller emits on trigger, often
            # with a constant payload (so nothing "changes", it just shows up).
            # The catch is a busy bus is full of periodic broadcasts that appear
            # near every mark too. So only keep a message whose presence CLUSTERS
            # at the marks well above its presence between them: a periodic
            # broadcast cancels out, a real event message stands out.
            appear = _appearance(times, events, window)
            need = max(2, (total + 1) // 2)  # newly appeared at least half the marks
            if appear >= need:
                results.append({
                    "channel": channel, "arbitration_id": arb, "byte": None,
                    "responded": appear, "events": total, "baseline": 0.0,
                    "score": round(appear / total, 3), "kind": "event",
                    "match": "appears", "steady": 0.0,
                    "hint": ("This message shows up right when you act and is absent just "
                             "before, so another controller is likely emitting it as the "
                             "command. Replay it or use Verify effect."),
                })
            continue
        # Status vs command: is this id broadcast steadily the whole time, or
        # does it appear only around your presses? A byte on a steady broadcast
        # that just tracks your press is usually the module reporting a STATUS,
        # not the command that drives the actuator, so replaying it does nothing.
        # A message that shows up only when you act is far more likely to be the
        # command (or a request) itself.
        away = sum(1 for t in times if all(abs(t - e) > window for e in events))
        steady = away / len(times) if times else 0.0
        kind = "status" if steady > 0.5 else "event"
        hint = ("Looks like a status the module broadcasts, not the command. "
                "Replaying it rarely does anything. Often the function is driven "
                "by the module itself and CAN only carries the status, so there "
                "may be no command frame to replay at all."
                if kind == "status" else
                "Appears mainly when you act, so this is more likely the command "
                "itself. Test it, and if nothing happens see the contention and "
                "checksum notes.")
        results.append({
            "channel": channel, "arbitration_id": arb, "byte": best_byte,
            "responded": responded[best_byte], "events": total,
            "baseline": round(flip_rate[best_byte], 3), "score": round(best_score, 3),
            "kind": kind, "steady": round(steady, 3), "hint": hint, "match": "byte",
        })

    # A byte that changes on almost every frame on its own is a data stream or a
    # free-running counter (a VIN or serial broadcast, a rolling counter), not a
    # discrete control. It correlates with any set of presses, so it masquerades
    # as a strong candidate. Drop those, but never return empty just because
    # everything looked noisy: if the filter would clear the list, keep the
    # ranked results so the user still has something to try.
    signal = [r for r in results if r["baseline"] <= STREAM_FLIP_RATE and r["score"] > 0]
    results = signal or results

    results.sort(key=lambda r: (-r["score"], -r["responded"]))
    final = results[:max_results]
    # Detect counter/checksum protection only for the few candidates we return,
    # not every message group: on a CAN-FD bus (64-byte frames) the checksum
    # search is costly, and running it over every id would bog down the analysis.
    for r in final:
        datas = payloads_by_key.get((r["channel"], r["arbitration_id"])) or []
        arb = int(r["arbitration_id"]) if r["arbitration_id"] is not None else 0
        prot = message_protection(datas[:120], arb)
        r["protected"] = prot["protected"]
        r["protection"] = prot
    return final


def _changing_bytes(records: list[dict]) -> set[tuple]:
    """Set of ``(channel, arbitration_id, byte)`` that took more than one value
    across ``records``. Used to compare a bus at rest against the same bus while
    a candidate is being injected. Pure."""
    seen: dict[tuple, set] = {}
    for r in records:
        key0 = (r.get("channel"), r.get("arbitration_id"))
        data = list(r.get("data") or [])
        for b, val in enumerate(data):
            seen.setdefault((key0[0], key0[1], b), set()).add(int(val))
    return {k for k, vals in seen.items() if len(vals) > 1}


def injection_reactors(baseline_records: list[dict], inject_records: list[dict],
                       *, exclude: tuple | None = None) -> list[dict]:
    """Find bytes that started changing only while a candidate was being injected.

    Compares which ``(channel, arbitration_id, byte)`` change on their own
    (``baseline_records``, the bus at rest) against which change while the
    candidate frame is being sent (``inject_records``). A byte that is steady at
    rest but moves during injection is a downstream reaction, which is real
    evidence the injected frame is a command that does something rather than a
    status mirror. ``exclude`` is the injected id itself (``(channel, arb)``), so
    the frame you are sending does not count as its own effect. Pure and offline.
    """
    at_rest = _changing_bytes(baseline_records)
    while_injecting = _changing_bytes(inject_records)
    new = while_injecting - at_rest
    reactors = []
    for channel, arb, byte in new:
        if exclude is not None and (channel, arb) == exclude:
            continue
        reactors.append({"channel": channel, "arbitration_id": arb, "byte": byte})
    reactors.sort(key=lambda r: (str(r["channel"]), r["arbitration_id"], r["byte"]))
    return reactors


def _default_signal_decode(dbc_text: str, arbitration_id: int, data: bytes) -> dict:
    from . import dbc as dbc_mod
    return dbc_mod.decode(dbc_text, arbitration_id, data)


def reference_from_signal(records: list[dict], dbc_text: str, arbitration_id: int,
                          signal: str, decode_fn=None) -> list[dict]:
    """Build a reference series from a KNOWN, decodable signal already in the
    capture (OBD2 speed/RPM, a GPS-to-CAN signal, or a proprietary signal you
    reverse engineered earlier), so an unknown field can be found by how closely
    it tracks it.

    This is the CSS Electronics "CAN-based reference" approach, and the most
    precise option: the reference is machine-accurate, so no manual sweeping or
    button pressing is needed. Returns ``[{t, value, available}]`` sorted by
    time; frames on ``arbitration_id`` that do not decode (or whose signal is not
    numeric) are skipped. Pure over its arguments (a test drives it with a
    stubbed ``decode_fn``)."""
    if not dbc_text or not signal or arbitration_id is None:
        return []
    decode_fn = decode_fn or _default_signal_decode
    out: list[dict] = []
    for record in records:
        if record.get("arbitration_id") != arbitration_id:
            continue
        try:
            decoded = decode_fn(dbc_text, arbitration_id, bytes(record.get("data") or []))
        except Exception:
            continue
        if not isinstance(decoded, dict) or signal not in decoded:
            continue
        try:
            value = float(decoded[signal])
        except (TypeError, ValueError):
            continue
        out.append({"t": float(record.get("timestamp", 0.0)), "value": value, "available": True})
    out.sort(key=lambda point: point["t"])
    return out


def _ranks(values: list[float]) -> list[float]:
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        average_rank = (i + j) / 2 + 1  # 1-based, ties share the mean rank
        for k in range(i, j + 1):
            ranks[order[k]] = average_rank
        i = j + 1
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n == 0:
        return 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0 or var_y == 0:
        return 0.0
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return covariance / math.sqrt(var_x * var_y)


def spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman rank correlation, pure Python (ties get the average rank)."""
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    return _pearson(_ranks(xs), _ranks(ys))


def linear_fit(xs: list[float], ys: list[float]) -> dict:
    """Ordinary least-squares fit ``y = slope * x + intercept``, with R^2."""
    n = len(xs)
    if n < 2 or len(xs) != len(ys):
        return {"slope": 0.0, "intercept": 0.0, "r2": 0.0}
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    if var_x == 0:
        return {"slope": 0.0, "intercept": mean_y, "r2": 0.0}
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = covariance / var_x
    intercept = mean_y - slope * mean_x
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    if ss_tot == 0:
        perfect = all(abs((slope * x + intercept) - y) < 1e-9 for x, y in zip(xs, ys))
        r2 = 1.0 if perfect else 0.0
    else:
        ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
        r2 = 1 - ss_res / ss_tot
    return {"slope": slope, "intercept": intercept, "r2": r2}


# --------------------------------------------------------------------------
# Search: survey ids, then bitsearch within one id
# --------------------------------------------------------------------------

def _n_bits_for(records: list[dict]) -> int:
    if not records:
        return 0
    return max(len(record.get("data") or []) for record in records) * 8


def _search_lengths(n_bits: int, opts: dict) -> list[int]:
    lengths = opts.get("lengths") or DEFAULT_LENGTHS
    return [length for length in lengths if 0 < length <= n_bits]


def _search_start_bits(n_bits: int, opts: dict) -> range:
    if "start_step" in opts:
        return range(0, n_bits, max(1, int(opts["start_step"])))
    # A classic 8-byte frame (64 bits) is cheap to search bit by bit. A
    # CAN-FD frame can be up to 64 bytes (512 bits); step by a nibble there
    # so the search stays fast without missing byte-aligned signals.
    step = 1 if n_bits <= 64 else 4
    return range(0, n_bits, step)


def _fits(byte_order: str, start_bit: int, length: int, n_bits: int) -> bool:
    if byte_order == "little_endian":
        return start_bit + length <= n_bits
    phys_start = 8 * (start_bit // 8) + (7 - start_bit % 8)
    return 0 <= phys_start and phys_start + length <= n_bits


def bitsearch(records_for_id: list[dict], reference: list[dict], opts: dict | None = None) -> list[dict]:
    """Enumerate plausible fields in one id's frames and rank them against a
    reference signal.

    ``opts`` (all optional): ``lengths`` (bit widths to try, default
    :data:`DEFAULT_LENGTHS`), ``byte_orders`` (default both), ``signed``
    (list of bools to try, default both), ``lags`` (candidate time lags
    passed to :func:`resample`), ``min_score`` (drop weaker candidates,
    default 0), ``max_candidates`` (cap the ranked list, default 20),
    ``start_step``/``method`` (advanced tuning).

    Each candidate is ``{arbitration_id, start_bit, length, byte_order,
    signed, scale, offset, r2, correlation, lag}``. Ranked by fit quality
    (the stronger of |correlation| and R^2), and on a tie the shorter field
    wins, since a longer field that happens to score the same usually just
    dragged in a neighboring static or noisy bit.
    """
    opts = opts or {}
    if not records_for_id:
        return []
    # Multiplexed message: search only the frames for one selector value, so a
    # signal that exists only in that mux case is not averaged away by the rest.
    mux = opts.get("mux")
    if isinstance(mux, dict) and mux.get("byte") is not None and mux.get("value") is not None:
        mb, mv = int(mux["byte"]), int(mux["value"])
        records_for_id = [r for r in records_for_id
                          if mb < len(r.get("data") or []) and int(r["data"][mb]) == mv]
        if not records_for_id:
            return []
    arbitration_id = records_for_id[0].get("arbitration_id")
    n_bits = _n_bits_for(records_for_id)
    if n_bits == 0:
        return []

    byte_orders = opts.get("byte_orders") or list(BYTE_ORDERS)
    signed_options = opts.get("signed", [False, True])
    lags = opts.get("lags")
    method = opts.get("method", "nearest")
    min_score = opts.get("min_score", 0.0)
    max_candidates = opts.get("max_candidates", 20)
    lengths = _search_lengths(n_bits, opts)
    start_bits = _search_start_bits(n_bits, opts)

    candidates = []
    for byte_order in byte_orders:
        for length in lengths:
            for start_bit in start_bits:
                if not _fits(byte_order, start_bit, length, n_bits):
                    continue
                for signed in signed_options:
                    series = field_series(records_for_id, {
                        "start_bit": start_bit, "length": length,
                        "byte_order": byte_order, "signed": signed,
                    })
                    if len(series) < 3:
                        continue
                    aligned = resample(series, reference, lags=lags, method=method)
                    xs, ys = aligned["xs"], aligned["ys"]
                    if len(xs) < 3 or len(set(xs)) < 2:
                        continue
                    correlation = spearman(xs, ys)
                    fit = linear_fit(xs, ys)
                    raw_score = max(abs(correlation), fit["r2"])
                    if raw_score < min_score:
                        continue
                    candidates.append((raw_score, length, start_bit, {
                        "arbitration_id": arbitration_id,
                        "start_bit": start_bit,
                        "length": length,
                        "byte_order": byte_order,
                        "signed": signed,
                        "scale": fit["slope"],
                        "offset": fit["intercept"],
                        "r2": round(fit["r2"], 6),
                        "correlation": round(correlation, 6),
                        "lag": aligned["lag"],
                        "score": round(raw_score, 6),
                    }))

    # Sort on the un-rounded score first: two candidates that are only
    # different in, say, the fifth decimal place both round the same way for
    # display, but that tiny gap is exactly what separates the true field
    # from a neighboring one that dragged in a stray bit, so the shorter-field
    # tiebreak below must not be reached before that real difference is
    # honored.
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    return [c[3] for c in candidates[:max_candidates]]


def survey(records_by_id: dict[int, list[dict]], reference: list[dict], opts: dict | None = None) -> list[dict]:
    """Coarse per-byte scan across every arbitration id, ranked by how well
    any one byte correlates with the reference, so a bitsearch only needs to
    run on the promising ids.
    """
    opts = opts or {}
    lags = opts.get("lags")
    method = opts.get("method", "nearest")
    results = []
    for arbitration_id, records in records_by_id.items():
        if not records:
            continue
        n_bytes = max(len(record.get("data") or []) for record in records)
        best_score = 0.0
        best_byte = None
        for byte_index in range(n_bytes):
            series = field_series(records, {"start_bit": byte_index * 8, "length": 8,
                                            "byte_order": "little_endian", "signed": False})
            if len(series) < 3:
                continue
            aligned = resample(series, reference, lags=lags, method=method)
            xs, ys = aligned["xs"], aligned["ys"]
            if len(xs) < 3 or len(set(xs)) < 2:
                continue
            score = max(abs(spearman(xs, ys)), linear_fit(xs, ys)["r2"])
            if score > best_score:
                best_score = score
                best_byte = byte_index
        results.append({
            "arbitration_id": arbitration_id,
            "score": round(best_score, 4),
            "best_byte": best_byte,
            "frame_count": len(records),
        })
    results.sort(key=lambda r: -r["score"])
    return results


def auto_decode(records_by_id: dict[int, list[dict]], reference: list[dict],
                opts: dict | None = None) -> list[dict]:
    """Find the best decode for a reference across a whole capture, in one pass.

    The iteration a technician does by hand: survey to rank ids, bit-search the
    most promising ones (the search already tries both byte orders and signs),
    and for a multiplexed message search each selector value too, then rank every
    candidate by fit. Returns the ranked, de-duplicated candidate list (each is a
    normal bitsearch candidate, plus a ``mux`` key when it came from one selector
    value). Pure; the LLM naming is layered on at the router."""
    opts = opts or {}
    top_ids = max(1, int(opts.get("top_ids", 3)))
    per_id = max(1, int(opts.get("per_id", 3)))
    ranked = [r for r in survey(records_by_id, reference, opts) if r.get("score", 0) > 0][:top_ids]
    out: list[dict] = []
    for row in ranked:
        arb = row["arbitration_id"]
        recs = records_by_id.get(arb) or []
        out.extend(bitsearch(recs, reference, opts)[:per_id])
        mux = detect_multiplexer([list(r.get("data") or []) for r in recs[:400]])
        if mux:
            for v in mux["values"][:8]:
                mopts = dict(opts)
                mopts["mux"] = {"byte": mux["byte"], "value": v}
                for c in bitsearch(recs, reference, mopts)[:2]:
                    c = dict(c)
                    c["mux"] = {"byte": mux["byte"], "value": v}
                    out.append(c)
    out.sort(key=lambda c: -(c.get("r2") or 0))
    seen: set = set()
    deduped: list[dict] = []
    for c in out:
        key = (c.get("arbitration_id"), c.get("start_bit"), c.get("length"),
               c.get("byte_order"), c.get("signed"), str(c.get("mux")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    return deduped[:int(opts.get("max_candidates", 10))]


def cross_correlate(records_by_id: dict[int, list[dict]], dbc_text: str,
                    known_signals: Sequence[dict], *, min_score: float = 0.9,
                    max_signals: int = 40, max_matches: int = 25, decode_fn=None) -> list[dict]:
    """Automatically find, for each signal a database already decodes, an unknown
    field elsewhere on the bus that tracks it, with no human input.

    For every known signal, decode it into a reference (``reference_from_signal``)
    and survey/bitsearch the *other* ids for a field that moves with it. A strong
    match means the proprietary bus carries a redundant (often higher-resolution)
    copy of that signal, e.g. a 16-bit wheel speed mirroring a coarser known one.

    ``known_signals`` are ``{arbitration_id, signal}`` dicts. Returns matches
    ``{known_signal, known_id, match_id, resolution_bits, candidate, score}``
    sorted strongest first. Pure over its arguments (a test drives it with a
    stubbed ``decode_fn``); reuses the same statistics as the manual flow."""
    matches: list[dict] = []
    for known in list(known_signals)[:max_signals]:
        arb = known.get("arbitration_id")
        signal = known.get("signal")
        reference = reference_from_signal(records_by_id.get(arb, []), dbc_text, arb, signal, decode_fn=decode_fn)
        if len(reference) < 5:
            continue
        # Constant references cannot be matched against anything.
        values = {round(p["value"], 6) for p in reference}
        if len(values) < 2:
            continue
        others = {aid: recs for aid, recs in records_by_id.items() if aid != arb}
        for entry in survey(others, reference, {})[:3]:
            if entry["score"] < min_score:
                break
            candidates = bitsearch(others[entry["arbitration_id"]], reference,
                                   {"min_score": min_score, "max_candidates": 1})
            if not candidates or candidates[0]["score"] < min_score:
                continue
            candidate = candidates[0]
            matches.append({
                "known_signal": signal, "known_id": arb,
                "match_id": entry["arbitration_id"],
                "resolution_bits": candidate["length"],
                "candidate": candidate, "score": candidate["score"],
            })
            break  # one best match per known signal
    matches.sort(key=lambda m: -m["score"])
    return matches[:max_matches]


# --------------------------------------------------------------------------
# Scale/offset derivation and DBC export
# --------------------------------------------------------------------------

def derive_scale_offset(candidate: dict, reference: list[dict] | None = None) -> dict:
    """Round a fitted slope to an OEM-realistic scale when it is close, and
    snap a near-zero intercept to exactly zero.

    ``reference`` is accepted but not required today: it is there so a
    future refinement (checking the fit against a known anchor point, e.g.
    "0 shown on the dash should decode to 0") has somewhere to look without
    changing the call signature everywhere else in the pipeline.
    """
    slope = candidate.get("scale", 1.0)
    intercept = candidate.get("offset", 0.0)

    best_scale = slope
    best_diff = None
    for nice in NICE_SCALES:
        if nice == 0:
            continue
        diff = abs(slope - nice)
        relative = diff / abs(nice)
        if relative < 0.05 and (best_diff is None or diff < best_diff):
            best_scale = nice
            best_diff = diff

    rounded_offset = round(intercept, 3)
    if abs(rounded_offset) < 0.05:
        rounded_offset = 0.0

    out = dict(candidate)
    out["scale"] = best_scale
    out["offset"] = rounded_offset
    return out


def to_dbc_signal(name: str, candidate: dict, *, unit: str = "", comment: str = "") -> dict:
    """Turn a ranked candidate into a decode definition shaped like
    :func:`app.can.dbc._signal_to_definition`, ready for
    :func:`add_signal_to_database`."""
    return {
        "name": name,
        "start": candidate["start_bit"],
        "length": candidate["length"],
        "byte_order": candidate.get("byte_order", "little_endian"),
        "is_signed": bool(candidate.get("signed", False)),
        "scale": candidate.get("scale", 1),
        "offset": candidate.get("offset", 0),
        "minimum": candidate.get("minimum"),
        "maximum": candidate.get("maximum"),
        "unit": unit,
        "is_float": False,
        "choices": {},
        "comment": comment,
        "receivers": [],
        "is_multiplexer": False,
        "multiplexer_ids": [],
    }


def _load_cantools_database(dbc_text: str):
    import cantools
    from cantools.database.can.database import Database as CanToolsDatabase
    if dbc_text and dbc_text.strip():
        try:
            return cantools.database.load_string(dbc_text, database_format="dbc")
        except Exception:
            return cantools.database.load_string(dbc_text, database_format="dbc", strict=False)
    return CanToolsDatabase()


def add_signal_to_database(session, database, arbitration_id: int, signal_name: str,
                            definition: dict, *, message_name: str | None = None,
                            frame_length: int = 8):
    """Add (or replace) one signal on an existing (or brand-new) message in a
    :class:`~app.db.models.CanDatabase`, regenerating its ``dbc_text`` through
    cantools so decode/encode keep working exactly as they do for any other
    imported DBC.

    ``database`` is the ``CanDatabase`` ORM row (already attached to
    ``session``); its ``dbc_text`` is replaced in place. The matching
    ``CanMessage``/``CanSignal`` rows are created or updated to match, so the
    message/signal list view stays in sync without a full re-import.
    """
    from cantools.database.can import Message, Signal
    from cantools.database.conversion import BaseConversion
    from . import dbc as dbc_mod
    from ..db.models import CanMessage, CanSignal

    cantools_db = _load_cantools_database(database.dbc_text)
    existing = None
    for message in cantools_db.messages:
        if message.frame_id == arbitration_id:
            existing = message
            break

    conversion = BaseConversion.factory(
        scale=definition.get("scale", 1) or 1,
        offset=definition.get("offset", 0) or 0,
    )
    new_signal = Signal(
        name=signal_name,
        start=definition["start"],
        length=definition["length"],
        byte_order=definition.get("byte_order", "little_endian"),
        is_signed=bool(definition.get("is_signed", False)),
        conversion=conversion,
        minimum=definition.get("minimum"),
        maximum=definition.get("maximum"),
        unit=definition.get("unit") or "",
        comment=definition.get("comment") or "",
    )

    if existing is not None:
        signals = [s for s in existing.signals if s.name != signal_name] + [new_signal]
        new_message = Message(
            frame_id=existing.frame_id,
            name=existing.name,
            length=existing.length,
            signals=signals,
            is_extended_frame=existing.is_extended_frame,
            is_fd=existing.is_fd,
            comment=existing.comment,
            senders=list(existing.senders or []),
            strict=False,
        )
        final_name = existing.name
        final_is_fd = bool(existing.is_fd)
        other_messages = [m for m in cantools_db.messages if m.frame_id != arbitration_id]
    else:
        final_name = message_name or f"MSG_{arbitration_id:X}"
        new_message = Message(
            frame_id=arbitration_id,
            name=final_name,
            length=frame_length,
            signals=[new_signal],
            strict=False,
        )
        final_is_fd = False
        other_messages = list(cantools_db.messages)

    from cantools.database.can.database import Database as CanToolsDatabase
    rebuilt = CanToolsDatabase(
        messages=other_messages + [new_message],
        nodes=cantools_db.nodes,
        version=cantools_db.version,
        strict=False,
    )
    database.dbc_text = rebuilt.as_dbc_string()

    message_row = (
        session.query(CanMessage)
        .filter_by(database_id=database.id, arbitration_id=arbitration_id)
        .one_or_none()
    )
    if message_row is None:
        message_row = CanMessage(database_id=database.id, arbitration_id=arbitration_id,
                                  name=final_name, is_fd=final_is_fd)
        session.add(message_row)
        session.flush()

    stored_definition = dbc_mod._signal_to_definition(new_signal)
    signal_row = (
        session.query(CanSignal)
        .filter_by(message_id=message_row.id, name=signal_name)
        .one_or_none()
    )
    if signal_row is None:
        session.add(CanSignal(message_id=message_row.id, name=signal_name, definition=stored_definition))
    else:
        signal_row.definition = stored_definition
    session.flush()
    return database
