"""Built-in example scenarios: load a complete working setup in one click."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..examples import EXAMPLES

router = APIRouter(prefix="/examples", tags=["examples"])


@router.get("")
def list_examples():
    return {"examples": [
        {"key": key, "name": ex["name"], "description": ex["description"], "loaded": ex["is_loaded"]()}
        for key, ex in EXAMPLES.items()
    ]}


@router.post("/{key}/load")
def load_example(key: str):
    ex = EXAMPLES.get(key)
    if ex is None:
        raise HTTPException(404, f"No example named {key}")
    try:
        return ex["load"]()
    except Exception as exc:
        raise HTTPException(400, f"Could not load example: {exc}")
