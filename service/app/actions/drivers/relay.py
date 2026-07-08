"""Relay board driver.

A relay board is GPIO-driven; the only twist is that most relay HATs are
active-low (the relay closes when the pin is pulled LOW), so this driver
defaults to active-low and exposes on/off/toggle/pulse per channel. It reuses
gpiozero like the plain GPIO driver and simulates when there is no real pin
factory, so it works on a bench.
"""
from __future__ import annotations

from typing import Any

from .base import Driver, DriverResult
from .gpio import GpioDriver


class RelayDriver(Driver):
    name = "relay"
    label = "Relay board"
    param_schema = [
        {"key": "pin", "label": "BCM pin", "type": "number", "required": True},
        {"key": "state", "label": "State", "type": "choice",
         "choices": ["on", "off", "toggle", "pulse"], "required": True, "default": "on"},
        {"key": "active_low", "label": "Active low (typical relay HAT)", "type": "bool",
         "required": False, "default": True},
        {"key": "pulse_ms", "label": "Pulse length (ms)", "type": "number",
         "required": False, "default": 300},
    ]

    def __init__(self) -> None:
        # Delegate the actual pin work to a GpioDriver instance so the pin
        # factory handling and simulation path are shared.
        self._gpio = GpioDriver()

    @property
    def available(self) -> bool:
        return self._gpio.available

    def execute(self, params: dict[str, Any]) -> DriverResult:
        state = str(params.get("state", "on"))
        # "on" for a relay means energised: with an active-low board that is a
        # LOW pin, which the GPIO driver models via active_high=False.
        mode = {"on": "on", "off": "off", "toggle": "toggle", "pulse": "pulse"}.get(state, "on")
        gpio_params = {
            "pin": params.get("pin"),
            "mode": mode,
            "active_high": not bool(params.get("active_low", True)),
            "pulse_ms": params.get("pulse_ms", 300),
        }
        res = self._gpio.execute(gpio_params)
        # Relabel for the relay vocabulary.
        if res.ok:
            res.message = res.message.replace("pin", "relay pin")
        return res
