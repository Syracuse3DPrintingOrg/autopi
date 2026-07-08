"""Pure tests for the host-bridge CAN interface name guard and route table.

autopi-host-bridge is a standalone stdlib script (no .py extension, no
dependency on the app package) so it is loaded here by file path, the same
way test_host_bridge_network.py does.
"""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "image-build" / "autopi-host-bridge"
_loader = SourceFileLoader("autopi_host_bridge_can", str(_SCRIPT))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
bridge_script = importlib.util.module_from_spec(_spec)
_loader.exec_module(bridge_script)


def test_is_valid_can_interface_accepts_typical_names():
    assert bridge_script.is_valid_can_interface("can0") is True
    assert bridge_script.is_valid_can_interface("can1") is True
    assert bridge_script.is_valid_can_interface("vcan0") is True
    assert bridge_script.is_valid_can_interface("my-custom_bus.1") is True


def test_is_valid_can_interface_rejects_empty():
    assert bridge_script.is_valid_can_interface("") is False
    assert bridge_script.is_valid_can_interface(None) is False


def test_is_valid_can_interface_rejects_shell_metacharacters():
    assert bridge_script.is_valid_can_interface("can0; rm -rf /") is False
    assert bridge_script.is_valid_can_interface("can0 && reboot") is False
    assert bridge_script.is_valid_can_interface("../etc/passwd") is False
    assert bridge_script.is_valid_can_interface("eth0 ") is False


def test_is_valid_can_interface_rejects_too_long():
    assert bridge_script.is_valid_can_interface("a" * 16) is False
    assert bridge_script.is_valid_can_interface("a" * 15) is True


def test_op_can_up_rejects_invalid_interface():
    result = bridge_script.op_can_up({"interface": "can0; reboot"})
    assert result["ok"] is False


def test_op_can_down_rejects_invalid_interface():
    result = bridge_script.op_can_down({"interface": ""})
    assert result["ok"] is False


def test_op_can_status_rejects_invalid_interface():
    result = bridge_script.op_can_status({"interface": "../x"})
    assert result["ok"] is False


def test_op_can_up_rejects_non_numeric_bitrate():
    result = bridge_script.op_can_up({"interface": "can0", "bitrate": "fast"})
    assert result["ok"] is False


def test_can_routes_are_registered():
    assert ("POST", "/can/up") in bridge_script.ROUTES
    assert ("POST", "/can/down") in bridge_script.ROUTES
    assert ("POST", "/can/status") in bridge_script.ROUTES


def test_bridge_version_bumped_for_can_routes():
    assert bridge_script.BRIDGE_VERSION >= 3
