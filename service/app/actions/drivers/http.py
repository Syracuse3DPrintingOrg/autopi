"""Call another application over HTTP as an action.

This is the main way AutoPi ties into external software: point an action at a
webhook, a REST endpoint, or another device's API and bind it to a key.
"""
from __future__ import annotations

from typing import Any

from .base import Driver, DriverResult

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


class HttpDriver(Driver):
    name = "http"
    label = "HTTP request"
    param_schema = [
        {"key": "method", "label": "Method", "type": "choice", "choices": list(METHODS),
         "required": True, "default": "POST"},
        {"key": "url", "label": "URL", "type": "text", "required": True},
        {"key": "headers", "label": "Headers", "type": "keyvalue", "required": False},
        {"key": "body", "label": "Body", "type": "text", "required": False,
         "help": "Sent as JSON when it parses as JSON, otherwise as raw text."},
        {"key": "timeout", "label": "Timeout (seconds)", "type": "number",
         "required": False, "default": 10},
    ]

    @property
    def available(self) -> bool:
        try:
            import httpx  # noqa: F401
            return True
        except Exception:
            return False

    def execute(self, params: dict[str, Any]) -> DriverResult:
        url = str(params.get("url", "")).strip()
        if not url:
            return DriverResult.failure("No URL configured")
        method = str(params.get("method", "POST")).upper()
        if method not in METHODS:
            return DriverResult.failure(f"Unsupported method: {method}")
        headers = params.get("headers") if isinstance(params.get("headers"), dict) else {}
        try:
            timeout = float(params.get("timeout", 10) or 10)
        except (TypeError, ValueError):
            timeout = 10.0

        try:
            import httpx
        except Exception:
            return DriverResult.failure("httpx is not installed")

        json_body, text_body = _split_body(params.get("body"))
        try:
            resp = httpx.request(
                method, url, headers=headers, timeout=timeout,
                json=json_body, content=text_body,
            )
        except httpx.HTTPError as exc:
            return DriverResult.failure(f"Request failed: {exc}")
        ok = resp.status_code < 400
        message = f"{method} {url} -> {resp.status_code}"
        result = DriverResult(ok=ok, message=message,
                              data={"status_code": resp.status_code,
                                    "body": resp.text[:2000]})
        return result


def _split_body(body: Any) -> tuple[Any, Any]:
    """Decide whether to send the body as JSON or raw text."""
    if body is None or body == "":
        return None, None
    if isinstance(body, (dict, list)):
        return body, None
    text = str(body)
    try:
        import json
        return json.loads(text), None
    except ValueError:
        return None, text.encode("utf-8")
