"""Which UI a request sees: the touch-first operator surface or the desktop
builder.

The app serves two audiences from the same server: a Raspberry Pi running
its own touchscreen and Stream Deck (the operator surface, ``/operator``),
and a PC browsing in to build layouts, actions, and test sequences (the
builder, the rest of the app). ``ui_mode`` in settings picks a fixed side
("operator" or "builder") or leaves it on "auto", where the decision is made
per request.

:func:`decide_ui_mode` is pure (no ``Request``, no settings singleton) so it
is unit-tested directly with fake hosts and settings values. The router
layer (``routers/ui.py``) is the only place that touches a real ``Request``:
it reads the client host and the kiosk latch out of the session, then calls
this function.
"""
from __future__ import annotations

OPERATOR = "operator"
BUILDER = "builder"
AUTO = "auto"

# Valid values for the ``ui_mode`` setting.
UI_MODES = (AUTO, OPERATOR, BUILDER)

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def is_loopback_host(host: str | None) -> bool:
    """Whether ``host`` (a request's client address) is the local machine.

    A Pi appliance talks to its own server over loopback (the kiosk browser
    and the server share the same box); a PC on the LAN or beyond does not.
    """
    return host in _LOOPBACK_HOSTS


def decide_ui_mode(*, host: str | None, kiosk_latched: bool, ui_mode_setting: str) -> str:
    """Decide "operator" or "builder" for one request.

    ``ui_mode_setting`` of "operator" or "builder" always wins (an explicit
    choice is never second-guessed). "auto" (the default) picks operator for
    a loopback client or once the kiosk latch is set, builder otherwise.
    """
    if ui_mode_setting == OPERATOR:
        return OPERATOR
    if ui_mode_setting == BUILDER:
        return BUILDER
    if kiosk_latched or is_loopback_host(host):
        return OPERATOR
    return BUILDER
