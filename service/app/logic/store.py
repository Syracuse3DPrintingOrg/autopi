"""Where logic rules persist for now.

Rules are plain, JSON-serializable dicts (``Rule.to_dict``), written
atomically through the same ``StateFile`` helper as ``actions.json`` and
``layout.json``. This is a placeholder store: the dependent bead
(AutoPi-j8t, the SQLite database) is expected to replace it with a real
table without changing ``Rule``'s serializable shape or the engine above.
"""
from __future__ import annotations

from ..config import settings
from ..services.state import StateFile
from .rule import Rule


def _store() -> StateFile:
    return StateFile(settings.data_dir / "logic.json", default={"rules": []})


def load_rules() -> list[Rule]:
    doc = _store().read()
    rules: list[Rule] = []
    for raw in doc.get("rules", []):
        if isinstance(raw, dict) and raw.get("id"):
            rules.append(Rule.from_dict(raw))
    return rules


def save_rules(rules: list[Rule]) -> None:
    _store().write({"rules": [r.to_dict() for r in rules]})
