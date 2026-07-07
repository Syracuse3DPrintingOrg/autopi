#!/usr/bin/env bash
# AutoPi on-device installer (skeleton).
#
# Run this ON the device (a Raspberry Pi, or any Debian/Ubuntu box). It brings
# up the AutoPi stack with Docker Compose and, on a Pi, can install the Wi-Fi
# fallback access point and the Stream Deck controller.
#
# This is a Phase 1 skeleton: it wires up the pieces that exist today and
# leaves clearly marked TODOs for the kiosk display and the full first-boot
# flow, which land as the appliance provisioning is fleshed out.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
ENABLE_AP="${ENABLE_AP:-0}"
ENABLE_STREAMDECK="${ENABLE_STREAMDECK:-0}"

echo "AutoPi installer"
echo "Repo: ${REPO_DIR}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Install Docker Engine + Compose plugin, then re-run."
  exit 1
fi

echo "Bringing up the AutoPi stack"
( cd "${REPO_DIR}" && docker compose up -d --build )
echo "AutoPi is running on http://localhost:9284"

if [ "${ENABLE_AP}" = "1" ]; then
  echo "Installing the Wi-Fi fallback access point (needs root)"
  sudo "${REPO_DIR}/scripts/image-build/setup-wifi-ap.sh"
fi

if [ "${ENABLE_STREAMDECK}" = "1" ]; then
  echo "Installing the Stream Deck controller"
  pip3 install -r "${REPO_DIR}/streamdeck/requirements.txt"
  echo "TODO: copy streamdeck/ to /opt/autopi/streamdeck and enable"
  echo "      streamdeck/systemd/autopi-streamdeck.service"
fi

# TODO (Phase 1 appliance): kiosk display service (chromium in kiosk mode
# pointed at http://localhost:9284/start), udev rule for Stream Deck hotplug.
echo "Done."
