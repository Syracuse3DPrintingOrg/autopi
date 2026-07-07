"""Rules: the serializable shape the engine evaluates.

A ``Rule`` is data, not behavior: an id, a condition tree (see
``conditions.py`` for the node shapes), the action ids to fire, and how
firing is gated (``trigger``). ``from_dict``/``to_dict`` make it a plain
JSON document today (see ``store.py``); a later bead can swap that storage
for a database table without touching this shape.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Rule:
    id: str
    name: str = ""
    # A condition node (see conditions.py). Defaults to an always-false leaf
    # so a freshly constructed Rule is inert until configured.
    condition: dict[str, Any] = field(
        default_factory=lambda: {"type": "bool", "signal": "", "negate": False}
    )
    # Action ids to fire when this rule's output is true (or transitions,
    # depending on `trigger`). The engine only returns these ids; dispatching
    # them to app.actions.registry is the caller's job.
    actions: list[str] = field(default_factory=list)
    # "level": fire every scan the condition is true (an energized PLC coil).
    # "rising": fire only the scan the output goes false -> true.
    # "falling": fire only the scan the output goes true -> false.
    trigger: str = "level"
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Rule":
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(**known)
