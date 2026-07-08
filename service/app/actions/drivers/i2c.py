"""I2C device driver (read/write a register over the Pi's I2C bus).

Uses smbus2 (MIT) when present; on a machine with no I2C bus it reports itself
unavailable and simulates, so actions can be built and tested anywhere. Reads
and writes a byte (or word) at a register on a device address.
"""
from __future__ import annotations

from typing import Any

from .base import Driver, DriverResult


def _parse_int(v, default=0):
    if isinstance(v, int):
        return v
    s = str(v).strip()
    if not s:
        return default
    return int(s, 16) if s.lower().startswith("0x") else int(s, 0)


class I2cDriver(Driver):
    name = "i2c"
    label = "I2C device"
    simulate_when_unavailable = True
    param_schema = [
        {"key": "bus", "label": "I2C bus", "type": "number", "required": False, "default": 1},
        {"key": "address", "label": "Address (hex)", "type": "text", "required": True, "help": "e.g. 0x48"},
        {"key": "register", "label": "Register (hex)", "type": "text", "required": True, "help": "e.g. 0x00"},
        {"key": "op", "label": "Operation", "type": "choice",
         "choices": ["read_byte", "write_byte", "read_word", "write_word"], "required": True, "default": "read_byte"},
        {"key": "value", "label": "Value (for write, hex/int)", "type": "text", "required": False},
    ]

    @property
    def available(self) -> bool:
        try:
            import smbus2  # noqa: F401
            import os
            return any(os.path.exists(f"/dev/i2c-{b}") for b in range(0, 3))
        except Exception:
            return False

    def execute(self, params: dict[str, Any]) -> DriverResult:
        try:
            bus_no = int(params.get("bus", 1) or 1)
            addr = _parse_int(params.get("address"))
            reg = _parse_int(params.get("register"))
            op = str(params.get("op", "read_byte"))
        except (TypeError, ValueError) as exc:
            return DriverResult.failure(f"Invalid I2C parameters: {exc}")

        if not self.available:
            return DriverResult.success(
                f"(simulated) I2C {op} bus {bus_no} addr {hex(addr)} reg {hex(reg)}",
                simulated=True, bus=bus_no, address=addr, register=reg, op=op)
        try:
            import smbus2
            bus = smbus2.SMBus(bus_no)
            try:
                if op == "read_byte":
                    val = bus.read_byte_data(addr, reg)
                    return DriverResult.success(f"Read {hex(val)} from {hex(addr)}:{hex(reg)}", value=val)
                if op == "read_word":
                    val = bus.read_word_data(addr, reg)
                    return DriverResult.success(f"Read {hex(val)} from {hex(addr)}:{hex(reg)}", value=val)
                value = _parse_int(params.get("value"))
                if op == "write_byte":
                    bus.write_byte_data(addr, reg, value & 0xFF)
                elif op == "write_word":
                    bus.write_word_data(addr, reg, value & 0xFFFF)
                return DriverResult.success(f"Wrote {hex(value)} to {hex(addr)}:{hex(reg)}", value=value)
            finally:
                bus.close()
        except Exception as exc:  # hardware errors should not crash a request
            return DriverResult.failure(f"I2C error: {exc}")
