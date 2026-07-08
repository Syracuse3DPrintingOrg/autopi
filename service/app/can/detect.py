"""Discover the CAN interfaces that actually exist on this device.

The app runs in a container with host networking, so the host's SocketCAN
interfaces show up under /sys/class/net. This reads that directory, keeps the
CAN interfaces (link type ARPHRD_CAN), and reports each one's name, its kernel
driver, the SPI device it sits on, the Waveshare HAT port it corresponds to
(the board silkscreen labels its two ports CAN0 and CAN1, which do NOT match the
kernel canN numbering once a USB adapter is also present), whether it is up, and
its receive/transmit packet counters (so you can see at a glance which bus is
actually carrying traffic).

Pure with respect to the filesystem root, so it is unit-testable against a fake
/sys tree with no hardware.
"""
from __future__ import annotations

import os
import re

# ARPHRD_CAN: the link type every SocketCAN interface reports in
# /sys/class/net/<iface>/type.
ARPHRD_CAN = 280

_DRIVER_LABELS = {
    "mcp251xfd": "MCP2518FD CAN-FD (Waveshare CAN-FD HAT)",
    "mcp251x": "MCP2515 CAN (older CAN HAT)",
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

_SPI_RE = re.compile(r"spi\d+\.\d+")


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def _int(path: str) -> int | None:
    v = _read(path)
    try:
        return int(v) if v is not None else None
    except ValueError:
        return None


def _driver_of(iface_dir: str) -> str | None:
    link = os.path.join(iface_dir, "device", "driver")
    try:
        return os.path.basename(os.readlink(link))
    except OSError:
        return None


def _spi_device_of(iface_dir: str) -> str | None:
    # /sys/class/net/<iface>/device resolves to the controller's device path,
    # which for the MCP2518FD is an spiB.C node. Pull that address out so we can
    # map it to a physical HAT port.
    try:
        real = os.path.realpath(os.path.join(iface_dir, "device"))
    except OSError:
        return None
    m = _SPI_RE.search(real)
    return m.group(0) if m else None


def _stats_of(iface_dir: str) -> dict:
    s = os.path.join(iface_dir, "statistics")
    return {
        "rx_packets": _int(os.path.join(s, "rx_packets")),
        "tx_packets": _int(os.path.join(s, "tx_packets")),
        "rx_errors": _int(os.path.join(s, "rx_errors")),
        "rx_over_errors": _int(os.path.join(s, "rx_over_errors")),
    }


def list_can_interfaces(sysfs_root: str = "/sys/class/net") -> list[dict]:
    """List the CAN interfaces present on the device, sorted by name.

    Each entry: ``name``, ``driver``, ``description``, ``spi_device``,
    ``port_label`` (the Waveshare HAT port, e.g. "CAN0", for MCP2518FD channels),
    ``up``, ``is_virtual``, and ``stats`` (rx/tx packet counters). Never raises.
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
            "spi_device": _spi_device_of(iface_dir),
            "port_label": None,
            "up": operstate == "up",
            "is_virtual": driver in ("vcan", "vxcan"),
            "stats": _stats_of(iface_dir),
        })

    # The Waveshare CAN-FD HAT silkscreens its two ports CAN0 and CAN1. The
    # kernel names (can1, can2, ...) shuffle when a USB adapter is also present,
    # so map the MCP2518FD channels to the board ports by their SPI address order
    # (spi0.0 is CAN0, then the next controller is CAN1, and so on). This holds
    # in both board modes (Mode A spi0.0/spi1.0, Mode B spi0.0/spi0.1).
    hat = sorted((i for i in out if i["driver"] == "mcp251xfd" and i["spi_device"]),
                 key=lambda i: i["spi_device"])
    for port, iface in enumerate(hat):
        iface["port_label"] = f"CAN{port}"
        iface["description"] = f"{iface['description']}, board port CAN{port}"
    return out
