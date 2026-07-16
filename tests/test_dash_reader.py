"""The combined dashboard reader (:mod:`app.services.dash_reader`): OCR first,
the vision LLM as fallback, and the per-mode behaviour, with both backends
monkeypatched so no binary or provider is needed."""
from __future__ import annotations

import pytest

from app.services import dash_reader
from app.services import ocr


def _ocr(value, confidence):
    return lambda image_b64, mime="image/jpeg": {
        "value": value, "confidence": confidence, "text": "", "engine": "ocr"}


def test_auto_uses_ocr_when_confident(monkeypatch):
    monkeypatch.setattr(ocr, "read_number", _ocr(42.0, 90.0))
    monkeypatch.setattr(dash_reader.llm, "read_dashboard_value",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call the LLM")))
    out = dash_reader.read("img", "image/jpeg", "speed", "auto")
    assert out["value"] == 42.0 and out["engine"] == "ocr"


def test_auto_falls_back_to_ai_when_ocr_unsure(monkeypatch):
    monkeypatch.setattr(ocr, "read_number", _ocr(42.0, 10.0))   # below MIN_CONFIDENCE
    monkeypatch.setattr(dash_reader.llm, "read_dashboard_value", lambda *a, **k: {"value": 55.0})
    out = dash_reader.read("img", "image/jpeg", "speed", "auto")
    assert out["value"] == 55.0 and out["engine"] == "ai"


def test_auto_falls_back_when_ocr_finds_nothing(monkeypatch):
    monkeypatch.setattr(ocr, "read_number", _ocr(None, 0.0))
    monkeypatch.setattr(dash_reader.llm, "read_dashboard_value", lambda *a, **k: {"value": 7.0})
    out = dash_reader.read("img", "image/jpeg", "speed", "auto")
    assert out["value"] == 7.0 and out["engine"] == "ai"


def test_local_never_calls_the_llm(monkeypatch):
    monkeypatch.setattr(ocr, "read_number", _ocr(None, 0.0))
    monkeypatch.setattr(dash_reader.llm, "read_dashboard_value",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("local must not call the LLM")))
    out = dash_reader.read("img", "image/jpeg", "speed", "local")
    assert out["value"] is None and out["engine"] == "ocr"


def test_ai_mode_skips_ocr(monkeypatch):
    monkeypatch.setattr(ocr, "read_number",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("ai mode must not run OCR")))
    monkeypatch.setattr(dash_reader.llm, "read_dashboard_value", lambda *a, **k: {"value": 99.0})
    out = dash_reader.read("img", "image/jpeg", "speed", "ai")
    assert out["value"] == 99.0 and out["engine"] == "ai"


def test_unknown_reader_defaults_to_auto(monkeypatch):
    monkeypatch.setattr(ocr, "read_number", _ocr(12.0, 99.0))
    out = dash_reader.read("img", "image/jpeg", "speed", "banana")
    assert out["value"] == 12.0 and out["engine"] == "ocr"
