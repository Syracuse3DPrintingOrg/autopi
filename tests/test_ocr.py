"""Local OCR number reading (:mod:`app.services.ocr`). The Tesseract call itself
needs the binary, so the tests cover the pure text/number picking and the
fail-open behaviour when Tesseract is absent."""
from __future__ import annotations

import pytest

from app.services import ocr


@pytest.mark.parametrize("text,expected", [
    ("21", 21.0),
    ("  85 ", 85.0),
    ("3.5", 3.5),
    ("1 2 3", 123.0),        # Tesseract sometimes spaces digits apart
    ("2\n1", 21.0),
    ("rpm 3200", 3200.0),
    ("", None),
    (".", None),
    ("no digits", None),
    ("12.", 12.0),           # trailing dot dropped
])
def test_parse_number(text, expected):
    assert ocr.parse_number(text) == expected


def test_pick_number_joins_digit_boxes_and_averages_confidence():
    texts = ["2", "1", "", "km/h"]
    confs = [95, 90, -1, 40]      # -1 is Tesseract's "no text" marker; km/h is not numeric
    value, confidence = ocr.pick_number(texts, confs)
    assert value == 21.0
    assert confidence == pytest.approx(92.5)


def test_pick_number_ignores_non_numeric_tokens():
    value, confidence = ocr.pick_number(["Speed", "MPH"], [88, 88])
    assert value is None
    assert confidence == 0.0


def test_read_number_fails_open_without_tesseract(monkeypatch):
    # Simulate Tesseract/pytesseract not installed: read_number must not raise and
    # must report no value so the caller falls back to the vision AI.
    import builtins
    real_import = builtins.__import__

    def no_pytesseract(name, *a, **k):
        if name == "pytesseract":
            raise ImportError("no pytesseract")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_pytesseract)
    got = ocr.read_number("Zm9v", "image/jpeg")
    assert got == {"value": None, "confidence": 0.0, "text": "", "engine": "ocr"}


def test_read_number_empty_input():
    assert ocr.read_number("", "image/jpeg")["value"] is None
