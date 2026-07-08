# Changelog

All notable changes to AutoPi are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project follows
semantic versioning while pre-1.0 (staying in `0.x`).

## [Unreleased]

### Added

- **Join Wi-Fi from the Network settings page.** On a Raspberry Pi appliance,
  the Network pane now shows the current connection and lets you scan for
  nearby networks and join one with a password, without opening a terminal.

### Fixed

- **The fallback hotspot now actually serves the app.** Connecting to the
  AutoPi setup hotspot and opening `http://192.168.99.1` used to fail,
  because nothing was listening on the plain web port. The hotspot now
  forwards that address straight to the app, so it opens without typing a
  port number.
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
