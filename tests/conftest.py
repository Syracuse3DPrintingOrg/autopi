import sys
from pathlib import Path

import pytest

# The app package lives under service/; make it importable like the app does.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "service"))


@pytest.fixture(autouse=True)
def temp_data_dir(tmp_path, monkeypatch):
    """Point every state file at an isolated temp dir for each test."""
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    # The logic runtime keeps one Engine alive for its whole life so rule
    # state (edges, timers, latches, rising/falling memory) survives between
    # scans; reset it between tests so one test's scan history never leaks
    # into the next.
    from app.logic.runtime import runtime as logic_runtime
    logic_runtime._engine.reset()
    logic_runtime._engine.rules = []

    return tmp_path
