"""Set a signal on a running CAN simulation entry.

This is what makes a selector key drive a live, periodically-transmitted
message: a "Drive" key sets the Gear signal on the periodic Transmission
entry, so the instrument cluster (which reads that message on the bus) shows
Drive. Supports absolute (set) and relative (add, for an adjustable speed
+/- key) updates. It is pure software, so it is always available.
"""
from __future__ import annotations

from typing import Any

from ...can import simulation
from .base import Driver, DriverResult


class SimSetDriver(Driver):
    name = "sim_set"
    label = "Set a simulated signal"
    param_schema = [
        {"key": "entry", "label": "Simulation entry name", "type": "text", "required": True},
        {"key": "signals", "label": "Signals to set", "type": "keyvalue", "required": True},
        {"key": "mode", "label": "Mode", "type": "choice", "choices": ["set", "add"],
         "required": False, "default": "set", "help": "set = absolute, add = increment (for +/- keys)"},
        {"key": "min", "label": "Clamp minimum", "type": "number", "required": False},
        {"key": "max", "label": "Clamp maximum", "type": "number", "required": False},
    ]

    def execute(self, params: dict[str, Any]) -> DriverResult:
        entry_name = str(params.get("entry", "")).strip()
        signals = params.get("signals") or {}
        if not entry_name or not isinstance(signals, dict):
            return DriverResult.failure("A simulation entry name and signals are required")
        target = next((e for e in simulation.list_entries()
                       if e.get("name") == entry_name or e.get("id") == entry_name), None)
        if target is None:
            return DriverResult.failure(f"No simulation entry named {entry_name}")
        mode = str(params.get("mode", "set"))
        current = dict(target.get("signals") or {})
        for key, value in signals.items():
            if mode == "add":
                new = float(current.get(key, 0)) + float(value)
                if params.get("min") is not None:
                    new = max(float(params["min"]), new)
                if params.get("max") is not None:
                    new = min(float(params["max"]), new)
                current[key] = new
            else:
                current[key] = value
        simulation.update_entry(target["id"], {"signals": current})
        return DriverResult.success(f"{entry_name}: {current}", entry=entry_name, signals=current)
