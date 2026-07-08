"""Application configuration.

Settings resolve in this order, lowest priority first: built-in defaults, the
JSON file written by the setup page (``service/data/settings.json``), then
environment variables. Only keys listed in ``_SAVEABLE`` are persisted.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "AutoPi"
APP_VERSION = "0.1.22"

# Where the setup page writes persisted settings and where state files live.
_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Keys the setup page is allowed to persist to settings.json.
_SAVEABLE = (
    "theme_mode",
    "kiosk_enabled",
    "start_page_enabled",
    "streamdeck_enabled",
    "deck_model",
    "deck_rotation",
    "deck_brightness",
    "require_pin",
    "pin",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTOPI_", extra="ignore")

    # Where runtime state and settings live. Overridable for tests / packaging.
    data_dir: Path = _DEFAULT_DATA_DIR

    # Deployment mode: "server" or "pi_hosted".
    deployment_mode: str = "server"

    # UI
    theme_mode: str = "dark"
    start_page_enabled: bool = True
    kiosk_enabled: bool = False

    # Stream Deck
    streamdeck_enabled: bool = False
    # Key count of the configured deck model: 6 (Mini), 15 (MK.2), or 32 (XL).
    # Drives the editor grid when no deck reports a live count.
    deck_model: int = 15
    deck_rotation: int = 0
    deck_brightness: int = 60

    # Access control (optional PIN gate for the setup page).
    require_pin: bool = False
    pin: str = ""

    def load_saved(self) -> None:
        """Layer settings.json over the current values (in place)."""
        path = self.data_dir / "settings.json"
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for key in _SAVEABLE:
            if key in data:
                setattr(self, key, data[key])

    def save(self, updates: dict[str, Any]) -> None:
        """Persist the given saveable fields to settings.json atomically."""
        path = self.data_dir / "settings.json"
        current: dict[str, Any] = {}
        try:
            existing = json.loads(path.read_text())
            if isinstance(existing, dict):
                current = existing
        except (OSError, ValueError):
            pass
        for key, value in updates.items():
            if key in _SAVEABLE:
                current[key] = value
                setattr(self, key, value)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(current, indent=2))
        tmp.replace(path)


settings = Settings()
settings.load_saved()
