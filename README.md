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

## Run it

```bash
docker compose up -d --build
```

Then open <http://localhost:9284>.

On a Raspberry Pi, `install.sh` provisions the appliance (kiosk display,
Stream Deck, Wi-Fi AP fallback).

## Status

Phase 1 (GPIO / shell / HTTP control surface) is in active development. Phase 2
adds the automotive CAN environment through CAN HATs, starting with the
Waveshare 2-Channel CAN-FD HAT. See [docs/ROADMAP.md](docs/ROADMAP.md).
