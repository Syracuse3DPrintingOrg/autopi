#!/usr/bin/env bash
# Bring up the Waveshare 2-Channel CAN-FD HAT (dual MCP2518FD over SPI) as
# SocketCAN interfaces can0 and can1.
#
# Enables SPI and the mcp251xfd device-tree overlay in the boot config, then
# brings each interface up with the requested bitrate (and data-bitrate for
# CAN-FD). Installs a systemd oneshot service that repeats the "ip link up"
# step on every boot, since the overlay recreates the interfaces but does not
# set their bitrate itself.
#
# Run as root on a Pi appliance with the HAT attached. No-op off a Pi.
# Idempotent: re-running only adds what is missing and re-applies the link
# settings.
#
#   setup-can-waveshare.sh
#
# Environment overrides:
#   CAN_BITRATE       arbitration-phase bitrate, bit/s (default 500000)
#   CAN_DBITRATE      CAN-FD data-phase bitrate, bit/s (default 2000000)
#   CAN_FD            "true" to bring the interfaces up in FD mode (default true)
#   CAN_MODE          Waveshare board mode: "a" (factory default) or "b"
#   CAN0_INTERRUPT    GPIO the first MCP2518FD's INT line is wired to (default 25)
#   CAN1_INTERRUPT    GPIO the second MCP2518FD's INT line is wired to
#
# Per the Waveshare 2-CH CAN FD HAT wiki, Mode A is the factory default and the
# two channels use two independent SPI buses: channel 0 on SPI0-0 (interrupt 25)
# and channel 1 on SPI1-0 (interrupt 24), with spi1-3cs enabling SPI1. Mode B
# (needs the board's 0-ohm resistors moved) puts both on SPI0: spi0-0 (25) and
# spi0-1 (13). This script defaults to Mode A. If the second channel does not
# appear, the board is likely in the other mode; set CAN_MODE accordingly.
set -uo pipefail

CAN_MODE="${CAN_MODE:-a}"
CAN_BITRATE="${CAN_BITRATE:-500000}"
CAN_DBITRATE="${CAN_DBITRATE:-2000000}"
CAN_FD="${CAN_FD:-true}"
CAN0_INTERRUPT="${CAN0_INTERRUPT:-25}"
# Channel 1's default interrupt depends on the mode: SPI1-0 uses 24, spi0-1 uses 13.
if [ "$CAN_MODE" = "b" ]; then
  CAN1_INTERRUPT="${CAN1_INTERRUPT:-13}"
else
  CAN1_INTERRUPT="${CAN1_INTERRUPT:-24}"
fi
# The MCP2518FD's crystal. The Waveshare 2-Ch CAN-FD HAT uses 40 MHz. This must
# match the board or the bit timing is wrong: classic CAN may still limp along,
# but CAN-FD (which needs tight timing) fails. Some board revisions use 20 MHz;
# set CAN_OSCILLATOR=20000000 if FD will not come up.
CAN_OSCILLATOR="${CAN_OSCILLATOR:-40000000}"
# Optional bit-timing sample points (0..1), to match a bus that needs a specific
# one. Empty lets the driver auto-pick.
CAN_SAMPLE_POINT="${CAN_SAMPLE_POINT:-}"
CAN_DSAMPLE_POINT="${CAN_DSAMPLE_POINT:-}"

is_pi=false
for f in /proc/device-tree/model /sys/firmware/devicetree/base/model; do
  [ -r "$f" ] && tr -d '\0' <"$f" | grep -qi 'raspberry pi' && is_pi=true
done
if [ "$is_pi" != true ]; then
  echo "Not a Raspberry Pi; leaving CAN unconfigured."
  exit 0
fi

# Bookworm moved the boot partition to /boot/firmware; older images still use
# /boot directly. Use whichever config.txt actually exists.
CONFIG_TXT="/boot/config.txt"
[ -f /boot/firmware/config.txt ] && CONFIG_TXT="/boot/firmware/config.txt"
if [ ! -f "$CONFIG_TXT" ]; then
  echo "No config.txt found at /boot or /boot/firmware; cannot enable the overlay." >&2
  exit 1
fi

add_config_line() {
  local line="$1"
  grep -qxF "$line" "$CONFIG_TXT" || echo "$line" >> "$CONFIG_TXT"
}

echo "Enabling SPI and the mcp251xfd overlay in ${CONFIG_TXT} (mode ${CAN_MODE})"
add_config_line "dtparam=spi=on"
# Replace any prior mcp251xfd/spi1 lines so re-running switches mode or pins
# cleanly instead of leaving stale, conflicting overlays behind.
sed -i '/^dtoverlay=mcp251xfd/d; /^dtoverlay=spi1-3cs/d' "$CONFIG_TXT"
echo "dtoverlay=mcp251xfd,spi0-0,interrupt=${CAN0_INTERRUPT},oscillator=${CAN_OSCILLATOR}" >> "$CONFIG_TXT"
if [ "$CAN_MODE" = "b" ]; then
  # Mode B: both controllers on SPI0 (needs the board's 0-ohm resistors moved).
  echo "dtoverlay=mcp251xfd,spi0-1,interrupt=${CAN1_INTERRUPT},oscillator=${CAN_OSCILLATOR}" >> "$CONFIG_TXT"
else
  # Mode A (factory default): the second controller is on SPI1, so enable SPI1.
  add_config_line "dtoverlay=spi1-3cs"
  echo "dtoverlay=mcp251xfd,spi1-0,interrupt=${CAN1_INTERRUPT},oscillator=${CAN_OSCILLATOR}" >> "$CONFIG_TXT"
fi

# Pin the interface names to the board's silkscreen so Linux can0 IS the board's
# CAN0 connector, not whichever controller the kernel happened to probe first.
# Without this the kernel names the two MCP2518FDs can0/can1 in probe order,
# which is not stable and often lands can0 on the board's CAN1 port (and vice
# versa), so the app, the monitor, and ip all disagree with the label on the
# board. The rule keys each name on the controller's SPI address, which is fixed
# by the mode: in Mode A the second controller is on SPI1 (spi1.0), in Mode B it
# is the second chip-select on SPI0 (spi0.1). The rename takes effect at the next
# boot, when udev names the interfaces as they are created.
if [ "$CAN_MODE" = "b" ]; then
  CAN1_SPI="spi0.1"
else
  CAN1_SPI="spi1.0"
fi
echo "Pinning interface names: can0 -> spi0.0 (board CAN0), can1 -> ${CAN1_SPI} (board CAN1)"
cat > /etc/udev/rules.d/72-autopi-can-names.rules <<EOF
# Generated by setup-can-waveshare.sh. Name the Waveshare CAN-FD HAT interfaces
# by their SPI controller so the Linux name matches the board silkscreen.
SUBSYSTEM=="net", ACTION=="add", KERNELS=="spi0.0", NAME="can0"
SUBSYSTEM=="net", ACTION=="add", KERNELS=="${CAN1_SPI}", NAME="can1"
EOF
udevadm control --reload-rules 2>/dev/null || true

echo "Writing the CAN link-up service (defaults: bitrate ${CAN_BITRATE}, dbitrate ${CAN_DBITRATE}, fd=${CAN_FD})"
# restart-ms auto-recovers the interface from a bus-off (matches the factory
# bring-up), so a wiring glitch does not leave the bus down until a manual reset.
CAN_RESTART_MS="${CAN_RESTART_MS:-1000}"
# Per-channel bring-up reads the app's saved interface config so a mixed setup
# (e.g. can0 500k CAN-FD, can1 125k classic) each comes up right and persists
# across reboots, instead of forcing one bitrate/FD mode on both channels.
CAN_CONFIG_JSON="${CAN_CONFIG_JSON:-/opt/autopi-src/service/data/can-interfaces.json}"
DEFAULT_FD=$([ "$CAN_FD" = "true" ] && echo true || echo false)

cat > /usr/local/sbin/autopi-can-config <<'PY'
#!/usr/bin/env python3
"""Emit per-channel CAN link settings from the app's saved interface config, one
'iface|bitrate|fd|dbitrate|sample_point|data_sample_point' line per SocketCAN
interface, for autopi-can-up. Silent if the file is missing or unreadable."""
import json
import sys
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
for entry in data.get("interfaces", []):
    if (entry.get("backend") or "socketcan") != "socketcan":
        continue
    channel = (entry.get("channel") or "").strip()
    if not channel:
        continue
    print("|".join([
        channel,
        str(entry.get("bitrate") or 500000),
        "true" if entry.get("fd") else "false",
        str(entry.get("data_bitrate") or 2000000),
        str(entry.get("sample_point") or ""),
        str(entry.get("data_sample_point") or ""),
    ]))
PY
chmod 755 /usr/local/sbin/autopi-can-config

cat > /usr/local/sbin/autopi-can-up <<EOF
#!/usr/bin/env bash
# Generated by setup-can-waveshare.sh. Brings the CAN interfaces up. Each channel
# configured in the app (Settings > CAN Interfaces) is brought up with its own
# bitrate and CAN-FD setting; any HAT channel not configured falls back to the
# defaults this script was generated with. A missing interface is reported but
# not fatal, so this never blocks boot.
set -u
CONFIG_JSON="${CAN_CONFIG_JSON}"
RESTART_MS="${CAN_RESTART_MS}"

apply_iface() {
  local iface="\$1" bitrate="\$2" fd="\$3" dbitrate="\$4" sp="\$5" dsp="\$6"
  if ! ip link show "\$iface" >/dev/null 2>&1; then
    echo "autopi-can-up: \$iface not present, skipping"
    return
  fi
  ip link set "\$iface" down 2>/dev/null || true
  local base="bitrate \$bitrate restart-ms \$RESTART_MS"
  [ -n "\$sp" ] && base="\$base sample-point \$sp"
  if [ "\$fd" = "true" ]; then
    local fdargs="dbitrate \$dbitrate"
    [ -n "\$dsp" ] && fdargs="\$fdargs dsample-point \$dsp"
    if ip link set "\$iface" type can \$base \$fdargs fd on 2>/dev/null; then
      ip link set "\$iface" up && echo "autopi-can-up: \$iface up, CAN-FD, \$base \$fdargs"
      return
    fi
    echo "autopi-can-up: \$iface CAN-FD setup failed, trying classic (check CAN_OSCILLATOR)"
  fi
  if ip link set "\$iface" type can \$base 2>/dev/null; then
    ip link set "\$iface" up && echo "autopi-can-up: \$iface up, classic, \$base"
  else
    echo "autopi-can-up: \$iface could not be configured (see: dmesg | grep mcp251)"
  fi
}

configured=""
if [ -f "\$CONFIG_JSON" ] && command -v python3 >/dev/null 2>&1; then
  while IFS='|' read -r iface bitrate fd dbitrate sp dsp; do
    [ -z "\$iface" ] && continue
    apply_iface "\$iface" "\$bitrate" "\$fd" "\$dbitrate" "\$sp" "\$dsp"
    configured="\$configured \$iface"
  done < <(python3 /usr/local/sbin/autopi-can-config "\$CONFIG_JSON")
fi

# HAT channels not configured in the app: bring up with the generated defaults.
for iface in can0 can1; do
  case " \$configured " in *" \$iface "*) continue ;; esac
  apply_iface "\$iface" "${CAN_BITRATE}" "${DEFAULT_FD}" "${CAN_DBITRATE}" "${CAN_SAMPLE_POINT}" "${CAN_DSAMPLE_POINT}"
done
EOF
chmod 755 /usr/local/sbin/autopi-can-up

cat > /etc/systemd/system/autopi-can.service <<'EOF'
[Unit]
Description=Bring up the Waveshare CAN-FD HAT interfaces
After=sys-subsystem-net-devices-can0.device
Wants=sys-subsystem-net-devices-can0.device

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/autopi-can-up
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable autopi-can.service

if ip link show can0 >/dev/null 2>&1 || ip link show can1 >/dev/null 2>&1; then
  echo "mcp251xfd interfaces already present; applying link settings now."
  /usr/local/sbin/autopi-can-up
else
  echo "Overlay written; can0/can1 will appear after a reboot (the interfaces" \
    "do not exist until the mcp251xfd driver loads at boot)."
fi

echo "CAN setup complete. A reboot is required if this is the first run, and to"
echo "apply the interface-name pinning (can0 = board CAN0). Until you reboot, the"
echo "names may still be crossed from a previous boot."

echo
echo "--- CAN diagnostics ---"
echo "config.txt overlay lines:"
grep -E '^dtparam=spi|^dtoverlay=(mcp251xfd|spi1-3cs)' "$CONFIG_TXT" | sed 's/^/  /'
echo "CAN interfaces present (name -> SPI controller):"
for c in $(ls -1 /sys/class/net/ 2>/dev/null | grep -E '^can[0-9]+$'); do
  spi=$(basename "$(readlink -f "/sys/class/net/$c/device" 2>/dev/null)" 2>/dev/null)
  echo "  $c -> ${spi:-unknown}"
done
ls -1 /sys/class/net/ 2>/dev/null | grep -qE '^can[0-9]+$' || echo "  none yet (reboot needed)"
echo "mcp251xfd kernel messages (last 12):"
dmesg 2>/dev/null | grep -i mcp251 | tail -12 | sed 's/^/  /' || echo "  none"
echo
echo "If one channel is missing while the other works, the second controller did not"
echo "probe (dmesg shows 'Failed to read Oscillator Configuration Register'):"
echo "  - this ran in mode ${CAN_MODE}. Mode A (factory default) puts channel 1 on SPI1"
echo "    (spi1-0, int 24, with spi1-3cs); Mode B puts it on SPI0 (spi0-1, int 13) and"
echo "    needs the board's 0-ohm resistors moved. If the second channel is absent, the"
echo "    board is likely in the other mode: re-run with the opposite CAN_MODE, e.g."
echo "    sudo CAN_MODE=$([ "$CAN_MODE" = a ] && echo b || echo a) bash \$0   # then reboot"
echo "  - confirm the HAT is seated and no header pin is bent."
echo "If CAN-FD will not come up but classic does, the oscillator is likely wrong:"
echo "  sudo CAN_OSCILLATOR=20000000 bash \$0   # then reboot"
