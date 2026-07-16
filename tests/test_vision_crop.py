"""Cropping a camera frame to a region of interest before the vision read
(:mod:`app.services.vision_crop`). Pure and fail-open: a bad or missing region
returns the frame unchanged so a stray box never blocks a reading."""
from __future__ import annotations

import base64
import io

import pytest

from app.services import vision_crop as vc

Image = pytest.importorskip("PIL.Image")


def _jpeg(width: int, height: int) -> str:
    img = Image.new("RGB", (width, height), (10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _size(image_b64: str) -> tuple[int, int]:
    return Image.open(io.BytesIO(base64.b64decode(image_b64))).size


def test_crop_region_reduces_to_the_boxed_area():
    src = _jpeg(400, 200)
    out, mime = vc.crop_region(src, "image/jpeg", {"x": 0.25, "y": 0.5, "w": 0.5, "h": 0.25})
    assert mime == "image/jpeg"
    w, h = _size(out)
    # 50% of 400 wide, 25% of 200 tall, within a rounding pixel.
    assert abs(w - 200) <= 2 and abs(h - 50) <= 2


def test_crop_region_clamps_a_box_that_runs_past_the_edge():
    src = _jpeg(400, 200)
    out, _ = vc.crop_region(src, "image/jpeg", {"x": 0.8, "y": 0.8, "w": 0.5, "h": 0.5})
    w, h = _size(out)
    assert abs(w - 80) <= 2 and abs(h - 40) <= 2  # clamped to the remaining 20%


@pytest.mark.parametrize("roi", [
    None, {}, {"x": 0, "y": 0, "w": 0, "h": 0}, {"x": 0.1, "y": 0.1, "w": 0.01, "h": 0.5},
    {"x": "bad", "y": 0, "w": 0.5, "h": 0.5}, {"w": 1.0, "h": 1.0},
])
def test_crop_region_passes_frame_through_when_there_is_no_usable_box(roi):
    src = _jpeg(320, 240)
    out, mime = vc.crop_region(src, "image/jpeg", roi)
    # A full-frame or degenerate box returns something the same size (no crop).
    w, h = _size(out)
    assert (w, h) == (320, 240)


def test_crop_region_survives_a_non_image_payload():
    out, mime = vc.crop_region("not-base64-or-image", "image/jpeg", {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5})
    assert out == "not-base64-or-image"  # fail-open, never raises
