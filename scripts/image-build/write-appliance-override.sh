#!/usr/bin/env bash
# Select the Raspberry Pi appliance compose and map this board's GPIO.
#
# On a Pi it writes:
#   - docker-compose.override.yml with the gpio device nodes that actually
#     exist (they differ across Pi models), and
#   - a .env line setting COMPOSE_FILE so the plain `docker compose up` in the
#     installer and updater uses the appliance file (network_mode: host, serves
#     on :9284) plus the gpio override.
#
# The appliance file cannot live as a plain override on docker-compose.yml
# because Docker refuses a published port together with network_mode: host, so
# it is a complete separate file selected via COMPOSE_FILE. No-op off a Pi.
# Idempotent.
#
#   write-appliance-override.sh [REPO_DIR]
set -uo pipefail

REPO_DIR="${1:-/opt/autopi-src}"

is_pi=false
for f in /proc/device-tree/model /sys/firmware/devicetree/base/model; do
  [ -r "$f" ] && tr -d '\0' <"$f" | grep -qi 'raspberry pi' && is_pi=true
done
if [ "$is_pi" != true ]; then
  echo "Not a Raspberry Pi; leaving the default server compose in place."
  exit 0
fi

devs=()
for d in /dev/gpiomem /dev/gpiomem0 /dev/gpiochip0 /dev/gpiochip4; do
  [ -e "$d" ] && devs+=("$d")
done

compose_files="docker-compose.appliance.yml"
override="$REPO_DIR/docker-compose.override.yml"
if [ "${#devs[@]}" -gt 0 ]; then
  {
    echo "# Generated: GPIO passthrough for this Pi (merged over the appliance file)."
    echo "services:"
    echo "  autopi:"
    echo "    devices:"
    for d in "${devs[@]}"; do echo "      - \"$d:$d\""; done
  } > "$override"
  compose_files="${compose_files}:docker-compose.override.yml"
else
  rm -f "$override"
fi

# Point docker compose at the appliance file(s). Preserve any other .env lines.
env_file="$REPO_DIR/.env"
touch "$env_file"
grep -v '^COMPOSE_FILE=' "$env_file" > "$env_file.tmp" 2>/dev/null || true
mv -f "$env_file.tmp" "$env_file"
echo "COMPOSE_FILE=${compose_files}" >> "$env_file"

echo "Appliance compose selected (COMPOSE_FILE=${compose_files}); gpio: ${devs[*]:-none}"
