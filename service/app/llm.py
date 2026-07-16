"""Optional LLM assist for the Signal Finder, multi-provider.

The Signal Finder works purely on statistics: it never needs a network or an
API key. This module is the optional layer on top that asks a hosted (or local)
LLM to make reverse engineering easier, mirroring the "let an LLM name the
signals" idea from CSS Electronics' AI CAN reverse-engineering write-up:

- interpret which real quantity a message's active bytes probably carry, and
- propose a name, unit, and description for a candidate the search turned up.

Several providers are supported. Google **Gemini** is the default; Anthropic
Claude, OpenAI, and a local Ollama server are also available, chosen from the
AI Assist settings section. Every provider is reached over plain HTTPS with the
``httpx`` the app already ships, so a Raspberry Pi appliance needs no extra
vendor SDKs.

Everything degrades gracefully. With no key configured (or, for Ollama, no
server), every entry point returns ``{"available": False, "reason": ...}`` and
the rest of the Signal Finder is unaffected. The context-building and
response-parsing helpers are pure so they stay testable without the network.
"""
from __future__ import annotations

import json
from typing import Any

from .config import settings

# Provider -> default model when the user leaves the model field blank.
DEFAULT_MODELS = {
    "gemini": "gemini-2.0-flash",
    "anthropic": "claude-opus-4-8",
    "openai": "gpt-4o-mini",
    "ollama": "llama3.1",
}

# Providers the settings UI offers, Gemini first (the default).
PROVIDERS = ("gemini", "anthropic", "openai", "ollama")

# Ollama runs locally with no key; every other provider needs an API key.
_KEYLESS = {"ollama"}

_DEFAULT_OLLAMA_BASE = "http://localhost:11434"

_INTERPRET_SYSTEM = (
    "You are a vehicle CAN bus reverse-engineering assistant helping a bench "
    "technician. Given a raw activity summary of one CAN message (arbitration "
    "id, per-byte behavior, and a few decoded sample frames), infer what real "
    "quantity the message most likely carries and what each changing byte "
    "probably represents. Ground every guess in the data you are shown. Be "
    "concrete but honest about uncertainty; never invent a DBC you were not "
    "given. Keep guesses short."
)

_NAME_SYSTEM = (
    "You are a vehicle CAN bus reverse-engineering assistant. Given a signal "
    "candidate a statistical search found (bit position, length, byte order, "
    "fitted scale/offset, correlation quality) and what the technician was "
    "doing when they recorded the reference, propose a concise UPPER_SNAKE_CASE "
    "signal name, a plausible SI-ish unit, and a one-line description. Judge "
    "whether the fit is actually plausible for that quantity and say why. Keep "
    "it terse."
)

_INTERPRET_SHAPE = (
    'Respond with ONLY a JSON object, no prose and no markdown fences: '
    '{"message_guess": string, "fields": [{"bytes": string, "guess": string, '
    '"confidence": "low"|"medium"|"high"}], "notes": string}.'
)

_NAME_SHAPE = (
    'Respond with ONLY a JSON object, no prose and no markdown fences: '
    '{"name": string in UPPER_SNAKE_CASE, "unit": string, "description": string, '
    '"plausible": boolean, "reason": string}.'
)


def _provider() -> str:
    return (getattr(settings, "llm_provider", "") or "gemini").strip().lower()


def _model() -> str:
    explicit = (getattr(settings, "llm_model", "") or "").strip()
    if explicit:
        return explicit
    return DEFAULT_MODELS.get(_provider(), "")


def _api_key() -> str:
    return (getattr(settings, "llm_api_key", "") or "").strip()


def _base_url() -> str:
    return (getattr(settings, "llm_base_url", "") or "").strip()


def status() -> dict[str, Any]:
    """Whether the LLM assist can run, and why not if it cannot. Safe to call
    from any surface (a template flag, a UI gate) without side effects."""
    provider = _provider()
    if provider not in PROVIDERS:
        return {"available": False, "provider": provider, "model": _model(),
                "reason": f"Unknown AI provider {provider!r}. Pick one in Settings, AI Assist."}
    try:
        import httpx  # noqa: F401
    except Exception:
        return {"available": False, "provider": provider, "model": _model(),
                "reason": "The 'httpx' package is not installed on this device."}
    if provider not in _KEYLESS and not _api_key():
        return {"available": False, "provider": provider, "model": _model(),
                "reason": "No API key set. Add one in Settings under AI assist."}
    return {"available": True, "provider": provider, "model": _model(), "reason": ""}


# --------------------------------------------------------------------------
# Pure context builders and response parsing (no network; unit-tested)
# --------------------------------------------------------------------------

def _hex_id(arbitration_id: Any) -> str:
    try:
        return f"0x{int(arbitration_id):X}"
    except (TypeError, ValueError):
        return str(arbitration_id)


def describe_message(activity: dict, samples: list[dict], *, max_samples: int = 8) -> str:
    """Format one id's :func:`app.can.reverse.bit_activity` result plus a few
    decoded sample frames into a compact prompt block."""
    lines = [
        f"Arbitration id: {_hex_id(activity.get('arbitration_id'))}",
        f"Data length: {activity.get('length', 0)} bytes over "
        f"{activity.get('frame_count', 0)} frames",
        "",
        "Per-byte behavior (index: classification, min..max, unique values):",
    ]
    for b in activity.get("bytes", []):
        lines.append(
            f"  byte {b.get('index')}: {b.get('classification')} "
            f"({b.get('min')}..{b.get('max')}, {b.get('unique_values')} unique)"
        )
    rows = []
    for frame in samples[:max_samples]:
        data = frame.get("data") or []
        rows.append(" ".join(f"{int(x) & 0xFF:02X}" for x in data))
    if rows:
        lines += ["", "Sample frames (hex bytes):"]
        lines += [f"  {r}" for r in rows]
    return "\n".join(lines)


def describe_candidate(candidate: dict, reference_hint: str = "") -> str:
    """Format a ranked candidate (and what the technician was doing) into a
    prompt block for name suggestion."""
    order = "Intel/little-endian" if candidate.get("byte_order") == "little_endian" else "Motorola/big-endian"
    lines = [
        f"Arbitration id: {_hex_id(candidate.get('arbitration_id'))}",
        f"Start bit: {candidate.get('start_bit')}, length: {candidate.get('length')} bits, {order}",
        f"Signed: {bool(candidate.get('signed'))}",
        f"Fitted scale: {candidate.get('scale')}, offset: {candidate.get('offset')}",
        f"Fit quality: r2={candidate.get('r2')}, correlation={candidate.get('correlation')}",
    ]
    hint = (reference_hint or "").strip()
    if hint:
        lines += ["", f"What the technician was doing while recording the reference: {hint}"]
    return "\n".join(lines)


def parse_json_response(text: str) -> dict[str, Any]:
    """Parse a model reply that should be a JSON object, tolerating an
    accidental ```json fence or surrounding prose. Returns ``{}`` when it is
    not usable."""
    if not text:
        return {}
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("```", 2)[1] if stripped.count("```") >= 2 else stripped.strip("`")
        if stripped.lstrip().lower().startswith("json"):
            stripped = stripped.lstrip()[4:]
    try:
        data = json.loads(stripped)
    except (ValueError, TypeError):
        # Last resort: grab the first {...} block if the model wrapped it.
        start, end = stripped.find("{"), stripped.rfind("}")
        if start == -1 or end <= start:
            return {}
        try:
            data = json.loads(stripped[start:end + 1])
        except (ValueError, TypeError):
            return {}
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------------------
# Provider transports (one HTTPS call each, uniform text in / text out)
# --------------------------------------------------------------------------

def _post_json(url: str, *, headers: dict | None = None, params: dict | None = None,
               payload: dict, timeout: float = 60.0) -> dict:
    import httpx
    try:
        resp = httpx.post(url, headers=headers, params=params, json=payload, timeout=timeout)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Could not reach the AI provider: {exc}") from exc
    if resp.status_code >= 400:
        detail = resp.text[:300]
        raise RuntimeError(f"AI provider error ({resp.status_code}): {detail}")
    try:
        return resp.json()
    except ValueError as exc:
        raise RuntimeError("AI provider returned a non-JSON response.") from exc


def _call_gemini(system: str, user: str, model: str, max_tokens: int) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
            "maxOutputTokens": max_tokens,
        },
    }
    data = _post_json(url, params={"key": _api_key()}, payload=payload)
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("The model returned no answer (a safety block or a bad model name?).")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts)


def _call_anthropic(system: str, user: str, model: str, max_tokens: int) -> str:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": _api_key(),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    data = _post_json(url, headers=headers, payload=payload)
    if data.get("stop_reason") == "refusal":
        raise RuntimeError("The model declined this request.")
    blocks = data.get("content") or []
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def _call_openai(system: str, user: str, model: str, max_tokens: int) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {_api_key()}", "content-type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    data = _post_json(url, headers=headers, payload=payload)
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("The model returned no answer.")
    return (choices[0].get("message") or {}).get("content", "")


def _call_ollama(system: str, user: str, model: str, max_tokens: int) -> str:
    base = _base_url() or _DEFAULT_OLLAMA_BASE
    url = f"{base.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": max_tokens},
    }
    data = _post_json(url, payload=payload)
    return (data.get("message") or {}).get("content", "")


_CALLERS = {
    "gemini": _call_gemini,
    "anthropic": _call_anthropic,
    "openai": _call_openai,
    "ollama": _call_ollama,
}


# --------------------------------------------------------------------------
# Vision: read a number off a dashboard photo, for a vision-based reference.
# --------------------------------------------------------------------------

def _call_gemini_vision(system: str, user: str, image_b64: str, mime: str, model: str, max_tokens: int) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [
            {"text": user}, {"inline_data": {"mime_type": mime, "data": image_b64}}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.0,
                             "maxOutputTokens": max_tokens},
    }
    data = _post_json(url, params={"key": _api_key()}, payload=payload)
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("The model returned no answer (a safety block or a bad model name?).")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts)


def _call_anthropic_vision(system: str, user: str, image_b64: str, mime: str, model: str, max_tokens: int) -> str:
    url = "https://api.anthropic.com/v1/messages"
    headers = {"x-api-key": _api_key(), "anthropic-version": "2023-06-01", "content-type": "application/json"}
    payload = {
        "model": model, "max_tokens": max_tokens, "system": system,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": user},
            {"type": "image", "source": {"type": "base64", "media_type": mime, "data": image_b64}}]}],
    }
    data = _post_json(url, headers=headers, payload=payload)
    blocks = data.get("content") or []
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def _call_openai_vision(system: str, user: str, image_b64: str, mime: str, model: str, max_tokens: int) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {_api_key()}", "content-type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": [
            {"type": "text", "text": user},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}}]}],
        "response_format": {"type": "json_object"}, "max_tokens": max_tokens, "temperature": 0.0,
    }
    data = _post_json(url, headers=headers, payload=payload)
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("The model returned no answer.")
    return (choices[0].get("message") or {}).get("content", "")


def _call_ollama_vision(system: str, user: str, image_b64: str, mime: str, model: str, max_tokens: int) -> str:
    base = _base_url() or _DEFAULT_OLLAMA_BASE
    url = f"{base.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user, "images": [image_b64]}],
        "format": "json", "stream": False, "options": {"temperature": 0.0, "num_predict": max_tokens},
    }
    data = _post_json(url, payload=payload)
    return (data.get("message") or {}).get("content", "")


_VISION_CALLERS = {
    "gemini": _call_gemini_vision,
    "anthropic": _call_anthropic_vision,
    "openai": _call_openai_vision,
    "ollama": _call_ollama_vision,
}

_VISION_SYSTEM = (
    "You read a single number off a photo of a vehicle dashboard or display. Return only "
    "the numeric value of the quantity asked for, as JSON. If the value is not clearly "
    "visible, return null. Do not guess."
)


def read_dashboard_value(image_b64: str, mime_type: str, what: str) -> dict[str, Any]:
    """Read one numeric value (e.g. speed) from a dashboard image via the vision
    model. Returns ``{"value": float|None}``. Raises ``RuntimeError`` with a
    bench-friendly message when the provider is not ready or the call fails."""
    ready = status()
    if not ready["available"]:
        raise RuntimeError(ready["reason"])
    caller = _VISION_CALLERS.get(_provider())
    if caller is None:
        raise RuntimeError(f"The {_provider()} provider is not set up for image reading here.")
    what = (what or "the displayed value").strip()
    user = (f'Read the current {what} shown in this image. Reply as JSON '
            '{"value": <number or null>}.')
    text = caller(_VISION_SYSTEM, user, image_b64, mime_type or "image/jpeg", _model(), 300)
    data = parse_json_response(text)
    value = data.get("value") if isinstance(data, dict) else None
    if value is None:
        return {"value": None}
    try:
        return {"value": float(value)}
    except (TypeError, ValueError):
        return {"value": None}


# --------------------------------------------------------------------------
# The one shaped call, and the two entry points
# --------------------------------------------------------------------------

def _ask_json(system: str, user: str, *, max_tokens: int = 1500) -> dict[str, Any]:
    """Ask the configured provider for a JSON object. Raises ``RuntimeError``
    with a bench-friendly message on any failure so callers can surface it
    verbatim."""
    ready = status()
    if not ready["available"]:
        raise RuntimeError(ready["reason"])
    caller = _CALLERS[_provider()]
    text = caller(system, user, _model(), max_tokens)
    data = parse_json_response(text)
    if not data:
        raise RuntimeError("The model did not return a usable answer.")
    return data


def _with_context(user: str, context_hint: str, known_signals: str) -> str:
    hint = (context_hint or "").strip()
    if hint:
        user += f"\n\nVehicle/platform context from the technician: {hint}"
    known = (known_signals or "").strip()
    if known:
        user += ("\n\nSignals already decoded in this vehicle's database (use as context, and do not "
                 f"re-propose one of these):\n{known}")
    return user


def interpret_message(activity: dict, samples: list[dict], context_hint: str = "",
                      known_signals: str = "") -> dict[str, Any]:
    """Ask the LLM what one message's active bytes probably carry."""
    user = _with_context(describe_message(activity, samples), context_hint, known_signals)
    user += "\n\nInterpret this message. " + _INTERPRET_SHAPE
    data = _ask_json(_INTERPRET_SYSTEM, user, max_tokens=1600)
    return {"available": True, "provider": _provider(), "model": _model(), **data}


def suggest_name(candidate: dict, reference_hint: str = "", context_hint: str = "",
                 known_signals: str = "") -> dict[str, Any]:
    """Ask the LLM to name/label a discovered candidate signal."""
    user = _with_context(describe_candidate(candidate, reference_hint), context_hint, known_signals)
    user += "\n\nPropose a name, unit, and description. " + _NAME_SHAPE
    data = _ask_json(_NAME_SYSTEM, user, max_tokens=800)
    return {"available": True, "provider": _provider(), "model": _model(), **data}
