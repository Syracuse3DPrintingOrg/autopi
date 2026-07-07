"""Atomic JSON state files shared across uvicorn workers.

Cross-surface state (the layout, the active page, the action library) is kept
in small JSON files under data_dir. Writes go through a temp file plus
``os.replace`` so a reader never sees a half-written file, reads are cached on
the file's mtime, and an unwritable data dir degrades to in-memory state
instead of crashing. This is the same pattern the source project used to keep
several workers and the Stream Deck controller in agreement.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


class StateFile:
    """A single JSON document persisted atomically and cached by mtime."""

    def __init__(self, path: Path, default: Any) -> None:
        self._path = Path(path)
        self._default = default
        self._lock = threading.Lock()
        self._cache: Any = None
        self._cache_mtime: float | None = None
        # In-memory fallback used when the data dir cannot be written.
        self._memory: Any = None

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> Any:
        """Return the current document, re-reading only when the file changed."""
        with self._lock:
            if self._memory is not None:
                return _clone(self._memory)
            try:
                mtime = self._path.stat().st_mtime
            except OSError:
                return _clone(self._default)
            if self._cache is not None and mtime == self._cache_mtime:
                return _clone(self._cache)
            try:
                data = json.loads(self._path.read_text())
            except (OSError, ValueError):
                return _clone(self._default)
            self._cache = data
            self._cache_mtime = mtime
            return _clone(data)

    def write(self, data: Any) -> None:
        """Persist the document atomically, falling back to memory on failure."""
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._path.with_name(self._path.name + ".tmp")
                tmp.write_text(json.dumps(data, indent=2))
                os.replace(tmp, self._path)
                self._cache = data
                try:
                    self._cache_mtime = self._path.stat().st_mtime
                except OSError:
                    self._cache_mtime = None
                self._memory = None
            except OSError:
                # Read-only data dir: keep the value in memory so the process
                # still behaves correctly until it can persist again.
                self._memory = data


def _clone(value: Any) -> Any:
    """Return a deep-ish copy so callers cannot mutate the cache in place."""
    if isinstance(value, (dict, list)):
        return json.loads(json.dumps(value))
    return value
