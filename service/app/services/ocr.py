"""Read a number off a cropped dashboard image locally, with no LLM round-trip.

Reading a plain numeric readout (speed, RPM, a gauge value) does not need a
vision model: on a clean, cropped number a local OCR pass is far faster (tens of
milliseconds against a couple of seconds), free, and works with no internet. The
speed matters twice over, because a faster read means many more reference points
land in the same recording, which is what the correlation actually needs.

This is best on a clear digital or seven-segment readout. A graphical cluster
with an odd font, glare, or an analog needle is where a vision model still does
better, so the caller uses this first and falls back to the LLM (see
:mod:`app.services.dash_reader`).

Everything degrades gracefully: with Tesseract not installed, :func:`read_number`
reports itself unavailable and the caller falls back. The number-picking and text
parsing are pure so they stay testable without the binary.
"""
from __future__ import annotations

import base64
import io
import re

# A reading is only trusted above this OCR confidence (0..100); below it the
# caller falls back to the vision model rather than record a bad number.
MIN_CONFIDENCE = 55.0

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def available() -> bool:
    """Whether a local OCR read can run here (Tesseract and its wrapper present)."""
    try:
        import pytesseract  # noqa: F401
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def parse_number(text: str) -> float | None:
    """The first number in a piece of OCR text, or None. Pure. Collapses stray
    spaces Tesseract puts between digits, and ignores a lone decimal point."""
    if not text:
        return None
    cleaned = re.sub(r"(?<=\d)\s+(?=\d)", "", text.replace(",", ""))
    match = _NUMBER_RE.search(cleaned)
    if not match:
        return None
    token = match.group(0).rstrip(".")
    try:
        return float(token)
    except ValueError:
        return None


def pick_number(texts, confidences) -> tuple[float | None, float]:
    """From Tesseract's per-token text and confidence lists, return the best
    numeric value and its confidence. Pure so it is testable without the binary.

    Joins the numeric tokens (a value split across boxes like ``2`` ``1`` becomes
    ``21``) and averages the confidence of the tokens that contributed."""
    joined = []
    confs = []
    for text, conf in zip(texts, confidences):
        token = (text or "").strip()
        if not token:
            continue
        try:
            c = float(conf)
        except (TypeError, ValueError):
            c = -1.0
        if c < 0:
            continue
        if re.fullmatch(r"[\d.]+", token):
            joined.append(token)
            confs.append(c)
    value = parse_number(" ".join(joined))
    confidence = (sum(confs) / len(confs)) if confs else 0.0
    return value, confidence


def _preprocess(img):
    """Grayscale, upscale, and high-contrast a crop so Tesseract reads glowing
    cluster digits (usually light on dark) as clean dark-on-light text."""
    from PIL import Image, ImageOps
    gray = ImageOps.grayscale(img)
    width, height = gray.size
    # Tesseract wants characters a few dozen pixels tall; a tight crop is often
    # smaller, so scale it up.
    if height and height < 90:
        scale = min(4, max(2, 90 // height))
        gray = gray.resize((width * scale, height * scale), Image.LANCZOS)
    gray = ImageOps.autocontrast(gray)
    # A cluster shows bright digits on a dark face; OCR wants the opposite. Invert
    # when the image is mostly dark so digits end up dark on a light ground.
    hist = gray.histogram()
    dark = sum(hist[:128])
    light = sum(hist[128:])
    if dark > light:
        gray = ImageOps.invert(gray)
    return gray


def read_number(image_b64: str, mime: str = "image/jpeg") -> dict:
    """Read a single number from a base64 image with local OCR.

    Returns ``{"value": float|None, "confidence": float, "text": str,
    "engine": "ocr"}``. ``value`` is None (and confidence 0) when Tesseract is not
    installed, the image cannot be read, or nothing numeric is found, so the
    caller can fall back to the vision model."""
    result = {"value": None, "confidence": 0.0, "text": "", "engine": "ocr"}
    if not image_b64:
        return result
    try:
        import pytesseract
        from PIL import Image
    except Exception:
        return result
    try:
        raw = base64.b64decode(image_b64)
        img = Image.open(io.BytesIO(raw))
        proc = _preprocess(img)
        # psm 7: treat the crop as a single text line; whitelist digits and a dot.
        config = "--psm 7 -c tessedit_char_whitelist=0123456789."
        data = pytesseract.image_to_data(proc, config=config,
                                          output_type=pytesseract.Output.DICT)
        value, confidence = pick_number(data.get("text", []), data.get("conf", []))
        text = " ".join(t for t in data.get("text", []) if (t or "").strip())
        return {"value": value, "confidence": confidence, "text": text, "engine": "ocr"}
    except Exception:
        return result
