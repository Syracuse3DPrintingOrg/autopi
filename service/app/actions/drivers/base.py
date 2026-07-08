"""The Driver interface and a small result type."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DriverResult:
    """Outcome of running an action, safe to serialize straight to JSON."""

    ok: bool
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls, message: str = "", **data: Any) -> "DriverResult":
        return cls(ok=True, message=message, data=dict(data))

    @classmethod
    def failure(cls, message: str, **data: Any) -> "DriverResult":
        return cls(ok=False, message=message, data=dict(data))


class Driver(ABC):
    """A named unit of behavior an action can dispatch to.

    ``name`` is the stable key used in an action's ``driver`` field. ``label``
    and ``param_schema`` describe the driver to the setup UI so it can render a
    form for its parameters. ``available`` reports whether the driver can run
    on this host right now (hardware present, dependency importable); an
    unavailable driver still validates and stores actions, it just refuses to
    execute them.
    """

    name: str = ""
    label: str = ""
    # A light description of the params a driver takes. Each entry is
    # {"key", "label", "type", "required", "default", "help"}. Kept as plain
    # data so the web form and the docs can both read it.
    param_schema: list[dict[str, Any]] = []
    # When True, an action may still be dispatched while the driver is
    # unavailable, because its execute() reports a useful simulated result
    # instead of failing. This lets a user test, say, a "Volume Up" CAN key on a
    # bench with no bus and see what it would send.
    simulate_when_unavailable: bool = False

    @property
    def available(self) -> bool:
        return True

    @abstractmethod
    def execute(self, params: dict[str, Any]) -> DriverResult:
        """Perform the action with the given validated parameters."""
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "available": self.available,
            "param_schema": self.param_schema,
        }
