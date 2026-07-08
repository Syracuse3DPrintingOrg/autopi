#!/usr/bin/env bash
# Install the AutoPi host-bridge: the root helper the container calls for
# privileged host operations (OTA update, reboot, Stream Deck restart, health).
#
# Run as root on a Pi appliance. Installs the bridge to /usr/local/sbin and a
# systemd unit that runs it as root on 127.0.0.1:9299, with the token written
# into the app's data dir so the container reads the same file.
set -euo pipefail

REPO_DIR="${1:-/opt/autopi-src}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TOKEN_PATH="${REPO_DIR}/service/data/bridge-token"

install -m 755 "${HERE}/autopi-host-bridge" /usr/local/sbin/autopi-host-bridge
mkdir -p "$(dirname "${TOKEN_PATH}")"

cat > /etc/systemd/system/autopi-host-bridge.service <<EOF
[Unit]
Description=AutoPi host-bridge (root helper on 127.0.0.1:9299)
After=network.target

[Service]
Type=simple
Environment=AUTOPI_REPO_DIR=${REPO_DIR}
Environment=AUTOPI_BRIDGE_TOKEN_PATH=${TOKEN_PATH}
ExecStart=/usr/bin/python3 /usr/local/sbin/autopi-host-bridge
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable autopi-host-bridge.service
# restart, not just enable --now: when re-running this to update an already
# running bridge, enable --now would leave the old daemon (and old version)
# in place. reset-failed clears any prior crash-loop state first.
systemctl reset-failed autopi-host-bridge.service 2>/dev/null || true
systemctl restart autopi-host-bridge.service
echo "Host-bridge installed and listening on 127.0.0.1:9299 (token: ${TOKEN_PATH})."
