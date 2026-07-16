"""Read a dashboard value, preferring a fast local OCR pass over the vision LLM.

Reading a number does not need a vision model in the common case, so this tries
local OCR first and only falls back to the LLM when OCR is unsure or unavailable.
That makes reads fast and free where it can, keeps the robust model read for the
hard displays (odd fonts, glare, analog needles), and lets the whole flow work
offline with no AI provider when the reader is set to local.

``reader``:
  - ``"auto"``  (default): OCR first; fall back to the LLM when OCR is unsure.
  - ``"local"``: OCR only; never call the LLM (works with no provider).
  - ``"ai"``:    the vision LLM only (the original behavior).
"""
from __future__ import annotations

from typing import Any

from .. import llm
from . import ocr

READERS = ("auto", "local", "ai")


def read(image_b64: str, mime: str, what: str, reader: str = "auto") -> dict[str, Any]:
    """Read one number from an image. Returns ``{"value": float|None,
    "engine": "ocr"|"ai"|None, "confidence": float}``. Raises the LLM's
    ``RuntimeError`` only when it actually falls back to the model and the model
    is not ready, so the local path never needs a provider configured."""
    reader = reader if reader in READERS else "auto"

    if reader in ("auto", "local"):
        got = ocr.read_number(image_b64, mime)
        if got.get("value") is not None and got.get("confidence", 0.0) >= ocr.MIN_CONFIDENCE:
            return {"value": float(got["value"]), "engine": "ocr",
                    "confidence": got.get("confidence", 0.0)}
        if reader == "local":
            # OCR is the only reader allowed; report the miss without touching the LLM.
            return {"value": None, "engine": "ocr", "confidence": got.get("confidence", 0.0)}

    reading = llm.read_dashboard_value(image_b64, mime, what)
    value = reading.get("value")
    return {"value": None if value is None else float(value), "engine": "ai", "confidence": 0.0}
