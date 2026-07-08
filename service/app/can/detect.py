"""Discover the CAN interfaces that actually exist on this device.

The app runs in a container with host networking, so the host's SocketCAN
interfaces show up under /sys/class/net. This reads that directory, keeps the
CAN interfaces (link type ARPHRD_CAN), and reports each one's name, its kernel
driver (so the UI can say a channel is the Waveshare HAT vs a PEAK USB adapter),
and whether it is up. It lets a user see that, for example, can0 is a PEAK
PCAN-USB and can1 is the Waveshare HAT, instead of guessing channel names.

Pure with respect to the filesystem root, so it is unit-testable against a fake
/sys tree with no hardware.
"""
from __future__ import annotations

import os

# ARPHRD_CAN: the link type every SocketCAN interface reports in
# /sys/class/net/<iface>/type. Filtering on it keeps ethernet/wifi/loopback out
# and keeps real and virtual CAN in.
ARPHRD_CAN = 280

# Kernel driver name -> a friendly description of what the adapter is.
_DRIVER_LABELS = {
    "mcp251xfd": "MCP2518FD CAN-FD controller (Waveshare CAN-FD HAT)",
    "mcp251x": "MCP2515 CAN controller (older CAN HAT)",
    "peak_usb": "PEAK PCAN-USB adapter",
    "peak_pciefd": "PEAK PCAN PCIe FD",
    "peak_pci": "PEAK PCAN PCI",
    "gs_usb": "USB CAN adapter (gs_usb / candleLight / CANable)",
    "kvaser_usb": "Kvaser USB adapter",
    "ucan": "USB CAN adapter (ucan)",
    "vcan": "Virtual CAN (software loopback, no hardware)",
    "vxcan": "Virtual CAN pair",
    "slcan": "Serial-line CAN adapter",
}


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def _driver_of(iface_dir: str) -> str | None:
    # /sys/class/net/<iface>/device/driver is a symlink into the driver dir; its
    # basename is the driver name (mcp251xfd, peak_usb, ...).
    link = os.path.join(iface_dir, "device", "driver")
    try:
        return os.path.basename(os.readlink(link))
    except OSError:
        return None


def list_can_interfaces(sysfs_root: str = "/sys/class/net") -> list[dict]:
    """List the CAN interfaces present on the device, sorted by name.

    Each entry: ``name``, ``driver`` (kernel driver or None), ``description``
    (a friendly label), ``up`` (bool), ``is_virtual`` (a vcan/vxcan software
    interface). Returns an empty list when none are present or the tree is
    unreadable, never raising.
    """
    out: list[dict] = []
    try:
        names = sorted(os.listdir(sysfs_root))
    except OSError:
        return out
    for name in names:
        iface_dir = os.path.join(sysfs_root, name)
        if _read(os.path.join(iface_dir, "type")) != str(ARPHRD_CAN):
            continue
        driver = _driver_of(iface_dir)
        operstate = (_read(os.path.join(iface_dir, "operstate")) or "").lower()
        description = _DRIVER_LABELS.get(driver or "", None)
        if description is None:
            description = f"CAN interface ({driver})" if driver else "CAN interface"
        out.append({
            "name": name,
            "driver": driver,
            "description": description,
            "up": operstate == "up",
            "is_virtual": driver in ("vcan", "vxcan"),
        })
    return out
