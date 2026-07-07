#!/usr/bin/env bash
# Install the AutoPi Wi-Fi fallback access point.
#
# Sets up hostapd + dnsmasq and a watchdog service that activates a captive
# setup hotspot (SSID: AutoPi) only when the device has no other connectivity
# within 30 seconds of boot. A unit that connects normally is unaffected.
#
# Run as root on the device. Ported from the source project's firstboot step
# with the branding changed.
set -euo pipefail

AP_SSID="${AP_SSID:-AutoPi}"
AP_PASSPHRASE="${AP_PASSPHRASE:-autopiap}"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "Installing hostapd and dnsmasq"
DEBIAN_FRONTEND=noninteractive apt-get install -y -q hostapd dnsmasq

mkdir -p /etc/hostapd
cat > /etc/hostapd/hostapd.conf <<EOF
interface=wlan0
driver=nl80211
ssid=${AP_SSID}
hw_mode=g
channel=6
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=${AP_PASSPHRASE}
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
EOF

mkdir -p /etc/dnsmasq.d
cat > /etc/dnsmasq.d/autopi-ap.conf <<'EOF'
interface=wlan0
dhcp-range=192.168.99.2,192.168.99.20,12h
dhcp-option=3,192.168.99.1
dhcp-option=6,192.168.99.1
address=/#/192.168.99.1
EOF

install -m 755 "${HERE}/autopi-ap-watchdog" /usr/local/sbin/autopi-ap-watchdog

cat > /etc/systemd/system/autopi-ap-watchdog.service <<'EOF'
[Unit]
Description=AutoPi Wi-Fi fallback AP watchdog
After=network-online.target
Wants=network-online.target
RemainAfterExit=yes

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/autopi-ap-watchdog

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable autopi-ap-watchdog.service
echo "Wi-Fi fallback AP installed (SSID: ${AP_SSID}). It activates only when the device has no other connectivity."
