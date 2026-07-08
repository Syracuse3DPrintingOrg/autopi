import sys
from pathlib import Path

import pytest

# The app package lives under service/; make it importable like the app does.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "service"))
# The Stream Deck controller package lives under streamdeck/, run in place on
# an appliance (never pip-installed); make it importable the same way.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "streamdeck"))


@pytest.fixture(autouse=True)
def temp_data_dir(tmp_path, monkeypatch):
    """Point every state file at an isolated temp dir for each test."""
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return tmp_path
