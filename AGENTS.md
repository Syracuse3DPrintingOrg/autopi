# AutoPi: Agent Instructions

Canonical instructions for every AI agent working in this repo (Claude Code,
Codex, and anything else). `CLAUDE.md` is just a pointer to this file; edit
here, not there.

## What This Is

AutoPi is a **CAN-first automotive tool** for a Raspberry Pi (or any
Debian/Ubuntu server): reverse engineer a vehicle's CAN bus and build a custom
controller for it. It runs a web interface plus an optional physical Stream
Deck and an optional screen (touch or not). The core workflow: bring up the CAN
interfaces, find a signal or a control (Signal Finder / "Find a control"), save
it into a CAN database, and drop it onto a **cockpit** of buttons and gauges you
actually use, one-shot or periodic.

**Two surfaces by device (see `services/ui_mode.py`):** a desktop browser gets
the detailed builder/productivity environment (full nav, CAN Lab, Signal
Finder, databases); the Pi touchscreen and Stream Deck get the simple,
glanceable operator surface (`/operator`) for using what you built. The choice
is automatic (loopback/kiosk -> operator) with a manual override.

**The generic engine is preserved and forkable.** Under the hood everything
still runs through a domain-neutral **action / driver** library (GPIO, shell,
HTTP, CAN) laid onto a start menu, Stream Deck, and cockpit. AutoPi leads with
CAN, but that generic control-surface engine is kept intact and cleanly
separable, so the project can be forked into a non-CAN general-purpose testing
platform later. Do not gut the generic bones (actions / drivers / cockpit /
start / layout); keep them tucked under "Builder", not deleted.

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

- `APP_VERSION` in `service/app/config.py` is the single source of truth
  (major.minor.patch). The project is pre-1.0: `1.0.0` is reserved for the
  first public release, so stay in `0.x` until then.
- **Every commit changes at least the patch number.** Run
  `scripts/install-git-hooks.sh` once per clone to install a pre-commit hook
  that auto-bumps the patch; it chains onto the beads hook and skips rebases,
  merges, and beads-only commits. Re-run the installer if a beads hook update
  rewrites the managed hook.
- **Every user-facing change gets a CHANGELOG entry** under `[Unreleased]` in
  the appropriate Added/Changed/Fixed section, written in the existing
  plain-prose style. The changelog doubles as the release description, so write
  for users, not for developers.
- For a minor or major release, bump first so the hook stays out of the way:
  `scripts/bump-version.sh minor && git add service/app/config.py`.

## Authorship and Git

- **All commits are authored by Dan's GitHub identity**
  (`Syracuse3DPrinting <dm.marafino@gmail.com>`); the repo git config is
  already set, do not change it. Never add Co-Authored-By trailers, AI
  attributions, or session links to commit messages.
- Development happens on **`main`** directly.
- **Commit and push are part of done.** For any load-bearing change (code,
  docs, instructions, provisioning) and for beads work, commit and push before
  ending the session. The deployed devices update from GitHub, so an unpushed
  change has not shipped. Do not wait to be asked.
- The one exception: small conversational tweaks Dan asks for while just
  chatting (a wording nit, a quick experiment) may be left uncommitted for his
  review, unless he says ship it. When in doubt, commit and push.

## Non-Interactive Shell Commands

**ALWAYS use non-interactive flags** with file operations. `cp`, `mv`, and
`rm` may be aliased to `-i` on some systems, which hangs an agent waiting for
y/n input. Use `cp -f`, `mv -f`, `rm -f` (and `-rf` for recursive operations).
Similarly: `scp`/`ssh` with `-o BatchMode=yes`, `apt-get -y`, and
`HOMEBREW_NO_AUTO_UPDATE=1` for `brew`.

## Roadmap

See `docs/ROADMAP.md`. Phase 1 is the GPIO / shell / HTTP control surface on
Raspberry Pi Lite and on a server. Phase 2 adds the automotive CAN
environment via CAN HATs, starting with the Waveshare 2-Channel CAN-FD HAT.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:7510c1e2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->
