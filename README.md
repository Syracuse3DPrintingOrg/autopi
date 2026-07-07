# AutoPi

A blank-slate control surface for a Raspberry Pi or a server. Build your own
physical and on-screen controller by defining actions and dragging them onto a
start menu and a Stream Deck.

AutoPi turns a Raspberry Pi (with an optional Stream Deck and an optional
screen, touch or not) into a flexible controller for whatever you want to
drive: GPIO pins, shell commands, HTTP calls to other applications, and (soon)
automotive CAN bus messages. It runs standalone over its own Wi-Fi access
point or on your network, and it runs just as well on a plain server.

## What you get

- A web interface with a full-screen **start menu** of keys.
- Optional **Stream Deck** support (Mini, Original/MK.2, XL) that mirrors the
  same layout, with rotation.
- A **library of actions** you define once and reuse: toggle a GPIO pin, run a
  command, call another app over HTTP, or chain several into a macro.
- A **drag-and-drop editor** to arrange the start menu and the Stream Deck.
- Standalone **Wi-Fi access point** fallback so the device is reachable with
  no network present.

## Install on a Raspberry Pi

Flash Raspberry Pi OS Lite with Raspberry Pi Imager (set your Wi-Fi, hostname,
and locale there), boot, SSH in, and run one line:

```bash
curl -fsSL https://raw.githubusercontent.com/Syracuse3DPrintingOrg/autopi/main/install.sh | bash
```

It detects the Pi, a display, and a Stream Deck, installs Docker if needed,
brings up AutoPi, and on a Pi appliance also sets up the kiosk display, the
Stream Deck controller, and a Wi-Fi access point fallback. Then open
`http://<hostname>.local:9284`.

The same one-liner works on any Debian/Ubuntu server; it installs the stack
only (no kiosk, deck, or access point).

## Run it with Docker

On a machine that already has Docker:

```bash
docker compose up -d --build
```

Then open <http://localhost:9284>.

## Status

Phase 1 (GPIO / shell / HTTP control surface) is in active development. Phase 2
adds the automotive CAN environment through CAN HATs, starting with the
Waveshare 2-Channel CAN-FD HAT. See [docs/ROADMAP.md](docs/ROADMAP.md).
