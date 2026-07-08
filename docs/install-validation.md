# Installer validation checklist (on real Pi hardware)

The installer scripts pass static checks (shell syntax on every `.sh`, and the
Python host bridge compiles). What can only be proven on a real Raspberry Pi is
the end-to-end run. Use this checklist on a freshly flashed Pi OS Lite device.

## Fresh install (pi_hosted)

1. Flash Pi OS Lite, boot, and run the one-liner:
   `curl -fsSL https://raw.githubusercontent.com/Syracuse3DPrintingOrg/autopi/main/install.sh | bash`
2. The mode prompt appears and accepts input over the piped shell; choose the Pi
   appliance mode.
3. Docker installs, `docker compose up -d --build` completes, and the app answers
   on `http://<pi>:9284/health` with `app=autopi`.
4. The host bridge is up: `systemctl status autopi-host-bridge` active, and
   `curl -s 127.0.0.1:9299/health` reports `BRIDGE_VERSION` matching the app's
   `EXPECTED_BRIDGE_VERSION`.
5. With a display attached, the kiosk paints the operator screen; touch works.
6. With the Stream Deck attached, `autopi-streamdeck` renders key faces (icon,
   label, color) matching the on-screen layout.

## CAN hardware (Waveshare 2-Ch CAN-FD HAT)

7. `sudo bash /opt/autopi-src/scripts/image-build/setup-can-waveshare.sh` brings
   up `can0`/`can1`; the CAN Interfaces page shows them up with a bitrate.
8. Load a real vehicle sample (RAM 1500, Alfa Romeo Giulia, Ford F-150, Toyota,
   Honda, or Hyundai) and confirm the Monitor decodes real frames from a bus, and
   the interface self-test passes.

## Update and recovery

9. `autopi-update` re-execs, pulls, redeploys, and restarts the bridge and deck
   cleanly (the OTA landmine is exercised).
10. A settings change persists across a reboot; the data dir is writable.

## Kiosk hardening (optional, off by default)

11. Set `KIOSK_ROTATION` / `KIOSK_IDLE_MINUTES` / `KIOSK_KEYBOARD`, re-run the
    kiosk installer, and confirm rotation, idle blank + touch wake, and the
    on-screen keyboard on the actual panel.

Record any step that needs a device-specific tweak so the installer can absorb it.
