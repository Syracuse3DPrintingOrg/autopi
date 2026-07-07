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

# id, label, driver, params, icon, color, category
_DEMO = [
    ("lamp", "Lamp", "gpio", {"pin": 17, "mode": "toggle"}, "bi-lightbulb", "#b45309", "Lights"),
    ("fan", "Fan", "gpio", {"pin": 27, "mode": "toggle"}, "bi-fan", "#0e7490", "Lights"),
    ("door", "Door", "gpio", {"pin": 22, "mode": "pulse", "pulse_ms": 400}, "bi-door-open", "#7c3aed", "Access"),
    ("ping", "Ping", "shell", {"command": "ping -c 1 1.1.1.1"}, "bi-broadcast-pin", "#334155", "Network"),
    ("status", "Status", "http", {"method": "GET", "url": "http://127.0.0.1:9284/health"},
     "bi-activity", "#166534", "Network"),
    ("webhook", "Webhook", "http", {"method": "POST", "url": "http://127.0.0.1:9284/health"},
     "bi-cloud-arrow-up", "#1d4ed8", "Network"),
]

# A macro that fires two of the demo actions in order.
_MACRO = ActionSpec(id="all-on", label="All on", driver="macro",
                    members=["lamp", "fan"], icon="bi-collection", color="#be123c",
                    category="Macros")


def seed_if_empty() -> bool:
    """Seed demo actions and fill empty surfaces on a fresh (or upgraded) install.

    Keyed off having no user actions rather than the presence of a state file:
    an earlier build could leave an empty layout.json behind, which used to make
    seeding skip and leave a blank start page. If a library already exists,
    nothing is touched.
    """
    if user_actions():
        return False

    specs = [ActionSpec(id=i, label=l, driver=d, params=p, icon=ic, color=c, category=cat)
             for (i, l, d, p, ic, c, cat) in _DEMO]
    specs.append(_MACRO)
    save_user_actions(specs)

    order = ["lamp", "fan", "door", "ping", "status", "webhook", "all-on"]
    # Only fill a surface that is empty, so a saved layout is never overwritten.
    for surface in ("start", "streamdeck"):
        if not any(layout_svc.get_layout(surface)):
            layout_svc.set_layout(surface, order)
    return True
