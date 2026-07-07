"""Seed a handful of demo actions and a starter layout on first run.

So a fresh install shows a populated start menu and Stream Deck instead of an
empty grid. Seeding only happens when there is no actions.json and no
layout.json yet, so it never clobbers a configured device. The demo actions are
generic (GPIO, shell, HTTP, a macro), not tied to any product.
"""
from __future__ import annotations

from ..actions.registry import ActionSpec, save_user_actions, user_actions
from ..config import settings
from ..services import layout as layout_svc

# id, label, driver, params, icon, color
_DEMO = [
    ("lamp", "Lamp", "gpio", {"pin": 17, "mode": "toggle"}, "bi-lightbulb", "#b45309"),
    ("fan", "Fan", "gpio", {"pin": 27, "mode": "toggle"}, "bi-fan", "#0e7490"),
    ("door", "Door", "gpio", {"pin": 22, "mode": "pulse", "pulse_ms": 400}, "bi-door-open", "#7c3aed"),
    ("ping", "Ping", "shell", {"command": "ping -c 1 1.1.1.1"}, "bi-broadcast-pin", "#334155"),
    ("status", "Status", "http", {"method": "GET", "url": "http://127.0.0.1:9284/health"},
     "bi-activity", "#166534"),
    ("webhook", "Webhook", "http", {"method": "POST", "url": "http://127.0.0.1:9284/health"},
     "bi-cloud-arrow-up", "#1d4ed8"),
]

# A macro that fires two of the demo actions in order.
_MACRO = ActionSpec(id="all-on", label="All on", driver="macro",
                    members=["lamp", "fan"], icon="bi-collection", color="#be123c")


def seed_if_empty() -> bool:
    """Seed demo actions + layout when nothing is configured. Returns True if seeded."""
    actions_path = settings.data_dir / "actions.json"
    layout_path = settings.data_dir / "layout.json"
    if actions_path.exists() or layout_path.exists() or user_actions():
        return False

    specs = [ActionSpec(id=i, label=l, driver=d, params=p, icon=ic, color=c)
             for (i, l, d, p, ic, c) in _DEMO]
    specs.append(_MACRO)
    save_user_actions(specs)

    order = ["lamp", "fan", "door", "ping", "status", "webhook", "all-on"]
    # The web start menu shows the actions; the deck gets the same plus its
    # built-in paging key so a small deck can scroll.
    layout_svc.set_layout("start", order)
    layout_svc.set_layout("streamdeck", order)
    return True
