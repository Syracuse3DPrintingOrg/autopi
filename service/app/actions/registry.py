"""The action library.

An **action** is a named unit of behavior with a stable id, a look (label,
icon, color), a driver, and driver-specific params. Actions come from two
places:

- **builtins**: surface controls (page navigation, a blank slot) that the app
  ships with. They are driven in-process, not through a hardware driver.
- **user actions**: everything the device owner defines in the UI, persisted
  to ``actions.json`` under data_dir through the shared atomic state file.

``run(action_id)`` looks the action up and dispatches it: builtins return a
surface hint the caller acts on, a ``macro`` runs its member actions in order,
and everything else goes to the named driver. Keeping the registry the single
place that resolves an id to behavior is what lets any surface (web start menu,
Stream Deck, an HTTP call) trigger the same action.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..config import settings
from ..services.state import StateFile
from .drivers import DriverResult, get_driver


@dataclass
class ActionSpec:
    id: str
    label: str = ""
    driver: str = "shell"
    params: dict[str, Any] = field(default_factory=dict)
    icon: str = "bi-lightning-charge"   # a Bootstrap Icons name
    color: str = "#334155"
    # Palette grouping in the layout editor (e.g. "Actions", "System").
    category: str = "Actions"
    # For driver == "macro": ordered list of action ids to run.
    members: list[str] = field(default_factory=list)
    # True for keys that only do something on a physical Stream Deck (paging,
    # brightness, screen power); the start menu shows them but hints instead.
    deck_only: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionSpec":
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(**known)


# Builtin surface controls. These are always available and cannot be deleted.
# "driver": "builtin" is handled directly by run(). Most only do something on a
# connected deck (deck_only), so the start menu shows them but hints on press.
def _b(id, label, op, icon, color, category, deck_only=True):
    return ActionSpec(id=id, label=label, driver="builtin", params={"op": op},
                      icon=icon, color=color, category=category, deck_only=deck_only)


BUILTINS: dict[str, ActionSpec] = {
    "page_prev": _b("page_prev", "Back", "page_prev", "bi-chevron-left", "#1f2937", "Navigation"),
    "page_next": _b("page_next", "More", "page_next", "bi-chevron-right", "#1f2937", "Navigation"),
    "brightness": _b("brightness", "Bright", "brightness", "bi-brightness-high", "#b45309", "System"),
    "screen_off": _b("screen_off", "Screen Off", "screen_off", "bi-display", "#334155", "System"),
    "screen_on": _b("screen_on", "Screen On", "screen_on", "bi-display-fill", "#166534", "System"),
    "clock": _b("clock", "Clock", "clock", "bi-clock", "#4338ca", "Info"),
    "blank": ActionSpec("blank", "", "builtin", {"op": "blank"}, "", "#111827", category="Other"),
}


def _store() -> StateFile:
    return StateFile(settings.data_dir / "actions.json", default={"actions": []})


def user_actions() -> dict[str, ActionSpec]:
    doc = _store().read()
    out: dict[str, ActionSpec] = {}
    for raw in doc.get("actions", []):
        if isinstance(raw, dict) and raw.get("id"):
            spec = ActionSpec.from_dict(raw)
            out[spec.id] = spec
    return out


def all_actions() -> dict[str, ActionSpec]:
    """Builtins plus user actions (user actions win on an id clash)."""
    merged = dict(BUILTINS)
    merged.update(user_actions())
    return merged


def get_action(action_id: str) -> ActionSpec | None:
    return all_actions().get(action_id)


def save_user_actions(specs: list[ActionSpec]) -> None:
    payload = {"actions": [s.to_dict() for s in specs if s.id not in BUILTINS]}
    _store().write(payload)


def upsert_action(spec: ActionSpec) -> None:
    if spec.id in BUILTINS:
        raise ValueError(f"{spec.id} is a builtin and cannot be overwritten")
    current = list(user_actions().values())
    current = [s for s in current if s.id != spec.id]
    current.append(spec)
    save_user_actions(current)


def delete_action(action_id: str) -> bool:
    if action_id in BUILTINS:
        return False
    current = list(user_actions().values())
    kept = [s for s in current if s.id != action_id]
    if len(kept) == len(current):
        return False
    save_user_actions(kept)
    return True


def run(action_id: str, _depth: int = 0) -> DriverResult:
    """Resolve an action id and perform it."""
    spec = get_action(action_id)
    if spec is None:
        return DriverResult.failure(f"Unknown action: {action_id}")

    if spec.driver == "builtin":
        op = spec.params.get("op", "")
        # Surface controls are acted on by the caller (the web page or the
        # deck), so we just echo the op back as a hint.
        return DriverResult.success(f"builtin:{op}", op=op, builtin=True)

    if spec.driver == "macro":
        if _depth > 8:
            return DriverResult.failure("Macro nested too deep")
        results = []
        for member in spec.members:
            res = run(member, _depth=_depth + 1)
            results.append({"id": member, "ok": res.ok, "message": res.message})
            if not res.ok:
                return DriverResult.failure(
                    f"Macro stopped at {member}: {res.message}", steps=results)
        return DriverResult.success(f"Ran {len(results)} step(s)", steps=results)

    driver = get_driver(spec.driver)
    if driver is None:
        return DriverResult.failure(f"No driver named {spec.driver}")
    if not driver.available:
        return DriverResult.failure(
            f"The {driver.label} driver is not available on this host")
    return driver.execute(spec.params)
