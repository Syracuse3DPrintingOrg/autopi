#!/usr/bin/env bash
# Install the AutoPi Stream Deck controller as a systemd service.
#
# Copies the controller package to /opt/autopi/streamdeck, installs its Python
# dependencies into a venv, adds the udev rule so the controller can claim the
# deck without root, and enables a service that runs it against the local app.
#
# Run as root on a Pi appliance. Ported from the source project's Stream Deck
# provisioning with the branding changed.
set -euo pipefail

# The repo checkout this script lives in (scripts/image-build -> repo root).
REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
INSTALL_DIR="/opt/autopi/streamdeck"
VENV_DIR="/opt/autopi/streamdeck-venv"
# The user the controller runs as (needs to be in plugdev). Defaults to the
# account that invoked sudo, falling back to the first regular login user.
RUN_USER="${RUN_USER:-${SUDO_USER:-$(id -un 1000 2>/dev/null || echo pi)}}"

echo "Installing the Stream Deck driver system dependencies"
DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
  python3 python3-venv python3-pip libhidapi-libusb0 libjpeg-dev zlib1g-dev

echo "Copying the controller to ${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"
cp -rf "${REPO_DIR}/streamdeck/autopi_streamdeck" "${INSTALL_DIR}/"
cp -f "${REPO_DIR}/streamdeck/requirements.txt" "${INSTALL_DIR}/"

echo "Creating the Python environment"
python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install -q --upgrade pip
"${VENV_DIR}/bin/pip" install -q -r "${INSTALL_DIR}/requirements.txt"

echo "Installing the udev rule and adding ${RUN_USER} to plugdev"
cp -f "${REPO_DIR}/streamdeck/udev/99-streamdeck.rules" /etc/udev/rules.d/
udevadm control --reload-rules && udevadm trigger || true
groupadd -f plugdev
usermod -aG plugdev "${RUN_USER}" || true

echo "Writing the systemd service"
cat > /etc/systemd/system/autopi-streamdeck.service <<EOF
[Unit]
Description=AutoPi Stream Deck controller
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
Group=plugdev
WorkingDirectory=${INSTALL_DIR}
Environment=AUTOPI_BASE_URL=http://127.0.0.1:9284
ExecStart=${VENV_DIR}/bin/python -m autopi_streamdeck
# on-failure only: the controller recovers an unplugged deck in-process, so
# systemd is just the backstop for a hard crash.
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now autopi-streamdeck.service || \
  echo "Service enabled; it will start once a deck is attached and the app is up."
echo "Stream Deck controller installed (running as ${RUN_USER})."
