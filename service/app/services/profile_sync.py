"""Pull vehicle profiles from a central AutoPi server (future feature).

There is no real server yet. This client defines a simple REST protocol a
future server would expose, and talks to it so a fleet of devices could pull
a vehicle's whole setup instead of it being hand-built on each one:

- ``GET {server}/profiles`` returns a list of
  ``{key, name, year, make, model, updated}`` summaries.
- ``GET {server}/profiles/{key}`` returns
  ``{key, name, year, make, model, updated, bundle}`` where ``bundle`` is the
  same shape ``services.profile_bundle`` captures and applies: databases,
  actions, layout, and simulation entries.

A pulled profile is matched to a local one by a ``sync_key`` stashed in the
profile's ``config`` blob (created on first pull if none matches), then the
bundle is stored and applied through ``profile_bundle``, which does the
database id remapping and everything else a local capture/apply already
handles.

Every public function degrades to a clear ``{"ok": False, "error": ...}``
instead of raising: unconfigured settings and an unreachable server are
expected, ordinary states here, not exceptional ones.
"""
from __future__ import annotations

from typing import Any

import httpx

from ..config import settings
from . import profile_bundle
from . import profiles as profiles_svc

NOT_CONFIGURED = (
    "Profile sync is not set up. Add a sync server URL and device token in "
    "Settings, Profile Sync."
)


def configured() -> bool:
    """Is there enough settings.json to talk to a sync server?"""
    return bool(settings.sync_server_url.strip()) and bool(settings.sync_device_token.strip())


def _request(method: str, path: str, timeout: float = 15.0) -> tuple[bool, Any]:
    """Relay one request to the sync server. Never raises.

    Returns ``(True, parsed_json)`` on success or ``(False, error_message)``.
    """
    base = settings.sync_server_url.strip().rstrip("/")
    headers = {"Authorization": f"Bearer {settings.sync_device_token.strip()}"}
    try:
        r = httpx.request(method, f"{base}{path}", headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        return False, f"Could not reach the sync server: {exc}"
    if r.status_code >= 400:
        return False, f"The sync server returned an error (HTTP {r.status_code})."
    try:
        return True, r.json()
    except ValueError:
        return False, "The sync server sent a response that was not valid JSON."


# --- Pure parsing / validation (no network, fully unit-testable) -----------


def parse_remote_list(payload: Any) -> list[dict] | None:
    """Normalize a ``GET /profiles`` response into a list of summaries.

    Accepts either a bare list or ``{"profiles": [...]}``. Returns ``None``
    when the payload is not a recognizable shape; entries missing a ``key``
    are dropped rather than failing the whole list.
    """
    if isinstance(payload, dict) and "profiles" in payload:
        payload = payload["profiles"]
    if not isinstance(payload, list):
        return None
    out: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if not key:
            continue
        out.append({
            "key": key,
            "name": item.get("name") or key,
            "year": item.get("year"),
            "make": item.get("make") or "",
            "model": item.get("model") or "",
            "updated": item.get("updated") or "",
        })
    return out


def validate_bundle_payload(payload: Any) -> str | None:
    """Check a ``GET /profiles/{key}`` response is shaped like a profile bundle.

    Returns an error message when it is not, or ``None`` when it is fine to
    hand to ``profile_bundle.apply``.
    """
    if not isinstance(payload, dict):
        return "The sync server's response was not a JSON object."
    if not payload.get("key"):
        return "The sync server's response is missing the profile key."
    bundle = payload.get("bundle")
    if not isinstance(bundle, dict):
        return "The sync server's response is missing the profile bundle."
    for field in ("databases", "actions", "simulation"):
        value = bundle.get(field, [])
        if not isinstance(value, list):
            return f"The profile bundle's '{field}' field must be a list."
    layout = bundle.get("layout", {})
    if not isinstance(layout, dict):
        return "The profile bundle's 'layout' field must be an object."
    return None


def _find_local_profile_by_key(key: str) -> dict | None:
    for p in profiles_svc.list_profiles():
        if (p.get("config") or {}).get("sync_key") == key:
            return p
    return None


def _upsert_local_profile(payload: dict) -> dict:
    """Find the local profile this remote key already maps to, or create one."""
    key = payload["key"]
    existing = _find_local_profile_by_key(key)
    if existing is not None:
        return profiles_svc.update_profile(
            existing["id"],
            name=payload.get("name") or existing["name"],
            year=payload.get("year"),
            make=payload.get("make") or "",
            model=payload.get("model") or "",
        )
    return profiles_svc.create_profile(
        name=payload.get("name") or key,
        year=payload.get("year"),
        make=payload.get("make") or "",
        model=payload.get("model") or "",
        config={"sync_key": key},
    )


# --- Network-facing calls ---------------------------------------------------


def list_remote() -> dict:
    """List the profiles a sync server currently offers."""
    if not configured():
        return {"ok": False, "error": NOT_CONFIGURED}
    ok, data = _request("GET", "/profiles")
    if not ok:
        return {"ok": False, "error": data}
    parsed = parse_remote_list(data)
    if parsed is None:
        return {"ok": False, "error": "The sync server's profile list was not in the expected shape."}
    return {"ok": True, "profiles": parsed}


def pull(key: str) -> dict:
    """Download one profile bundle, create/find the local profile, and apply it."""
    if not configured():
        return {"ok": False, "error": NOT_CONFIGURED}
    if not key:
        return {"ok": False, "error": "A profile key is required."}
    ok, data = _request("GET", f"/profiles/{key}")
    if not ok:
        return {"ok": False, "error": data}
    error = validate_bundle_payload(data)
    if error:
        return {"ok": False, "error": error}

    local = _upsert_local_profile(data)
    profile_bundle.store_bundle(local["id"], data["bundle"])
    result = profile_bundle.apply(local["id"])
    if not result.get("ok"):
        return result
    return {
        "ok": True,
        "profile_id": local["id"],
        "key": key,
        "message": f"Pulled and applied '{data.get('name') or key}'.",
    }


def pull_all() -> dict:
    """Pull and apply every profile the sync server currently offers."""
    listing = list_remote()
    if not listing.get("ok"):
        return listing
    results = []
    pulled = 0
    for summary in listing["profiles"]:
        outcome = pull(summary["key"])
        results.append({"key": summary["key"], "name": summary.get("name"), **outcome})
        if outcome.get("ok"):
            pulled += 1
    return {"ok": True, "pulled": pulled, "total": len(listing["profiles"]), "results": results}


def push(profile_id: int) -> dict:
    """Push a local profile's setup to the sync server.

    The push direction has no server counterpart yet; this is a stub so the
    client's shape is settled and callers get a clean, non-crashing answer.
    """
    return {
        "ok": False,
        "error": "Pushing profiles to a sync server is not implemented yet. "
                 "Only pulling from a server is supported today.",
    }
