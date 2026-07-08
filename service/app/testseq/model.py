"""Test sequence data model: a :class:`Step` and a :class:`Sequence` of them.

Kept as plain dataclasses with ``to_dict``/``from_dict`` (the same shape
``ActionSpec`` in ``actions/registry.py`` and a transmit entry in
``can/simulation.py`` use), so a sequence round-trips straight to and from
the JSON state file with no schema migration needed when a new step field
shows up later.

A :class:`Step` carries every field any step type might use; only the ones
relevant to its ``type`` are read. That keeps the model flat and easy to
serialize instead of a tagged union, matching the rest of the app's state
files.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# The five step types the runner understands.
STEP_TYPES = ("send", "expect", "prompt", "delay", "action")

# Comparison operators an "expect" step can check a decoded signal with.
COMPARE_OPS = ("==", "!=", "<", "<=", ">", ">=")


@dataclass
class Step:
    id: str
    type: str = "send"
    label: str = ""

    # -- send / expect: which CAN command or response to match ------------
    channel: str = "can0"
    backend: str = "socketcan"
    arbitration_id: str = ""  # hex ("0x100") or decimal, parsed at run time
    data: str = ""            # raw hex bytes, e.g. "02 01 0C" (send, no database)
    database_id: int | None = None
    message: str | int | None = None
    signals: dict[str, Any] = field(default_factory=dict)
    is_fd: bool = False
    is_extended_id: bool = False

    # -- expect: how long to wait, and an optional decoded signal check ---
    timeout_ms: int = 2000
    signal_name: str = ""
    op: str = "=="
    value: Any = None

    # -- prompt: what to ask the operator ----------------------------------
    prompt_text: str = ""

    # -- delay: how long to wait, in milliseconds --------------------------
    delay_ms: int = 0

    # -- action: an existing action id to run -------------------------------
    action_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Step":
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(**known)


@dataclass
class Sequence:
    id: str
    name: str = ""
    profile_id: int | None = None
    steps: list[Step] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "profile_id": self.profile_id,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Sequence":
        steps = [Step.from_dict(s) for s in data.get("steps", []) if isinstance(s, dict)]
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            profile_id=data.get("profile_id"),
            steps=steps,
        )
