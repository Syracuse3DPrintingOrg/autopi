"""Modbus TCP driver (read/write coils and registers over TCP).

Uses pymodbus (MIT) when present; simulates otherwise so actions build and test
anywhere. Covers the common cases: read/write a coil, read/write a holding
register.
"""
from __future__ import annotations

from typing import Any

from .base import Driver, DriverResult


class ModbusDriver(Driver):
    name = "modbus"
    label = "Modbus TCP"
    simulate_when_unavailable = True
    param_schema = [
        {"key": "host", "label": "Host", "type": "text", "required": True, "help": "IP or hostname"},
        {"key": "port", "label": "Port", "type": "number", "required": False, "default": 502},
        {"key": "unit", "label": "Unit id", "type": "number", "required": False, "default": 1},
        {"key": "op", "label": "Operation", "type": "choice",
         "choices": ["read_coil", "write_coil", "read_register", "write_register"],
         "required": True, "default": "read_register"},
        {"key": "address", "label": "Address", "type": "number", "required": True},
        {"key": "value", "label": "Value (for write)", "type": "number", "required": False},
    ]

    @property
    def available(self) -> bool:
        try:
            import pymodbus  # noqa: F401
            return True
        except Exception:
            return False

    def execute(self, params: dict[str, Any]) -> DriverResult:
        host = str(params.get("host", "")).strip()
        if not host:
            return DriverResult.failure("No Modbus host configured")
        try:
            port = int(params.get("port", 502) or 502)
            unit = int(params.get("unit", 1) or 1)
            address = int(params.get("address", 0) or 0)
            op = str(params.get("op", "read_register"))
        except (TypeError, ValueError) as exc:
            return DriverResult.failure(f"Invalid Modbus parameters: {exc}")

        if not self.available:
            return DriverResult.success(
                f"(simulated) Modbus {op} {host}:{port} unit {unit} addr {address}",
                simulated=True, host=host, port=port, unit=unit, address=address, op=op)
        try:
            from pymodbus.client import ModbusTcpClient
            client = ModbusTcpClient(host, port=port)
            if not client.connect():
                return DriverResult.failure(f"Could not connect to {host}:{port}")
            try:
                value = int(params.get("value", 0) or 0)
                if op == "read_coil":
                    r = client.read_coils(address, count=1, slave=unit)
                    return DriverResult.success(f"Coil {address} = {r.bits[0]}", value=int(r.bits[0]))
                if op == "read_register":
                    r = client.read_holding_registers(address, count=1, slave=unit)
                    return DriverResult.success(f"Register {address} = {r.registers[0]}", value=r.registers[0])
                if op == "write_coil":
                    client.write_coil(address, bool(value), slave=unit)
                    return DriverResult.success(f"Wrote coil {address} = {bool(value)}", value=value)
                client.write_register(address, value & 0xFFFF, slave=unit)
                return DriverResult.success(f"Wrote register {address} = {value}", value=value)
            finally:
                client.close()
        except Exception as exc:
            return DriverResult.failure(f"Modbus error: {exc}")
