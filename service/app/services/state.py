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


# The mtime cache, per-path lock, and in-memory fallback live at module level
# keyed by the file path, NOT on the StateFile instance. Every consumer builds a
# fresh StateFile(path) on each access (a `_store()` helper returning a new
# instance is the pattern across the app), so an instance-held cache would reset
# on every call and never actually cache anything: each read would re-stat,
# re-read, and re-parse the file (multi-MB for the captures file) on every
# request. Keying the cache by path lets a fresh instance reuse the cached parse
# as long as the file has not changed on disk.
_registry_lock = threading.Lock()
_locks: dict[str, threading.Lock] = {}
_cache: dict[str, Any] = {}
_cache_mtime: dict[str, float | None] = {}
_memory: dict[str, Any] = {}


def _lock_for(key: str) -> threading.Lock:
    with _registry_lock:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock


class StateFile:
    """A single JSON document persisted atomically and cached by mtime.

    The cache is shared per file path across instances, so constructing a new
    StateFile for the same path (as every consumer does per call) reuses the
    cached parse rather than re-reading the file every time."""

    def __init__(self, path: Path, default: Any) -> None:
        self._path = Path(path)
        self._key = str(self._path)
        self._default = default
        self._lock = _lock_for(self._key)

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> Any:
        """Return the current document, re-reading only when the file changed."""
        with self._lock:
            if _memory.get(self._key) is not None:
                return _clone(_memory[self._key])
            try:
                mtime = self._path.stat().st_mtime
            except OSError:
                return _clone(self._default)
            if self._key in _cache and mtime == _cache_mtime.get(self._key):
                return _clone(_cache[self._key])
            try:
                data = json.loads(self._path.read_text())
            except (OSError, ValueError):
                return _clone(self._default)
            _cache[self._key] = data
            _cache_mtime[self._key] = mtime
            return _clone(data)

    def write(self, data: Any) -> None:
        """Persist the document atomically, falling back to memory on failure."""
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._path.with_name(self._path.name + ".tmp")
                tmp.write_text(json.dumps(data, indent=2))
                os.replace(tmp, self._path)
                _cache[self._key] = data
                try:
                    _cache_mtime[self._key] = self._path.stat().st_mtime
                except OSError:
                    _cache_mtime[self._key] = None
                _memory[self._key] = None
            except OSError:
                # Read-only data dir: keep the value in memory so the process
                # still behaves correctly until it can persist again.
                _memory[self._key] = data


def _clone(value: Any) -> Any:
    """Return a deep-ish copy so callers cannot mutate the cache in place."""
    if isinstance(value, (dict, list)):
        return json.loads(json.dumps(value))
    return value
