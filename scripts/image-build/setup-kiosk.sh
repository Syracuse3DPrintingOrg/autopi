#!/usr/bin/env bash
# Install a minimal full-screen kiosk display for AutoPi.
#
# On Raspberry Pi OS Lite there is no desktop, so this installs a tiny Wayland
# kiosk (the cage compositor) plus Chromium and a systemd service that shows the
# AutoPi operator screen full screen on the attached display. Touch input works
# out of the box. This is deliberately minimal; a richer kiosk (rotation, idle
# blanking, on-screen keyboard) can layer on top later.
#
# Run as root on a Pi appliance with a display attached.
set -euo pipefail

# /operator is the large-touch bench view (see services/ui_mode.py); the
# request also comes from loopback on the Pi itself, so it lands there even
# without the query string, but ?kiosk=1 makes the choice explicit and latches
# it for any link the operator screen itself points at.
URL="${KIOSK_URL:-http://127.0.0.1:9284/operator?kiosk=1}"
RUN_USER="${RUN_USER:-${SUDO_USER:-$(id -un 1000 2>/dev/null || echo pi)}}"

# Kiosk hardening (all optional, default to today's behavior):
#   KIOSK_ROTATION     0 | 90 | 180 | 270  (display rotation)
#   KIOSK_IDLE_MINUTES 0 disables; N blanks the screen after N idle minutes,
#                      waking on touch
#   KIOSK_KEYBOARD     0 | 1  (show an on-screen keyboard for text fields)
KIOSK_ROTATION="${KIOSK_ROTATION:-0}"
KIOSK_IDLE_MINUTES="${KIOSK_IDLE_MINUTES:-0}"
KIOSK_KEYBOARD="${KIOSK_KEYBOARD:-0}"

echo "Installing the kiosk display stack (cage + chromium)"
DEBIAN_FRONTEND=noninteractive apt-get install -y -q cage seatd \
  || { echo "cage/seatd not available in this distro; kiosk not installed." >&2; exit 1; }

# Chromium is packaged as chromium on Pi OS / Debian and chromium-browser on
# some Ubuntu builds. Install whichever is available.
CHROMIUM=""
if DEBIAN_FRONTEND=noninteractive apt-get install -y -q chromium; then
  CHROMIUM="chromium"
elif DEBIAN_FRONTEND=noninteractive apt-get install -y -q chromium-browser; then
  CHROMIUM="chromium-browser"
else
  echo "Could not install Chromium; kiosk not installed." >&2
  exit 1
fi

# Optional hardening helpers (wlroots-compatible). Best-effort: the kiosk still
# runs if a distro lacks one, the matching feature just stays off.
DEBIAN_FRONTEND=noninteractive apt-get install -y -q wlr-randr swayidle wlopm wvkbd \
  2>/dev/null || echo "Some kiosk hardening tools were unavailable; features needing them stay off." >&2

systemctl enable seatd 2>/dev/null || true
systemctl start seatd 2>/dev/null || true
groupadd -f seat
usermod -aG seat,video,input "${RUN_USER}" || true

echo "Writing the kiosk launch wrapper"
cat > /usr/local/bin/autopi-kiosk-launch <<'LAUNCH'
#!/usr/bin/env bash
# Runs inside the cage (wlroots) session: apply rotation, start idle blanking and
# an on-screen keyboard if configured, then exec the browser. Each step is
# best-effort so a missing tool never stops the kiosk from painting.
set -u
OUT="$(wlr-randr 2>/dev/null | awk 'NR==1{print $1}')"
case "${KIOSK_ROTATION:-0}" in
  90|180|270) [ -n "$OUT" ] && wlr-randr --output "$OUT" --transform "${KIOSK_ROTATION}" 2>/dev/null || true ;;
  *) [ -n "$OUT" ] && wlr-randr --output "$OUT" --transform normal 2>/dev/null || true ;;
esac
if [ "${KIOSK_IDLE_MINUTES:-0}" -gt 0 ] 2>/dev/null; then
  SECS=$(( KIOSK_IDLE_MINUTES * 60 ))
  swayidle -w timeout "$SECS" 'wlopm --off \*' resume 'wlopm --on \*' >/dev/null 2>&1 &
fi
if [ "${KIOSK_KEYBOARD:-0}" = "1" ]; then
  wvkbd-mobintl -L 240 >/dev/null 2>&1 &
fi
exec "$@"
LAUNCH
chmod +x /usr/local/bin/autopi-kiosk-launch

echo "Writing the kiosk service (user ${RUN_USER}, url ${URL})"
cat > /etc/systemd/system/autopi-kiosk.service <<EOF
[Unit]
Description=AutoPi kiosk display
After=autopi.service seatd.service
Wants=seatd.service

[Service]
User=${RUN_USER}
PAMName=login
TTYPath=/dev/tty7
# Wait for the app to answer before painting, so the first frame is the menu.
ExecStartPre=/bin/sh -c 'for i in \$(seq 1 60); do curl -fsS ${URL} >/dev/null 2>&1 && exit 0; sleep 2; done; exit 0'
Environment=KIOSK_ROTATION=${KIOSK_ROTATION}
Environment=KIOSK_IDLE_MINUTES=${KIOSK_IDLE_MINUTES}
Environment=KIOSK_KEYBOARD=${KIOSK_KEYBOARD}
ExecStart=/usr/bin/cage -- /usr/local/bin/autopi-kiosk-launch ${CHROMIUM} --kiosk --noerrdialogs --disable-infobars --incognito ${URL}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable autopi-kiosk.service
systemctl start autopi-kiosk.service || \
  echo "Kiosk enabled; it will start on the next boot with a display attached."
echo "Kiosk display installed."
