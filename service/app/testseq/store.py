"""Sequence persistence: the same atomic JSON state-file pattern the CAN
transmit list (``can/simulation.py``) and the action library
(``actions/registry.py``) use, so sequences survive a restart and stay
consistent across uvicorn workers.

Sequences live in one file (``test_sequences.json``), each carrying its own
``profile_id`` so a caller can filter to one vehicle's sequences without a
separate file per profile.
"""
from __future__ import annotations

import uuid
from typing import Any

from ..config import settings
from ..services.state import StateFile
from .model import Sequence


def _store() -> StateFile:
    return StateFile(settings.data_dir / "test_sequences.json", default={"sequences": []})


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def list_sequences(profile_id: int | None = None) -> list[dict[str, Any]]:
    docs = _store().read().get("sequences", [])
    if profile_id is not None:
        docs = [d for d in docs if d.get("profile_id") == profile_id]
    return docs


def get_sequence(sequence_id: str) -> dict[str, Any] | None:
    for doc in list_sequences():
        if doc.get("id") == sequence_id:
            return doc
    return None


def create_sequence(data: dict[str, Any]) -> dict[str, Any]:
    doc = dict(data)
    doc["id"] = doc.get("id") or _new_id()
    # Round-trip through the model so every step is normalized to the full
    # field set (missing fields get their defaults) before it is persisted.
    normalized = Sequence.from_dict(doc).to_dict()
    store = _store()
    doc_all = store.read()
    sequences = doc_all.get("sequences", [])
    sequences.append(normalized)
    doc_all["sequences"] = sequences
    store.write(doc_all)
    return normalized


def update_sequence(sequence_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    store = _store()
    doc_all = store.read()
    sequences = doc_all.get("sequences", [])
    for i, doc in enumerate(sequences):
        if doc.get("id") == sequence_id:
            updated = dict(data)
            updated["id"] = sequence_id
            normalized = Sequence.from_dict(updated).to_dict()
            sequences[i] = normalized
            doc_all["sequences"] = sequences
            store.write(doc_all)
            return normalized
    return None


def delete_sequence(sequence_id: str) -> bool:
    store = _store()
    doc_all = store.read()
    sequences = doc_all.get("sequences", [])
    remaining = [d for d in sequences if d.get("id") != sequence_id]
    if len(remaining) == len(sequences):
        return False
    doc_all["sequences"] = remaining
    store.write(doc_all)
    return True
