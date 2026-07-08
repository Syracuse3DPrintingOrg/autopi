# Kiosk display

On a Raspberry Pi appliance, AutoPi shows the operator screen full screen on the
attached display through a minimal Wayland kiosk (the cage compositor plus
Chromium). Install it on the device with:

```
sudo bash scripts/image-build/setup-kiosk.sh
```

## Hardening options

These are optional and off by default, so the kiosk behaves exactly as before
unless you set them. Pass them as environment variables to the installer, or set
them in the flashed image config, then re-run the installer:

- `KIOSK_ROTATION` (0, 90, 180, 270): rotate the display, for a portrait mount or
  an upside-down panel.
- `KIOSK_IDLE_MINUTES` (0 disables): blank the screen after this many idle
  minutes and wake it on the next touch, to save the panel and power.
- `KIOSK_KEYBOARD` (0 or 1): show an on-screen keyboard so text fields can be
  filled on a touch-only bench.

Each option relies on a small wlroots helper (wlr-randr, swayidle plus wlopm, and
wvkbd). The installer pulls them in when the distribution has them; if one is
missing, the kiosk still runs and only that option stays off.

These display features depend on the exact panel and mount, so confirm rotation,
blanking, and the keyboard on the actual hardware after install.
