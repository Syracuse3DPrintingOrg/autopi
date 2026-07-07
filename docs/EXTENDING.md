# Extending AutoPi

AutoPi is a platform, not a finished product. It ships a small, generic core
and a few extension seams so you can adapt it to a specific product without
touching the plumbing. This is the guide to those seams.

## The model in three pieces

- An **action** (`service/app/actions/registry.py`) is a named unit of
  behavior: an id, a look (label, icon, color), a `driver`, and driver-specific
  `params`. Actions are data, stored in `actions.json`.
- A **driver** (`service/app/actions/drivers/`) is what an action actually
  does. Drivers are the main extension point.
- A **surface** (`service/app/services/layout.py`) is where keys are shown (the
  web start menu, the Stream Deck). A layout binds actions to slots on a
  surface, and the drag-and-drop editor rewrites it.

Any surface triggers an action the same way: `POST /actions/{id}/run`, which
goes through `registry.run()`. That single dispatch point is why the web menu
and the Stream Deck stay in agreement.

## Add a driver (the common case)

Drop a module into `service/app/actions/drivers/` with a `Driver` subclass:

```python
from .base import Driver, DriverResult

class RelayDriver(Driver):
    name = "relay"
    label = "Relay board"
    param_schema = [
        {"key": "channel", "label": "Channel", "type": "number", "required": True},
        {"key": "state", "label": "State", "type": "choice", "choices": ["on", "off"]},
    ]

    @property
    def available(self) -> bool:
        return _relay_board_present()  # never assume hardware; degrade to False

    def execute(self, params) -> DriverResult:
        ...
        return DriverResult.success("Relay set")
```

That is all. The registry auto-discovers any `Driver` subclass in the package
on import, so nothing else needs editing. From a separate plugin you can also
call `app.actions.drivers.register_driver(MyDriver())`.

Rules every driver follows:

- Never assume its hardware or dependency is present. Report `available =
  False` and no-op (or simulate) when it is missing, so one build runs on a
  laptop, a server, and a Pi.
- Return a `DriverResult`, never raise, for an expected failure.
- Keep any parsing or math pure and put it in a module-level function so it can
  be unit-tested without hardware (see `drivers/can.py`'s `_parse_frame`).

## Add a surface

Add the surface name to `SURFACES` in `service/app/services/layout.py`, then
render its layout wherever you need it (a new template, another device
controller). The paging and rotation helpers in
`service/app/services/deck_layout.py` are pure and reusable for any grid
surface.

## Rebrand for a product

The app name and version live in `service/app/config.py` (`APP_NAME`,
`APP_VERSION`). Device-level identifiers (systemd unit names, the AP SSID, the
`/opt/autopi` paths) are in `scripts/image-build/` and `streamdeck/systemd/`.
There is no domain content baked into the core to strip.

## Where things persist

All cross-surface state is a small atomic JSON file under `data_dir`
(`actions.json`, `layout.json`, `settings.json`), written through
`service/app/services/state.py`. It survives restarts, is shared across
uvicorn workers and the Stream Deck controller, and degrades to in-memory state
when the data dir is read-only.
