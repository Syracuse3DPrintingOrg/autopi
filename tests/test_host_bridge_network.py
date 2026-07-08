"""Pure parsing tests for the host-bridge Wi-Fi helpers.

autopi-host-bridge is a standalone stdlib script (no .py extension, no
dependency on the app package) so it is loaded here by file path instead of
imported as a package.
"""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "image-build" / "autopi-host-bridge"
_loader = SourceFileLoader("autopi_host_bridge", str(_SCRIPT))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
bridge_script = importlib.util.module_from_spec(_spec)
_loader.exec_module(bridge_script)


def test_parse_nmcli_active_ssid_found():
    out = "no:OtherNetwork\nyes:HomeWifi\n"
    assert bridge_script.parse_nmcli_active_ssid(out) == "HomeWifi"


def test_parse_nmcli_active_ssid_none_when_not_connected():
    out = "no:OtherNetwork\nno:AnotherOne\n"
    assert bridge_script.parse_nmcli_active_ssid(out) is None


def test_parse_iw_link_ssid():
    out = "Connected to aa:bb:cc:dd:ee:ff (on wlan0)\n\tSSID: HomeWifi\n\tfreq: 2412\n"
    assert bridge_script.parse_iw_link_ssid(out) == "HomeWifi"


def test_parse_iw_link_ssid_none_when_absent():
    assert bridge_script.parse_iw_link_ssid("") is None


def test_parse_nmcli_scan_basic():
    out = "HomeWifi:78:WPA2\nOpenGuest::\nWeakNetwork:20:WPA2\n"
    networks = bridge_script.parse_nmcli_scan(out)
    ssids = [n["ssid"] for n in networks]
    assert ssids == ["HomeWifi", "WeakNetwork", "OpenGuest"]
    home = next(n for n in networks if n["ssid"] == "HomeWifi")
    assert home["signal"] == 78
    assert home["secured"] is True
    guest = next(n for n in networks if n["ssid"] == "OpenGuest")
    assert guest["secured"] is False


def test_parse_nmcli_scan_dedupes_keeping_strongest():
    out = "SameNetwork:40:WPA2\nSameNetwork:85:WPA2\n"
    networks = bridge_script.parse_nmcli_scan(out)
    assert len(networks) == 1
    assert networks[0]["signal"] == 85


def test_parse_nmcli_scan_handles_escaped_colon_in_ssid():
    out = "My\\:Network:60:WPA2\n"
    networks = bridge_script.parse_nmcli_scan(out)
    assert networks[0]["ssid"] == "My:Network"


def test_parse_iw_scan_basic():
    out = (
        "BSS aa:bb:cc:dd:ee:ff(on wlan0)\n"
        "\tsignal: -45.00 dBm\n"
        "\tSSID: HomeWifi\n"
        "BSS 11:22:33:44:55:66(on wlan0)\n"
        "\tsignal: -70.00 dBm\n"
        "\tSSID: FarAwayNetwork\n"
    )
    networks = bridge_script.parse_iw_scan(out)
    assert [n["ssid"] for n in networks] == ["HomeWifi", "FarAwayNetwork"]
    assert networks[0]["signal"] == -45.0


def test_parse_iw_scan_empty():
    assert bridge_script.parse_iw_scan("") == []


def test_op_network_connect_requires_ssid():
    result = bridge_script.op_network_connect({})
    assert result["ok"] is False
    assert "ssid" in result["error"]
