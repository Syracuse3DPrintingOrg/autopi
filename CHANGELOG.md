# Changelog

All notable changes to AutoPi are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project follows
semantic versioning while pre-1.0 (staying in `0.x`).

## [Unreleased]

### Added

- **Build and edit actions from the web UI, including vehicle commands.** A
  new Actions page (nav: Actions) lists every action and lets you create or
  edit one: pick a driver (GPIO, shell, HTTP, macro, or the new vehicle
  command), and the form adjusts to that driver's parameters. A new "vehicle
  command" driver sends a named CAN message: pick an imported database and
  message and set the signal values you want (for example, Volume Up), and it
  encodes and sends the frame for you; a raw arbitration id and data bytes
  still work for a one-off frame with no database. A Test button runs the
  action once and shows the result before you bind it to a key in the layout
  editor.

### Fixed

- **Wi-Fi and other host features no longer show a bare "not found" after an
  update.** The host-bridge is a long-running service, so replacing its file on
  disk during an update does not change the running process; if its restart did
  not fire, the old bridge kept serving and the new Wi-Fi routes returned 404.
  The updater now restarts the bridge reliably (with a fallback if systemd-run
  is unavailable, and it re-enables and clears any failed state), and the app
  now shows an actionable message ("the host-bridge is out of date, restart it")
  instead of "not found" when the bridge is behind.

### Fixed

- **Wi-Fi scan (and update, reboot, deck restart) now work on the Pi.** These
  said "Only available on a Raspberry Pi appliance" even on a real Pi, because
  the check ran inside the container, which cannot see the Pi's device-tree.
  They now gate on whether the host-bridge answers (the bridge does the work and
  only runs on a Pi appliance), which is the correct signal, and Pi detection
  also reads /proc/cpuinfo so it works from inside the container.

### Fixed

- **Stream Deck and start settings save reliably now.** Settings are re-read
  from disk on every request, so a saved rotation, brightness, model, or the
  start-page toggle no longer appears to revert (the settings object was loaded
  once at startup, so a second worker process could serve stale values). The
  health page now also reports the data directory and whether it is writable, to
  make a stuck save easy to diagnose.

### Fixed

- **The Stream Deck keeps its keys through an update, and recovers on its own.**
  The controller now reads its key layout straight from the app's data files on
  the device, so a deck no longer blanks or loses its keys while the app
  container restarts during an update, the way it did before. Combined with the
  in-process recovery, a plugged-in deck reconnects by itself. Updating a device
  also rewrites the deck's service so a previous crash loop can no longer wedge
  it: the service is told never to give up, and its failed state is cleared on
  update.

- **Changing keys no longer wedges the Stream Deck.** The controller only
  caught network errors, so a transient USB write failure while repainting the
  new layout crashed the process, and systemd relaunched it straight back into
  the same crash, which is why a manual restart did not recover it. The loop now
  never exits on a deck or paint error: it re-opens the deck in-process (like
  the source project), paints defensively per key, and its service never gives
  up after a burst of restarts.

- **Updating a device now actually applies host-side fixes.** The OTA updater
  overwrote itself but kept running the old copy, so changes to the updater (like
  GPIO passthrough) never took effect on the update that shipped them. It now
  re-executes the fresh copy after pulling, syncs the Stream Deck controller and
  the compose override separately from the Docker image (the image never carries
  them), recovers a diverged checkout, and reports whether anything changed. This
  is why the Stream Deck and GPIO fixes did not take on the last update.
- **The Stream Deck controller now actually runs.** It was importing the app's
  paging code from a path that does not exist once the controller is installed
  on its own, so it crashed on startup and never connected. The controller is
  now fully self-contained, like the source project's, so a plugged-in deck
  comes up and shows your layout.
- **GPIO keys work on the start menu and the deck.** The demo lamp, fan, and
  door keys did nothing because the app runs in a container with no access to
  the Pi's GPIO and no pin backend installed. The installer (and updater) now
  map the board's GPIO devices into the container and the image ships the lgpio
  backend, so GPIO actions drive real pins. A blank start page left over from
  an earlier build now re-seeds its demo keys on update.
- **Stream Deck rotation, brightness, and Restart now work from the web
  editor.** The app runs in a container and cannot restart the host service, so
  Restart used to report "No Stream Deck service on this host." The controller
  now pulls the rotation and brightness you set in the editor on each check and
  applies them to a live deck without a restart, and Restart is a request the
  controller honors by reconnecting itself. When a deck is connected, Restart
  reports "Reconnecting the Stream Deck."

### Added

- **Vehicles, CAN simulation, and Wi-Fi configuration.** Three more sections of
  the platform go live. **Vehicles**: create vehicle test profiles (year, make,
  model, one or more VINs) and pick an active one; Stellantis **Atlantis High**
  and **Atlantis Mid** are seeded to start from (infotainment focus).
  **Simulate**: a CAN transmit list of periodic (cyclic) and one-shot frames,
  each raw hex or encoded from a DBC signal set, with a scheduler you start and
  stop. **Wi-Fi**: the Network settings pane scans for networks and joins one
  (on a Pi appliance), and the fallback access point now actually serves the
  app (a captive redirect sends `http://192.168.99.1` to the app), fixing the
  hotspot that reached nothing before.

- **The platform is now visible and usable in the app, not just the API.** New
  top-nav sections put the tools one click away: a **CAN** console and an
  **Automation** page. The CAN console lists your imported CAN databases,
  uploads a DBC file or bulk-imports opendbc, browses each database's messages
  and signals, and decodes a raw frame into named values or encodes signal
  values and sends them, plus a raw-frame sender and live interface status. The
  Automation page lists your logic rules and does database backup and restore
  (download the whole database as a file, import it back without wiping data).
  Settings now links across to CAN, Automation, and the layout editor.

- **Import open-source CAN databases (DBC), and decode/encode frames.** AutoPi
  now speaks DBC, the format the open-source CAN world ships its message and
  signal definitions in. Upload any DBC file, or pull comma.ai's opendbc
  collection (the largest open set of vehicle databases) onto a device with
  `scripts/import-opendbc.sh`. Each imported database is stored locally with its
  messages and signals, and records where it came from and under what license,
  so open-source content stays attributable. Frames decode into named signal
  values and encode back, built on the cantools library. New endpoints under
  `/can` list databases and decode/encode. A LICENSING.md now tracks every
  dependency's license and what it means for shipping AutoPi as a proprietary
  product (notably python-can under the LGPL, and that CAN database content
  carries its own licenses separate from the code).

- **Phase 2 foundations: a database, a CAN core, and a logic engine.** Three
  building blocks toward turning AutoPi into a full test and automation
  platform. A locally-hosted SQLite database (under the data directory) stores
  actions, vehicle profiles, CAN message/signal definitions, and logic rules,
  with whole-database and per-profile import and export at `/db/export` and
  `/db/import`. A CAN core built on python-can with a backend-independent frame
  model and provider abstraction: the socketcan backend and a bring-up script
  for the Waveshare 2-Channel CAN-FD HAT (`can0`/`can1`) are in, and the CAN
  action now sends real frames when an interface is present and simulates
  otherwise. A PLC-like logic engine evaluates rules (comparisons, boolean
  inputs, rising/falling edges, on-delay and off-delay timers, set-reset
  latches, combined with AND/OR/NOT) on a fixed scan cycle, viewable at
  `/logic/rules`. Each is pure and heavily tested; wiring them together (rules
  driven by CAN signals, DB-backed actions, vehicle profiles) follows.

- **Raspberry Pi appliance platform (host-bridge + appliance compose).**
  Following the Pi appliance blueprint, a small root helper (the host-bridge on
  127.0.0.1:9299) now performs the privileged host operations the container
  cannot: OTA update, reboot, restarting the Stream Deck service, and reading Pi
  power/thermal/disk health. The app runs with host networking on a Pi so it can
  reach the bridge, relays those operations to it with a shared token, and
  degrades to a clean no-op on a plain server.
- **Visual Stream Deck and Start Page editor.** Drag keys from a categorized
  library onto a deck-shaped grid. The grid scales to the selected model (Mini
  6, MK.2 15, XL 32) or, when a Stream Deck is plugged in and its controller is
  running, to the real deck automatically. Rotation reshapes the grid, and a
  layout longer than the deck paginates with a wrapping "More" key. Set the
  model, rotation, and brightness, then save the deck settings and both layouts
  at once. A connected badge shows which deck reported in.
- **A real interface, matching the look and feel it was spun out from.** The
  start menu, layout editor, and settings now use the same Bootstrap dark theme
  and icons, with a blue accent. The settings page is a sectioned menu
  (Appearance, Start Page & Stream Deck, Display & Kiosk, Network, Actions,
  Home Assistant, Security, Updates, Advanced) with search, one click to any
  section. A fresh install seeds a handful of demo keys (a lamp, a fan, a door
  pulse, a ping, a status check, a webhook, and an "all on" macro) onto both
  the start menu and the Stream Deck so the grid is populated out of the box.
- **On-device updater.** `autopi-update` pulls the latest source, rebuilds the
  stack, and refreshes the Stream Deck controller, run over SSH.
- **One-line install on a Raspberry Pi.** Flash Raspberry Pi OS Lite, SSH in,
  and run a single `curl ... | bash` line. It detects the Pi, a display, and a
  Stream Deck, installs Docker if needed, brings up AutoPi, and on a Pi
  appliance also sets up the kiosk display, the Stream Deck controller, and a
  Wi-Fi access point fallback. The same line installs the stack on a plain
  Debian or Ubuntu server.
- **First cut of the AutoPi control surface.** A web start menu and an
  optional Stream Deck share one layout of keys. Each key runs an action you
  define: toggle or pulse a GPIO pin, run a shell command, or call another
  application over HTTP. Arrange the keys by dragging them in the layout
  editor. The app runs standalone over its own Wi-Fi access point or on your
  network, and on a plain server with no Pi attached (the hardware drivers
  no-op cleanly when there is nothing to drive).
