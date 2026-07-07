# AutoPi: Agent Instructions

Canonical instructions for every AI agent working in this repo (Claude Code,
Codex, and anything else). `CLAUDE.md` is just a pointer to this file; edit
here, not there.

## What This Is

AutoPi is a blank-slate control surface for a Raspberry Pi (or any
Debian/Ubuntu server). It runs a web interface plus an optional physical
Stream Deck and an optional screen (touch or not), and it drives an external
environment through a library of user-defined **actions**: GPIO pins, shell
commands, HTTP calls to other applications, and (Phase 2) automotive CAN bus
messages.

Nothing about the app is domain-specific. The point is maximum flexibility:
you define actions, then drag and drop them onto a start menu and a Stream
Deck to build whatever controller you need.

This project was spun out from the Pantry Raider codebase, reusing its proven
device bones (the Stream Deck render and paging pipeline, the atomic
state-file pattern, the kiosk and Wi-Fi AP provisioning) with every food and
Pantry Raider reference removed.

## Deployment Modes

AutoPi is **host-only**. There is no thin-client / satellite mode.

- **server**: the Docker Compose stack on any Debian/Ubuntu box.
- **pi_hosted**: the full stack on a Raspberry Pi appliance, usually with the
  local kiosk display and/or a Stream Deck attached.

## Architecture in One Line

An **action** is a named unit of behavior that dispatches to a **driver**
(gpio / shell / http / builtin / macro / can). A **layout** binds actions to
slots on **surfaces** (the web start menu and the Stream Deck). Both surfaces
render the same layout; the drag-and-drop editor rewrites it.

## Service Architecture

- `service/app/main.py`: FastAPI app (port 8000 in-container, 9284 on host).
- `service/app/config.py`: pydantic settings; env vars override
  `service/data/settings.json` (written by the setup page).
- `service/app/actions/registry.py`: the action library. Builtin actions plus
  user-defined actions loaded from a state file. `run(action_id)` dispatches
  to a driver.
- `service/app/actions/drivers/`: `Driver` ABC and the concrete drivers
  (`gpio.py`, `shell.py`, `http.py`; `can.py` is a Phase 2 placeholder). Every
  driver degrades gracefully when its hardware or dependency is absent, so the
  app runs on a laptop with no Pi attached.
- `service/app/services/state.py`: the atomic JSON state-file helper (temp
  file + `os.replace`, mtime-cached reads, silent in-memory degradation when
  the data dir is unwritable). All cross-surface state uses it.
- `service/app/services/layout.py`: the layout model (surfaces, slots,
  drag-and-drop persistence).
- `service/app/services/deck_layout.py`: pure paging and rotation math shared
  by the web grid and the Stream Deck. Keep it pure so it stays testable.
- `service/app/routers/`: REST + UI routes. `ui.py` serves the start menu and
  kiosk pages; `layout.py` is the editor API; `actions.py` lists and runs
  actions; `setup.py` is settings.

## Stream Deck Controller (`streamdeck/`)

`autopi_streamdeck` is the physical Stream Deck controller (systemd + udev
units alongside). It reads the shared layout, renders key faces, and on a key
press calls the app's `POST /actions/{id}/run`. Supports the Mini (6),
Original/MK.2 (15), and XL (32) with 0/90/180/270 rotation.

## Conventions and Gotchas

- App code is volume-mounted with `--reload`: `git pull` applies changes live;
  rebuild only for `requirements.txt` or Dockerfile changes.
- Cross-surface state (layout, active page, settings) is shared through small
  atomic JSON state files under data_dir so multiple uvicorn workers agree and
  state survives a restart. Keep the parse and layout logic pure and testable.
- Drivers must never assume hardware is present. On a dev machine the GPIO and
  CAN drivers log and no-op instead of crashing.

## Writing Style

Applies to ALL project content: code comments, docs, README, CHANGELOG,
commit messages, and UI copy.

- No em-dashes. Use commas, parentheses, colons, or rewrite the sentence.
- No ASCII line or box diagrams.
- Copy reads as human-written; avoid LLM tells.
- Docs and UI copy are user-forward: written for the app's end user, not as
  notes to the developer.

## Build and Test

```bash
docker compose up -d --build         # run the stack

# local smoke test:
pip install -r service/requirements.txt
python -c "import sys; sys.path.insert(0,'service'); from app.main import app"

# tests (pure logic, no network or hardware needed):
pip install pytest && python -m pytest tests/ -q
```

**Definition of done:** run `python -m pytest tests/ -q` and the import smoke
test before handing off. A user-facing change also needs a CHANGELOG entry.

## Versioning

`APP_VERSION` in `service/app/config.py` is the single source of truth
(major.minor.patch). Pre-1.0: stay in `0.x`. Every user-facing change gets a
CHANGELOG entry under `[Unreleased]`.

## Roadmap

See `docs/ROADMAP.md`. Phase 1 is the GPIO / shell / HTTP control surface on
Raspberry Pi Lite and on a server. Phase 2 adds the automotive CAN
environment via CAN HATs, starting with the Waveshare 2-Channel CAN-FD HAT.
