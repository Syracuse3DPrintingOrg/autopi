# AutoPi Roadmap

## Phase 1: the control surface

Goal: a flexible controller that runs on Raspberry Pi Lite and on a server.

- Web interface with internet access and a Wi-Fi access point fallback for
  standalone use.
- A full-screen start menu and an optional Stream Deck that share one layout,
  so the same shortcuts drive the touchscreen and the physical keys.
- A library of user-defined actions that perform functions and can be tied to
  external applications:
  - **gpio**: toggle, set, or pulse a pin.
  - **shell**: run a command (optionally with arguments and a timeout).
  - **http**: call another application (method, URL, headers, body).
  - **macro**: run several actions in order.
  - **builtin**: page navigation, brightness, clock, and other surface
    controls.
- A drag-and-drop editor for both the start menu and the Stream Deck.
- Host-only. No thin-client / satellite mode. Runs on a server as well as a
  Pi.
- All relevant drivers bundled: the Stream Deck driver, GPIO access, and the
  kiosk display plumbing.

### Phase 1 status

Foundation in place: FastAPI app, the action registry with gpio / shell / http
/ macro / builtin drivers (each degrading gracefully with no hardware), the
shared layout model and its pure paging/rotation math, the start-menu page, the
layout editor API, and the Stream Deck controller skeleton. Wi-Fi AP and kiosk
provisioning are ported from the proven device scripts.

Still to build out: the full layout-editor UI polish, per-driver setup forms,
Stream Deck key-face rendering parity, and the on-device installer end to end.

## Phase 2: automotive CAN

Goal: talk to a vehicle's CAN environment through a CAN HAT.

- Support multiple CAN HATs, with the **Waveshare 2-Channel CAN-FD HAT** as the
  first target. That board carries two MCP2518FD controllers on SPI; on
  Raspberry Pi OS they are brought up as SocketCAN interfaces (`can0`, `can1`)
  after enabling the `mcp251xfd` overlay in `/boot/config.txt` and setting the
  bitrate with `ip link`.
- A `can` driver (placeholder already present in
  `service/app/actions/drivers/can.py`) built on `python-can` with the
  `socketcan` backend: send a frame, send an ISO-TP request, or watch an id and
  react.
- Actions that send CAN frames or request diagnostic (OBD-II / UDS) data, bound
  to keys like any other action.
- Bus configuration (interface, bitrate, data bitrate for CAN-FD, sample point)
  in the setup page, with a live bus monitor on the kiosk screen.

CAN work is gated on Phase 1 landing. Do not start it before the control
surface is solid on real hardware.
