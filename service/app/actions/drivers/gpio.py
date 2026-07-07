"""Drive a GPIO pin as an action.

Uses gpiozero when it can find a real pin factory, which covers a Raspberry Pi
running Raspberry Pi OS. On any other host (a laptop, a plain server, CI) the
driver reports itself unavailable and records the intended pin state in memory
so the rest of the app, the layout editor, and the tests all still work. That
graceful no-op is what lets one build run everywhere.
"""
from __future__ import annotations

from typing import Any

from .base import Driver, DriverResult

# Modes an action can request for a pin.
MODES = ("toggle", "on", "off", "pulse")


class GpioDriver(Driver):
    name = "gpio"
    label = "GPIO pin"
    param_schema = [
        {"key": "pin", "label": "BCM pin number", "type": "number", "required": True},
        {"key": "mode", "label": "Action", "type": "choice", "choices": list(MODES),
         "required": True, "default": "toggle"},
        {"key": "active_high", "label": "Active high", "type": "bool",
         "required": False, "default": True},
        {"key": "pulse_ms", "label": "Pulse length (ms)", "type": "number",
         "required": False, "default": 200,
         "help": "Only used by the pulse action."},
    ]

    def __init__(self) -> None:
        # Cache one output device per pin so repeated presses reuse it.
        self._devices: dict[int, Any] = {}
        # Software mirror of each pin's state, so the no-hardware path and the
        # toggle action have something to reason about.
        self._state: dict[int, bool] = {}
        self._factory_ok: bool | None = None

    @property
    def available(self) -> bool:
        if self._factory_ok is None:
            self._factory_ok = self._probe_factory()
        return self._factory_ok

    @staticmethod
    def _probe_factory() -> bool:
        try:
            from gpiozero import Device  # type: ignore
            # Touching pin_factory raises BadPinFactory off real hardware.
            _ = Device.pin_factory
            return _ is not None or _real_factory_importable()
        except Exception:
            return False

    def execute(self, params: dict[str, Any]) -> DriverResult:
        try:
            pin = int(params["pin"])
        except (KeyError, TypeError, ValueError):
            return DriverResult.failure("No valid pin configured")
        mode = str(params.get("mode", "toggle"))
        if mode not in MODES:
            return DriverResult.failure(f"Unknown GPIO action: {mode}")
        active_high = bool(params.get("active_high", True))

        target = self._resolve_target(pin, mode)
        self._state[pin] = target

        if not self.available:
            # No real hardware: record the intent and report it plainly so the
            # UI can still show what would happen.
            return DriverResult.success(
                f"(simulated) pin {pin} -> {'high' if target else 'low'}",
                pin=pin, state=target, simulated=True,
            )
        try:
            device = self._device(pin, active_high)
            if mode == "pulse":
                try:
                    pulse_ms = float(params.get("pulse_ms", 200) or 200)
                except (TypeError, ValueError):
                    pulse_ms = 200.0
                device.blink(on_time=pulse_ms / 1000.0, n=1, background=False)
                return DriverResult.success(f"Pulsed pin {pin}", pin=pin)
            device.value = 1 if target else 0
            return DriverResult.success(
                f"Pin {pin} {'high' if target else 'low'}", pin=pin, state=target)
        except Exception as exc:  # hardware errors should not crash a request
            return DriverResult.failure(f"GPIO error on pin {pin}: {exc}", pin=pin)

    def _resolve_target(self, pin: int, mode: str) -> bool:
        if mode == "on" or mode == "pulse":
            return True
        if mode == "off":
            return False
        return not self._state.get(pin, False)  # toggle

    def _device(self, pin: int, active_high: bool) -> Any:
        dev = self._devices.get(pin)
        if dev is None:
            from gpiozero import OutputDevice  # type: ignore
            dev = OutputDevice(pin, active_high=active_high, initial_value=False)
            self._devices[pin] = dev
        return dev


def _real_factory_importable() -> bool:
    for mod in ("gpiozero.pins.lgpio", "gpiozero.pins.rpigpio", "gpiozero.pins.pigpio"):
        try:
            __import__(mod)
            return True
        except Exception:
            continue
    return False
