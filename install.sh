#!/usr/bin/env bash
# AutoPi on-device installer (loader)
# ===================================
# Run this ON the device (a freshly flashed Raspberry Pi OS Lite, or any
# Debian/Ubuntu box) over SSH. It detects the hardware, then installs only what
# that device needs.
#
#   curl -fsSL https://raw.githubusercontent.com/Syracuse3DPrintingOrg/autopi/main/install.sh | bash
#
# There is nothing to edit on your PC and no repo to clone on your PC. Flash the
# card with Raspberry Pi Imager (set wifi/hostname/locale there), boot, SSH in,
# and run the line above.
#
# What it does:
#   1. Detects whether this is a Raspberry Pi, and whether a display and/or a
#      Stream Deck are attached right now.
#   2. Asks for the deployment mode.
#   3. Fetches the repo to the device, installs Docker if needed, and brings up
#      the AutoPi stack. On a Pi appliance it also installs the Wi-Fi fallback
#      access point, the Stream Deck controller, and a kiosk display, based on
#      what is attached.
#
# Modes:
#   pi_hosted  - full appliance on this Pi (AutoPi stack + optional kiosk and
#                Stream Deck + Wi-Fi AP fallback).
#   server     - the AutoPi stack on a general Debian/Ubuntu host (no kiosk,
#                deck, or AP provisioning).
#
# Non-interactive use (CI, scripted installs): set NONINTERACTIVE=1 and pass the
# choices as env vars (DEPLOYMENT_MODE, ENABLE_KIOSK, ENABLE_STREAMDECK,
# ENABLE_AP, HOSTNAME). PLAN_ONLY=1 prints the resolved plan and exits without
# cloning, using sudo, or provisioning (used by tests).
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Syracuse3DPrintingOrg/autopi.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
# Where the repo is checked out ON THE DEVICE (never on the user's PC).
REPO_DIR="${REPO_DIR:-/opt/autopi-src}"

NONINTERACTIVE="${NONINTERACTIVE:-0}"
PLAN_ONLY="${PLAN_ONLY:-0}"

# -- pretty output ------------------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_CYAN=$'\033[1;36m'; C_GREEN=$'\033[1;32m'; C_YELLOW=$'\033[1;33m'
  C_RED=$'\033[1;31m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
  C_CYAN=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_DIM=""; C_OFF=""
fi
say()  { printf '%s==>%s %s\n' "$C_CYAN" "$C_OFF" "$*"; }
ok()   { printf '%s[ok]%s %s\n' "$C_GREEN" "$C_OFF" "$*"; }
warn() { printf '%s[!]%s %s\n' "$C_YELLOW" "$C_OFF" "$*" >&2; }
die()  { printf '%sError:%s %s\n' "$C_RED" "$C_OFF" "$*" >&2; exit 1; }
hr()   { printf '%s----------------------------------------%s\n' "$C_DIM" "$C_OFF"; }

# -- interactive helpers (read from the terminal, not stdin) ------------------
# When invoked as `curl ... | bash`, stdin is the script itself, so prompts must
# read from /dev/tty.
TTY="/dev/tty"
have_tty() { [ -e "$TTY" ] && { : >/dev/null 2>&1 <"$TTY"; }; }

prompt_yn() {  # prompt default(y|n) -> 0 for yes, 1 for no
  local prompt="$1" def="$2" hint ans
  case "$def" in y|Y) hint="[Y/n]";; *) hint="[y/N]";; esac
  while :; do
    printf '%s%s %s%s ' "$C_CYAN" "$prompt" "$hint" "$C_OFF" >"$TTY"
    IFS= read -r ans <"$TTY" || ans=""
    ans="${ans:-$def}"
    case "$ans" in
      y|Y|yes|YES) return 0 ;;
      n|N|no|NO)   return 1 ;;
      *) printf '  Please answer y or n.\n' >"$TTY" ;;
    esac
  done
}

prompt_choice() {  # title; then "key:label" pairs in $@ ; echoes chosen key
  local title="$1"; shift
  local -a keys=() labels=()
  local pair
  for pair in "$@"; do keys+=("${pair%%:*}"); labels+=("${pair#*:}"); done
  printf '%s%s%s\n' "$C_CYAN" "$title" "$C_OFF" >"$TTY"
  local i
  for i in "${!keys[@]}"; do printf '  %s) %s\n' "$((i+1))" "${labels[$i]}" >"$TTY"; done
  while :; do
    local sel
    printf '%sChoose 1-%s [1]:%s ' "$C_CYAN" "${#keys[@]}" "$C_OFF" >"$TTY"
    IFS= read -r sel <"$TTY" || sel=""
    sel="${sel:-1}"
    if [[ "$sel" =~ ^[0-9]+$ ]] && [ "$sel" -ge 1 ] && [ "$sel" -le "${#keys[@]}" ]; then
      printf '%s' "${keys[$((sel-1))]}"; return 0
    fi
    printf '  Enter a number between 1 and %s.\n' "${#keys[@]}" >"$TTY"
  done
}

# -- hardware detection -------------------------------------------------------
is_raspberry_pi() {
  [ -n "${FORCE_PI:-}" ] && return 0
  local f
  for f in /proc/device-tree/model /sys/firmware/devicetree/base/model; do
    [ -r "$f" ] && tr -d '\0' <"$f" | grep -qi 'raspberry pi' && return 0
  done
  return 1
}
has_display() {
  [ -n "${FORCE_DISPLAY:-}" ] && return 0
  [ -e /dev/dri/card0 ] && return 0
  [ -n "${WAYLAND_DISPLAY:-}" ] && return 0
  [ -n "${DISPLAY:-}" ] && return 0
  return 1
}
has_streamdeck() {
  [ -n "${FORCE_STREAMDECK:-}" ] && return 0
  if command -v lsusb >/dev/null 2>&1; then
    lsusb 2>/dev/null | grep -qi '0fd9:' && return 0
  fi
  grep -qil '0fd9' /sys/bus/usb/devices/*/idVendor 2>/dev/null && return 0
  return 1
}
board_model() {
  local f
  for f in /proc/device-tree/model /sys/firmware/devicetree/base/model; do
    [ -r "$f" ] && { tr -d '\0' <"$f"; return; }
  done
  echo "unknown"
}
yesno() { case "$1" in true|TRUE|1|yes|on) echo true;; *) echo false;; esac; }

# -- gather configuration -----------------------------------------------------
IS_PI=false; is_raspberry_pi && IS_PI=true
HAS_DISPLAY=false; has_display && HAS_DISPLAY=true
HAS_DECK=false; has_streamdeck && HAS_DECK=true

DEPLOYMENT_MODE="${DEPLOYMENT_MODE:-}"
ENABLE_KIOSK="${ENABLE_KIOSK:-}"
ENABLE_STREAMDECK="${ENABLE_STREAMDECK:-}"
ENABLE_AP="${ENABLE_AP:-}"
HOSTNAME_CHOICE="${HOSTNAME:-$(hostname 2>/dev/null || echo autopi)}"

banner() {
  hr
  printf '%s  AutoPi installer%s\n' "$C_GREEN" "$C_OFF"
  hr
  if [ "$IS_PI" = true ]; then say "Device: $(board_model)"; else say "Device: non-Pi host ($(uname -m))"; fi
  say "Display attached:     $([ "$HAS_DISPLAY" = true ] && echo yes || echo no)"
  say "Stream Deck attached: $([ "$HAS_DECK" = true ] && echo yes || echo no)"
  hr
}

resolve_config() {
  # Mode.
  if [ -z "$DEPLOYMENT_MODE" ]; then
    if [ "$IS_PI" = true ]; then
      if [ "$NONINTERACTIVE" = "1" ]; then
        DEPLOYMENT_MODE="pi_hosted"
      else
        have_tty || die "No terminal for prompts. Run over SSH, or set NONINTERACTIVE=1 with the choices as env vars (see the header of this script)."
        DEPLOYMENT_MODE="$(prompt_choice "How will this device be used?" \
          "pi_hosted:Pi appliance  - run AutoPi on this Pi, with kiosk / Stream Deck / Wi-Fi AP" \
          "server:Server only   - just run the AutoPi stack (no kiosk, deck, or AP)")"
      fi
    else
      DEPLOYMENT_MODE="server"
    fi
  fi
  # Appliance add-ons: default from attached hardware on a Pi appliance, always
  # off on a plain server.
  if [ "$DEPLOYMENT_MODE" = "pi_hosted" ]; then
    [ -z "$ENABLE_KIOSK" ]      && ENABLE_KIOSK="$([ "$HAS_DISPLAY" = true ] && echo true || echo false)"
    [ -z "$ENABLE_STREAMDECK" ] && ENABLE_STREAMDECK="$([ "$HAS_DECK" = true ] && echo true || echo false)"
    [ -z "$ENABLE_AP" ]         && ENABLE_AP="true"
  else
    ENABLE_KIOSK=false; ENABLE_STREAMDECK=false; ENABLE_AP=false
  fi
}

confirm_plan() {
  hr
  say "Install plan"
  printf '  Mode:        %s\n' "$DEPLOYMENT_MODE"
  printf '  Hostname:    %s\n' "$HOSTNAME_CHOICE"
  printf '  Kiosk:       %s\n' "$(yesno "$ENABLE_KIOSK")"
  printf '  Stream Deck: %s\n' "$(yesno "$ENABLE_STREAMDECK")"
  printf '  Wi-Fi AP:    %s\n' "$(yesno "$ENABLE_AP")"
  hr
}

# -- provisioning -------------------------------------------------------------
SUDO=""
need_root() {
  if [ "$(id -u)" -eq 0 ]; then SUDO=""; return; fi
  command -v sudo >/dev/null 2>&1 || die "This step needs root. Re-run as root or install sudo."
  SUDO="sudo"
}

fetch_repo() {
  say "Fetching AutoPi to $REPO_DIR (on this device)"
  if [ -d "$REPO_DIR/.git" ]; then
    if $SUDO git -C "$REPO_DIR" fetch --depth 1 origin "$REPO_BRANCH"; then
      $SUDO git -C "$REPO_DIR" reset --hard "origin/$REPO_BRANCH" \
        || warn "Fetched but could not fast-forward; using what is on disk."
    else
      warn "Could not update existing checkout; using what is on disk."
    fi
  else
    command -v git >/dev/null 2>&1 || { say "Installing git"; $SUDO apt-get update -y && $SUDO apt-get install -y git; }
    $SUDO git clone --depth 1 --branch "$REPO_BRANCH" "$REPO_URL" "$REPO_DIR" \
      || die "Could not clone $REPO_URL. Check internet access and try again."
  fi
  ok "Repo ready at $REPO_DIR"
}

install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    ok "Docker with the Compose plugin is already installed"
    return
  fi
  say "Installing Docker Engine and the Compose plugin"
  curl -fsSL https://get.docker.com | $SUDO sh || die "Docker install failed."
  # Let the login user run docker without sudo next time (takes effect on next login).
  [ -n "${SUDO_USER:-}" ] && $SUDO usermod -aG docker "$SUDO_USER" 2>/dev/null || true
  ok "Docker installed"
}

# Give the container access to the Pi's GPIO (writes docker-compose.override.yml
# mapping the board's gpio devices). Without it the GPIO driver runs simulated
# and keys like the demo lamp/fan do nothing.
configure_gpio_access() {
  $SUDO bash "$REPO_DIR/scripts/image-build/setup-gpio.sh" "$REPO_DIR" || true
}

bring_up_stack() {
  say "Building and starting the AutoPi stack (this can take a few minutes)"
  ( cd "$REPO_DIR" && $SUDO docker compose up -d --build ) || die "docker compose failed."
  ok "AutoPi is running on port 9284"
}

provision_appliance() {
  local ib="$REPO_DIR/scripts/image-build"
  if [ "$(yesno "$ENABLE_AP")" = true ]; then
    say "Installing the Wi-Fi fallback access point"
    $SUDO bash "$ib/setup-wifi-ap.sh" || warn "Wi-Fi AP setup failed; skipping."
  fi
  if [ "$(yesno "$ENABLE_STREAMDECK")" = true ]; then
    say "Installing the Stream Deck controller"
    $SUDO bash "$ib/setup-streamdeck.sh" || warn "Stream Deck setup failed; skipping."
  fi
  if [ "$(yesno "$ENABLE_KIOSK")" = true ]; then
    say "Installing the kiosk display"
    $SUDO bash "$ib/setup-kiosk.sh" || warn "Kiosk setup failed; skipping."
  fi
}

print_done() {
  hr
  ok "AutoPi installed."
  say "Open this URL in your browser to build your control surface:"
  printf '    %shttp://%s.local:9284%s\n' "$C_GREEN" "$HOSTNAME_CHOICE" "$C_OFF"
  say "(If .local doesn't resolve, use the device IP instead.)"
  [ "$(yesno "$ENABLE_STREAMDECK")" = true ] && say "A Stream Deck will pick up the layout you build in the editor."
  [ "$(yesno "$ENABLE_AP")" = true ] && say "With no network, the device serves a Wi-Fi hotspot named AutoPi."
  hr
}

main() {
  banner
  resolve_config
  confirm_plan

  if [ "$PLAN_ONLY" = "1" ]; then
    printf 'PLAN mode=%s kiosk=%s streamdeck=%s ap=%s hostname=%s repo_dir=%s\n' \
      "$DEPLOYMENT_MODE" "$(yesno "$ENABLE_KIOSK")" "$(yesno "$ENABLE_STREAMDECK")" \
      "$(yesno "$ENABLE_AP")" "$HOSTNAME_CHOICE" "$REPO_DIR"
    exit 0
  fi

  if [ "$NONINTERACTIVE" != "1" ]; then
    prompt_yn "Proceed with this install?" y || die "Aborted by user."
  fi

  need_root
  fetch_repo
  install_docker
  configure_gpio_access
  bring_up_stack
  [ "$DEPLOYMENT_MODE" = "pi_hosted" ] && provision_appliance
  print_done
}

main "$@"
