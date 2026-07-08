"""The virtual cockpit model: a user-designed surface of keys and gauges laid
over an uploaded background image.

A **cockpit** has an optional background image and an ordered list of
**elements** the user has placed on it. Each element carries its position and
size as *fractions* of the image (0..1), so the same layout scales to any
screen: the operate view multiplies a fraction by the rendered image's pixel
size (done in the template/JS, this module only produces the percentages).

Two element kinds:

- ``key``: bound to an ``action_id``, fired through the action registry
  (``actions/registry.py``) exactly like a Stream Deck key or start-menu tile.
- ``gauge`` / ``indicator``: bound to a CAN database + arbitration id +
  signal name. The live value comes from the running channel monitor's ring
  buffer (``can/monitor.py``), decoded against the database's DBC text
  (``can/dbc.py``), then mapped to a display value: a clamped numeric readout
  or percent for a gauge, an on/off state for an indicator.

Persistence follows the same pattern as the layout and profile-selection
state: a single atomic JSON file under data_dir (``services/state.py``), so
every uvicorn worker agrees and a restart does not lose the design.

Placement math and the gauge/indicator value mapping are kept pure (no I/O,
no CAN, no state file) so they are unit-testable without hardware or a
running monitor thread.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import settings
from .state import StateFile

ELEMENT_TYPES = ("key", "gauge", "indicator")
GAUGE_STYLES = ("numeric", "bar")

ALLOWED_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB


# --------------------------------------------------------------------------
# Pure helpers: placement, scaling, and value mapping. No I/O below this
# comment block touches a file, the database, or the CAN bus.
# --------------------------------------------------------------------------

def clamp(value: float, lo: float, hi: float) -> float:
    """Clamp ``value`` to [lo, hi], tolerating a swapped or degenerate range."""
    if lo > hi:
        lo, hi = hi, lo
    return max(lo, min(hi, value))


def clamp01(value: float) -> float:
    return clamp(float(value), 0.0, 1.0)


def _parse_arbitration_id(value: Any) -> int | None:
    """Accept an int, a decimal string, or a hex string like "0x201"."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    try:
        return int(text, 0) if text.lower().startswith("0x") else int(text)
    except ValueError:
        return None


def normalize_element(data: dict, *, element_id: str | None = None) -> dict:
    """Coerce a raw element dict into a well-formed one with sane defaults.

    Never raises: unparsable numeric fields fall back to a default rather
    than rejecting the whole element, since a half-filled binding (a gauge
    with no signal chosen yet) is the normal state while a user is still
    placing things in the editor.
    """
    etype = data.get("type") if data.get("type") in ELEMENT_TYPES else "key"

    def _float(key: str, default: float) -> float:
        try:
            return float(data.get(key, default))
        except (TypeError, ValueError):
            return default

    x = clamp01(_float("x", 0.1))
    y = clamp01(_float("y", 0.1))
    w = clamp(_float("w", 0.12), 0.01, 1.0)
    h = clamp(_float("h", 0.12), 0.01, 1.0)
    min_v = _float("min", 0.0)
    max_v = _float("max", 100.0)

    style = data.get("style") or ("bar" if etype == "gauge" else "numeric")
    if etype == "gauge" and style not in GAUGE_STYLES:
        style = "numeric"

    threshold = data.get("threshold")
    try:
        threshold = None if threshold in (None, "") else float(threshold)
    except (TypeError, ValueError):
        threshold = None

    element = {
        "id": element_id or data.get("id") or "",
        "type": etype,
        "x": x, "y": y, "w": w, "h": h,
        "label": str(data.get("label", "") or ""),
        "color": str(data.get("color") or "#334155"),
        # key binding
        "action_id": data.get("action_id") or None,
        # gauge/indicator binding
        "database_id": data.get("database_id") if isinstance(data.get("database_id"), int) else
                       (int(data["database_id"]) if str(data.get("database_id") or "").isdigit() else None),
        "arbitration_id": _parse_arbitration_id(data.get("arbitration_id")),
        "signal": data.get("signal") or None,
        "channel": str(data.get("channel") or "can0"),
        "backend": str(data.get("backend") or "socketcan"),
        "min": min_v,
        "max": max_v,
        "style": style,
        "threshold": threshold,
        "unit": str(data.get("unit", "") or ""),
    }
    return element


def element_rect_percent(element: dict) -> dict[str, float]:
    """The element's placement as CSS-ready percentages of the background image."""
    return {
        "left": round(clamp01(element.get("x", 0.0)) * 100, 4),
        "top": round(clamp01(element.get("y", 0.0)) * 100, 4),
        "width": round(clamp(element.get("w", 0.12), 0.01, 1.0) * 100, 4),
        "height": round(clamp(element.get("h", 0.12), 0.01, 1.0) * 100, 4),
    }


def gauge_percent(value: float, min_v: float, max_v: float) -> float:
    """Where ``value`` falls in [min_v, max_v], as 0..100, clamped either way."""
    if max_v == min_v:
        return 0.0
    span = max_v - min_v
    return (clamp(value, min(min_v, max_v), max(min_v, max_v)) - min_v) / span * 100.0


def indicator_on(value: Any, threshold: float | None) -> bool:
    """Whether a numeric (or truthy) value counts as "on" past ``threshold``."""
    if threshold is None:
        threshold = 0.0
    try:
        return float(value) >= float(threshold)
    except (TypeError, ValueError):
        return bool(value)


def map_element_value(element: dict, raw: Any) -> dict[str, Any]:
    """Turn a raw decoded signal value into a display payload for a gauge or
    indicator element. Never raises: an unbound element or an undecoded
    value just yields a "no data" payload instead of failing the request.
    """
    if raw is None:
        return {"ok": False, "raw": None, "value": None, "percent": None,
                "on": None, "display": "--"}

    etype = element.get("type")
    if etype == "indicator":
        try:
            numeric: float | None = float(raw)
        except (TypeError, ValueError):
            numeric = None
        on = indicator_on(numeric if numeric is not None else raw, element.get("threshold"))
        return {"ok": True, "raw": raw, "value": numeric, "percent": None,
                "on": on, "display": "ON" if on else "OFF"}

    try:
        numeric = float(raw)
    except (TypeError, ValueError):
        return {"ok": True, "raw": raw, "value": None, "percent": None,
                "on": None, "display": str(raw)}

    min_v = float(element.get("min", 0.0) or 0.0)
    max_v = float(element.get("max", 100.0) or 100.0)
    clamped = clamp(numeric, min(min_v, max_v), max(min_v, max_v))
    percent = gauge_percent(numeric, min_v, max_v)
    unit = element.get("unit") or ""
    display = f"{clamped:.1f}{(' ' + unit) if unit else ''}"
    return {"ok": True, "raw": raw, "value": clamped, "percent": percent,
            "on": None, "display": display}


def _default_decode(dbc_text: str, arbitration_id: int, data: bytes) -> dict[str, Any]:
    from ..can import dbc as dbc_mod
    return dbc_mod.decode(dbc_text, arbitration_id, data)


def latest_signal_value(
    frames: list[dict], dbc_text: str | None, arbitration_id: int | None,
    signal: str | None, decode_fn=None,
) -> Any:
    """The most recent decoded value of ``signal`` for ``arbitration_id`` in
    ``frames`` (oldest-first, matching ``MonitorChannel.frames()``), or
    ``None`` if unbound, undecodable, or never seen.

    Pure with respect to its arguments: a test drives it with synthetic frame
    dicts and a stubbed ``decode_fn``, no CAN hardware or monitor thread
    involved.
    """
    if not dbc_text or not signal or arbitration_id is None:
        return None
    decode_fn = decode_fn or _default_decode
    for record in reversed(frames):
        if record.get("arbitration_id") != arbitration_id:
            continue
        try:
            decoded = decode_fn(dbc_text, arbitration_id, bytes(record.get("data") or []))
        except Exception:
            return None
        return decoded.get(signal)
    return None


def validate_image_upload(filename: str | None, size: int) -> str | None:
    """Return an error message if the upload should be rejected, else None."""
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        allowed = ", ".join(ALLOWED_IMAGE_EXTS)
        return f"Unsupported image type '{ext or '(none)'}'. Use one of: {allowed}."
    if size <= 0:
        return "The uploaded file is empty."
    if size > MAX_IMAGE_BYTES:
        limit_mb = MAX_IMAGE_BYTES // (1024 * 1024)
        return f"Image is too large; the limit is {limit_mb} MB."
    return None


# --------------------------------------------------------------------------
# Persistence: cockpits.json under data_dir, the same atomic-state pattern
# used for the layout and profile selection.
# --------------------------------------------------------------------------

def _store() -> StateFile:
    return StateFile(settings.data_dir / "cockpits.json", default={"cockpits": [], "next_id": 1})


def image_dir() -> Path:
    return settings.data_dir / "cockpit_images"


def image_path_for(cockpit: dict) -> Path | None:
    filename = cockpit.get("image_filename")
    if not filename:
        return None
    return image_dir() / filename


def list_cockpits() -> list[dict]:
    return list(_store().read().get("cockpits", []))


def get_cockpit(cockpit_id: int) -> dict | None:
    for c in list_cockpits():
        if c.get("id") == cockpit_id:
            return c
    return None


def create_cockpit(name: str = "", profile_id: int | None = None) -> dict:
    store = _store()
    doc = store.read()
    cockpit_id = doc.get("next_id", 1)
    cockpit = {
        "id": cockpit_id, "name": name or f"Cockpit {cockpit_id}",
        "profile_id": profile_id, "image_filename": None, "elements": [],
        "next_element_seq": 1,
    }
    doc.setdefault("cockpits", []).append(cockpit)
    doc["next_id"] = cockpit_id + 1
    store.write(doc)
    return cockpit


def update_cockpit(cockpit_id: int, **fields) -> dict | None:
    store = _store()
    doc = store.read()
    for c in doc.get("cockpits", []):
        if c.get("id") == cockpit_id:
            if "name" in fields and fields["name"] is not None:
                c["name"] = fields["name"]
            if "profile_id" in fields:
                c["profile_id"] = fields["profile_id"]
            store.write(doc)
            return c
    return None


def delete_cockpit(cockpit_id: int) -> bool:
    store = _store()
    doc = store.read()
    cockpits = doc.get("cockpits", [])
    kept = [c for c in cockpits if c.get("id") != cockpit_id]
    if len(kept) == len(cockpits):
        return False
    doc["cockpits"] = kept
    store.write(doc)
    return True


def set_background_image(cockpit_id: int, filename: str | None) -> dict | None:
    """Set (or clear) the cockpit's background image filename directly.

    Kept separate from :func:`update_cockpit`, which only forwards the
    name/profile_id fields, so a partial update there can never accidentally
    leave (or clear) the image out of sync.
    """
    store = _store()
    doc = store.read()
    for c in doc.get("cockpits", []):
        if c.get("id") == cockpit_id:
            c["image_filename"] = filename
            store.write(doc)
            return c
    return None


def add_element(cockpit_id: int, data: dict) -> dict | None:
    """Normalize and append an element, returning the updated cockpit."""
    store = _store()
    doc = store.read()
    for c in doc.get("cockpits", []):
        if c.get("id") == cockpit_id:
            seq = c.get("next_element_seq", 1)
            element = normalize_element(data, element_id=f"el{seq}")
            c.setdefault("elements", []).append(element)
            c["next_element_seq"] = seq + 1
            store.write(doc)
            return c
    return None


def update_element(cockpit_id: int, element_id: str, data: dict) -> dict | None:
    store = _store()
    doc = store.read()
    for c in doc.get("cockpits", []):
        if c.get("id") == cockpit_id:
            elements = c.get("elements", [])
            for i, el in enumerate(elements):
                if el.get("id") == element_id:
                    # Merge over the existing element so a caller can PATCH
                    # just one or two fields (e.g. only min/max) without
                    # having to resend the whole binding. Pass an explicit
                    # ``None`` for a field that should be cleared out.
                    merged = dict(el)
                    merged.update(data)
                    elements[i] = normalize_element(merged, element_id=element_id)
                    store.write(doc)
                    return c
            return None
    return None


def delete_element(cockpit_id: int, element_id: str) -> bool:
    store = _store()
    doc = store.read()
    for c in doc.get("cockpits", []):
        if c.get("id") == cockpit_id:
            before = c.get("elements", [])
            after = [el for el in before if el.get("id") != element_id]
            if len(after) == len(before):
                return False
            c["elements"] = after
            store.write(doc)
            return True
    return False
