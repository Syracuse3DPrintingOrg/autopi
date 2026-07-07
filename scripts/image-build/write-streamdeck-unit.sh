#!/usr/bin/env bash
# (Re)write the autopi-streamdeck systemd unit.
#
# Regenerating the unit on update is what lets an already-installed device pick
# up unit changes (StartLimitIntervalSec=0 so systemd never gives up on the
# deck, and AUTOPI_DATA_DIR so the controller reads its layout from local files
# and keeps its keys across an app restart). Preserves the existing run user.
# Idempotent; used by setup-streamdeck.sh and by autopi-update.
#
#   write-streamdeck-unit.sh [REPO_DIR]
set -euo pipefail

REPO_DIR="${1:-/opt/autopi-src}"
INSTALL_DIR="/opt/autopi/streamdeck"
VENV_DIR="/opt/autopi/streamdeck-venv"
UNIT="/etc/systemd/system/autopi-streamdeck.service"

# Preserve the run user from an existing unit; otherwise the sudo user, else pi.
RUN_USER="${RUN_USER:-}"
if [ -z "$RUN_USER" ] && [ -f "$UNIT" ]; then
  RUN_USER="$(sed -n 's/^User=//p' "$UNIT" | head -1)"
fi
RUN_USER="${RUN_USER:-${SUDO_USER:-$(id -un 1000 2>/dev/null || echo pi)}}"

cat > "$UNIT" <<EOF
[Unit]
Description=AutoPi Stream Deck controller
After=network-online.target docker.service
Wants=network-online.target
# The controller recovers a lost deck in-process; never give up after a burst.
StartLimitIntervalSec=0

[Service]
Type=simple
User=${RUN_USER}
Group=plugdev
WorkingDirectory=${INSTALL_DIR}
Environment=AUTOPI_BASE_URL=http://127.0.0.1:9284
Environment=AUTOPI_DATA_DIR=${REPO_DIR}/service/data
ExecStart=${VENV_DIR}/bin/python -m autopi_streamdeck
# on-failure only: the controller recovers an unplugged deck in-process.
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
echo "Wrote ${UNIT} (User=${RUN_USER}, data_dir=${REPO_DIR}/service/data)"
