"""Crop a camera frame to a region of interest before the vision AI reads it.

A dashboard often shows several numbers at once (speed, RPM, gear, coolant), and
the AI can latch onto the wrong one, so the reference it records tracks something
other than what the user meant. Letting the user box just the value they care
about, and cropping the frame to that box before the read, removes the other
numbers from view.

The region is given as fractions of the frame (``{x, y, w, h}`` in 0..1, with
``x``/``y`` the top-left corner) so it is independent of the camera's resolution:
the browser measures the box against the preview it shows, the server maps it onto
whatever pixels the frame actually has.

Everything fails open: a missing, malformed, or tiny region, or a Pillow that is
not installed, returns the frame unchanged so a bad box never blocks a reading.
"""
from __future__ import annotations

import base64
import io


def _clamp01(value: float) -> float:
    return 0.0 if value < 0 else 1.0 if value > 1 else value


def _region(roi: dict | None) -> tuple[float, float, float, float] | None:
    """Validated (x, y, w, h) fractions, or None when there is no usable box."""
    if not isinstance(roi, dict):
        return None
    try:
        x = _clamp01(float(roi.get("x", 0.0)))
        y = _clamp01(float(roi.get("y", 0.0)))
        w = float(roi.get("w", 0.0))
        h = float(roi.get("h", 0.0))
    except (TypeError, ValueError):
        return None
    # A box smaller than 2% of the frame in either axis is almost certainly a
    # stray click, not a selection; read the whole frame instead.
    if w <= 0.02 or h <= 0.02:
        return None
    # Keep the box inside the frame.
    w = min(w, 1.0 - x)
    h = min(h, 1.0 - y)
    if w <= 0.02 or h <= 0.02:
        return None
    return x, y, w, h


def crop_region(image_b64: str, mime: str, roi: dict | None) -> tuple[str, str]:
    """Crop a base64 image to ``roi`` and return ``(image_b64, mime)`` re-encoded
    as JPEG. Returns the input unchanged when there is no usable region or Pillow
    is unavailable."""
    region = _region(roi)
    if region is None or not image_b64:
        return image_b64, mime
    try:
        from PIL import Image
    except Exception:
        return image_b64, mime
    try:
        raw = base64.b64decode(image_b64)
        img = Image.open(io.BytesIO(raw))
        width, height = img.size
        x, y, w, h = region
        left = int(round(x * width))
        top = int(round(y * height))
        right = min(width, int(round((x + w) * width)))
        bottom = min(height, int(round((y + h) * height)))
        if right - left < 2 or bottom - top < 2:
            return image_b64, mime
        cropped = img.crop((left, top, right, bottom)).convert("RGB")
        buf = io.BytesIO()
        cropped.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"
    except Exception:
        # A corrupt frame or an encoder hiccup must never stop a reading.
        return image_b64, mime
