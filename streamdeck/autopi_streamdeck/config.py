"""Controller configuration.

Settings come from a TOML file (default ``config.toml`` next to the package,
overridable with ``--config`` or ``AUTOPI_STREAMDECK_CONFIG``). Everything has
a sane default, so a deck plugged into a fresh appliance works with an empty
file as long as the app is on localhost.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

ENV_CONFIG = "AUTOPI_STREAMDECK_CONFIG"
ENV_BASE_URL = "AUTOPI_BASE_URL"

ALLOWED_ROTATIONS = (0, 90, 180, 270)
BRIGHTNESS_STEPS = (20, 40, 60, 80, 100)


@dataclass
class Config:
    base_url: str = "http://127.0.0.1:9284"
    brightness: int = 60
    rotation: int = 0
    poll_seconds: int = 5
    # Which shared surface this deck renders. Defaults to the streamdeck layout.
    surface: str = "streamdeck"

    def validated(self) -> "Config":
        self.base_url = self.base_url.rstrip("/")
        self.brightness = max(5, min(100, int(self.brightness)))
        if self.rotation not in ALLOWED_ROTATIONS:
            self.rotation = 0
        self.poll_seconds = max(1, int(self.poll_seconds))
        return self


def default_config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config.toml"


def resolved_config_path(path=None) -> Path:
    if path:
        return Path(path)
    if os.environ.get(ENV_CONFIG):
        return Path(os.environ[ENV_CONFIG])
    return default_config_path()


def load(path=None) -> Config:
    cfg = Config()
    resolved = resolved_config_path(path)
    if resolved.exists():
        data = tomllib.loads(resolved.read_text())
        for name in ("base_url", "surface"):
            if isinstance(data.get(name), str):
                setattr(cfg, name, data[name])
        for name in ("brightness", "rotation", "poll_seconds"):
            if isinstance(data.get(name), int) and not isinstance(data.get(name), bool):
                setattr(cfg, name, data[name])
    if os.environ.get(ENV_BASE_URL):
        cfg.base_url = os.environ[ENV_BASE_URL]
    return cfg.validated()
