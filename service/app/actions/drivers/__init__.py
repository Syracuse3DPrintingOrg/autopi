"""Action drivers: the things an action actually does.

Every driver subclasses :class:`~app.actions.drivers.base.Driver`. Drivers are
discovered automatically: any module dropped into this package that defines a
``Driver`` subclass with a ``name`` is registered on import, so adapting AutoPi
to a new product is usually just adding one file here (or calling
``register_driver`` from a plugin loaded elsewhere). Nothing else in the app
hard-codes the list of drivers.

Drivers must never assume their hardware or optional dependency is present: on
a machine with no Pi, the GPIO and CAN drivers report themselves unavailable
and no-op instead of crashing, so one build runs on a laptop and on an
appliance alike.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil

from .base import Driver, DriverResult

# name -> singleton driver instance
DRIVERS: dict[str, Driver] = {}


def register_driver(driver: Driver) -> None:
    """Register a driver instance under its ``name`` (last registration wins)."""
    if not driver.name:
        raise ValueError(f"{type(driver).__name__} has no name")
    DRIVERS[driver.name] = driver


def get_driver(name: str) -> Driver | None:
    return DRIVERS.get(name)


def _discover() -> None:
    """Import every sibling module and register its Driver subclasses."""
    package = __name__
    for info in pkgutil.iter_modules(__path__):
        if info.name in {"base"}:
            continue
        module = importlib.import_module(f"{package}.{info.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, Driver)
                and obj is not Driver
                and getattr(obj, "name", "")
                and obj.__module__ == module.__name__
            ):
                register_driver(obj())


_discover()

__all__ = ["Driver", "DriverResult", "DRIVERS", "get_driver", "register_driver"]
