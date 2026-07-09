"""Optional LLM assist for the Signal Finder.

The Signal Finder works purely on statistics: it never needs a network or an
API key. This module is the thin, entirely optional layer on top that uses the
Anthropic Claude API to make reverse engineering easier, mirroring the "let an
LLM name the signals" idea from CSS Electronics' AI CAN reverse-engineering
write-up:

- interpret which real quantity a message's active bytes probably carry, and
- propose a name, unit, and description for a candidate the search turned up.

Everything degrades gracefully. With no key configured, every entry point
returns ``{"available": False, "reason": ...}`` and the rest of the Signal
Finder is unaffected. The context-building and response-parsing helpers are
pure so they stay testable without touching the network.
"""
from __future__ import annotations

import json
from typing import Any

from .config import settings

# Claude Opus 4.8 is the default; a bench user can point at a cheaper/faster
# model (e.g. claude-haiku-4-5) from the AI settings section.
DEFAULT_MODEL = "claude-opus-4-8"

# Only the Anthropic Claude API is wired up today. The provider field exists so
# the setting is stable if other backends are added later.
SUPPORTED_PROVIDER = "anthropic"

_INTERPRET_SCHEMA = {
    "type": "object",
    "properties": {
        "message_guess": {"type": "string"},
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "bytes": {"type": "string"},
                    "guess": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["bytes", "guess", "confidence"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["message_guess", "fields", "notes"],
    "additionalProperties": False,
}

_NAME_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "unit": {"type": "string"},
        "description": {"type": "string"},
        "plausible": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["name", "unit", "description", "plausible", "reason"],
    "additionalProperties": False,
}

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


def _provider() -> str:
    return (getattr(settings, "llm_provider", "") or SUPPORTED_PROVIDER).strip().lower()


def _model() -> str:
    return (getattr(settings, "llm_model", "") or DEFAULT_MODEL).strip()


def _api_key() -> str:
    return (getattr(settings, "llm_api_key", "") or "").strip()


def status() -> dict[str, Any]:
    """Whether the LLM assist can run, and why not if it cannot. Safe to call
    from any surface (a template flag, a UI gate) without side effects."""
    provider = _provider()
    if provider != SUPPORTED_PROVIDER:
        return {"available": False, "provider": provider, "model": _model(),
                "reason": f"Only the {SUPPORTED_PROVIDER!r} provider is supported."}
    if not _api_key():
        return {"available": False, "provider": provider, "model": _model(),
                "reason": "No API key set. Add one in Settings under AI assist."}
    try:
        import anthropic  # noqa: F401
    except Exception:
        return {"available": False, "provider": provider, "model": _model(),
                "reason": "The 'anthropic' package is not installed on this device."}
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
    accidental ```json fence. Returns ``{}`` when it is not usable."""
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
        return {}
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------------------
# The one network call, and the two shaped entry points
# --------------------------------------------------------------------------

def _ask_json(system: str, user: str, schema: dict, *, max_tokens: int = 1500) -> dict[str, Any]:
    """Single Claude Messages call constrained to a JSON schema. Raises
    ``RuntimeError`` with a bench-friendly message on any failure so callers
    can surface it verbatim."""
    ready = status()
    if not ready["available"]:
        raise RuntimeError(ready["reason"])
    try:
        import anthropic
    except Exception as exc:  # pragma: no cover - covered by status()
        raise RuntimeError("The 'anthropic' package is not installed.") from exc

    client = anthropic.Anthropic(api_key=_api_key())
    try:
        resp = client.messages.create(
            model=_model(),
            max_tokens=max_tokens,
            system=system,
            output_config={
                "format": {"type": "json_schema", "schema": schema},
                "effort": "medium",
            },
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f"Claude API error ({exc.status_code}): {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise RuntimeError("Could not reach the Claude API (no internet?).") from exc
    except Exception as exc:
        raise RuntimeError(f"LLM request failed: {exc}") from exc

    if getattr(resp, "stop_reason", None) == "refusal":
        raise RuntimeError("The model declined this request.")
    text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), "")
    data = parse_json_response(text)
    if not data:
        raise RuntimeError("The model did not return a usable answer.")
    return data


def interpret_message(activity: dict, samples: list[dict], context_hint: str = "") -> dict[str, Any]:
    """Ask the LLM what one message's active bytes probably carry."""
    user = describe_message(activity, samples)
    hint = (context_hint or "").strip()
    if hint:
        user += f"\n\nVehicle/platform context from the technician: {hint}"
    user += "\n\nInterpret this message."
    data = _ask_json(_INTERPRET_SYSTEM, user, _INTERPRET_SCHEMA, max_tokens=1600)
    return {"available": True, "model": _model(), **data}


def suggest_name(candidate: dict, reference_hint: str = "", context_hint: str = "") -> dict[str, Any]:
    """Ask the LLM to name/label a discovered candidate signal."""
    user = describe_candidate(candidate, reference_hint)
    hint = (context_hint or "").strip()
    if hint:
        user += f"\n\nVehicle/platform context from the technician: {hint}"
    user += "\n\nPropose a name, unit, and description."
    data = _ask_json(_NAME_SYSTEM, user, _NAME_SCHEMA, max_tokens=800)
    return {"available": True, "model": _model(), **data}
