"""Pure-logic tests for the optional LLM assist (app/llm.py).

The network call is never exercised here; only the context builders, the JSON
parser, and the no-key/degradation path, so the suite stays offline and cheap.
"""
from __future__ import annotations

import pytest

from app import llm
from app.config import settings


@pytest.fixture(autouse=True)
def _clear_llm_settings(monkeypatch):
    """Every test starts from the default provider (gemini), no key."""
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "llm_model", "")
    monkeypatch.setattr(settings, "llm_base_url", "")


def test_default_provider_is_gemini():
    assert llm._provider() == "gemini"
    assert llm.PROVIDERS[0] == "gemini"


def test_status_no_key_reports_unavailable():
    st = llm.status()
    assert st["available"] is False
    assert st["provider"] == "gemini"
    assert "key" in st["reason"].lower()
    assert st["model"] == llm.DEFAULT_MODELS["gemini"]


def test_status_unknown_provider():
    settings.llm_provider = "cohere"
    st = llm.status()
    assert st["available"] is False
    assert "provider" in st["reason"].lower()


def test_ollama_is_available_without_a_key():
    settings.llm_provider = "ollama"
    st = llm.status()
    assert st["available"] is True
    assert st["model"] == llm.DEFAULT_MODELS["ollama"]


def test_model_default_is_per_provider_then_overridable():
    assert llm._model() == llm.DEFAULT_MODELS["gemini"]
    settings.llm_provider = "anthropic"
    assert llm._model() == llm.DEFAULT_MODELS["anthropic"]
    settings.llm_model = "claude-haiku-4-5"
    assert llm._model() == "claude-haiku-4-5"


def test_every_provider_has_a_default_model_and_caller():
    for provider in llm.PROVIDERS:
        assert provider in llm.DEFAULT_MODELS
        assert provider in llm._CALLERS


def test_interpret_without_key_raises_runtime_error():
    with pytest.raises(RuntimeError):
        llm._ask_json("sys", "user")


def test_describe_message_includes_id_bytes_and_samples():
    activity = {
        "arbitration_id": 0x1F0,
        "length": 3,
        "frame_count": 4,
        "bytes": [
            {"index": 0, "classification": "counter", "min": 0, "max": 255, "unique_values": 200},
            {"index": 1, "classification": "static", "min": 5, "max": 5, "unique_values": 1},
            {"index": 2, "classification": "candidate", "min": 0, "max": 90, "unique_values": 30},
        ],
    }
    samples = [{"data": [1, 5, 10]}, {"data": [2, 5, 20]}, {"data": [255, 5, 90]}]
    text = llm.describe_message(activity, samples)
    assert "0x1F0" in text
    assert "counter" in text and "candidate" in text
    # Bytes rendered as two-hex-digit, masked to a byte.
    assert "FF 05 5A" in text


def test_describe_message_caps_samples():
    activity = {"arbitration_id": 1, "length": 1, "frame_count": 50, "bytes": []}
    samples = [{"data": [i & 0xFF]} for i in range(50)]
    text = llm.describe_message(activity, samples, max_samples=3)
    # Only 3 sample rows, so at most 3 lines under "Sample frames".
    body = text.split("Sample frames (hex bytes):")[1]
    assert len([ln for ln in body.splitlines() if ln.strip()]) == 3


def test_describe_candidate_mentions_byte_order_and_hint():
    cand = {
        "arbitration_id": 0x200, "start_bit": 8, "length": 16,
        "byte_order": "big_endian", "signed": True,
        "scale": 0.01, "offset": 0.0, "r2": 0.99, "correlation": 0.98,
    }
    text = llm.describe_candidate(cand, "turning the volume knob up")
    assert "0x200" in text
    assert "Motorola" in text
    assert "volume knob" in text


def test_parse_json_response_plain_and_fenced():
    assert llm.parse_json_response('{"name": "SPEED"}') == {"name": "SPEED"}
    fenced = "```json\n{\"unit\": \"km/h\"}\n```"
    assert llm.parse_json_response(fenced) == {"unit": "km/h"}


def test_parse_json_response_rejects_non_object_and_garbage():
    assert llm.parse_json_response("not json") == {}
    assert llm.parse_json_response("[1, 2, 3]") == {}
    assert llm.parse_json_response("") == {}
