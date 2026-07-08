"""The device-local logging journal.

A standalone, always-on-the-SD-card record of what the device did: actions
run, CAN traffic of interest, and (later) test steps and results written by
the Phase 5 test runner. Records are appended as JSON lines to a file per
day under ``data_dir/logs`` (``autopi-YYYYMMDD.jsonl``) so a single day's log
stays a manageable, greppable size and old days are easy to prune.

Writing goes through a plain append (not the atomic ``StateFile`` pattern
used elsewhere): a journal is a growing log, not a document that gets
replaced wholesale, and an append is already safe against a half-written
record as long as each write is one line. Reads are only ever used for the
UI and API, never for state another part of the app depends on, so a partial
last line (a crash mid-write) is simply skipped instead of failing the read.

Kept deliberately small and stable: ``log_event`` is the one function other
subsystems (the actions registry, later the test runner) call.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import settings

_FILE_PREFIX = "autopi-"
_FILE_SUFFIX = ".jsonl"
_NAME_RE = re.compile(r"^autopi-\d{8}\.jsonl$")


def _logs_dir() -> Path:
    return settings.data_dir / "logs"


def enabled() -> bool:
    """Whether the journal should record events (the settings toggle)."""
    return bool(getattr(settings, "logging_enabled", True))


def _day_filename(when: datetime) -> str:
    return f"{_FILE_PREFIX}{when.strftime('%Y%m%d')}{_FILE_SUFFIX}"


def make_record(kind: str, message: str, data: dict[str, Any] | None,
                 when: datetime | None = None) -> dict[str, Any]:
    """Build a single journal record. Pure, so it is easy to unit test."""
    when = when or datetime.now(timezone.utc)
    return {
        "ts": when.isoformat(timespec="milliseconds"),
        "kind": kind,
        "message": message,
        "data": data or {},
    }


def log_event(kind: str, message: str, data: dict[str, Any] | None = None) -> None:
    """Append one event to today's journal file.

    Silently does nothing when logging is disabled or the data dir cannot be
    written, so a call site never has to guard this itself. ``kind`` is a
    free-form label ("action", "can", "test_step", "test_result", ...).
    """
    if not enabled():
        return
    record = make_record(kind, message, data)
    line = json.dumps(record) + "\n"
    logs_dir = _logs_dir()
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        path = logs_dir / _day_filename(datetime.now(timezone.utc))
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        # Read-only data dir: drop the event rather than crash the caller.
        return
    _prune_old_files(logs_dir)


def parse_lines(text: str) -> list[dict[str, Any]]:
    """Parse journal file text into records, skipping any malformed line.

    A malformed trailing line (a crash mid-write) is skipped rather than
    failing the whole read.
    """
    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _iter_files(logs_dir: Path) -> list[Path]:
    if not logs_dir.is_dir():
        return []
    return sorted(
        (p for p in logs_dir.iterdir() if p.is_file() and _NAME_RE.match(p.name)),
        reverse=True,
    )


def retention_days() -> int:
    days = getattr(settings, "log_retention_days", 14)
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 14
    return max(days, 1)


def files_to_prune(names: list[str], keep_days: int, today: str) -> list[str]:
    """Pure helper: given sorted journal filenames (newest first) and the
    current day-string (YYYYMMDD), return the names outside the retention
    window. Split out so rotation/pruning logic is testable without touching
    the filesystem.
    """
    cutoff = _shift_day(today, -(keep_days - 1))
    return [n for n in names if _NAME_RE.match(n) and _day_from_name(n) < cutoff]


def _day_from_name(name: str) -> str:
    return name[len(_FILE_PREFIX):len(_FILE_PREFIX) + 8]


def _shift_day(day: str, delta_days: int) -> str:
    dt = datetime.strptime(day, "%Y%m%d") + _timedelta(delta_days)
    return dt.strftime("%Y%m%d")


def _timedelta(days: int):
    from datetime import timedelta
    return timedelta(days=days)


def _prune_old_files(logs_dir: Path) -> None:
    files = _iter_files(logs_dir)
    names = [p.name for p in files]
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    stale = set(files_to_prune(names, retention_days(), today))
    if not stale:
        return
    for p in files:
        if p.name in stale:
            try:
                p.unlink()
            except OSError:
                pass


def recent(limit: int = 200, kind: str | None = None) -> list[dict[str, Any]]:
    """The most recent events, newest first, optionally filtered by kind.

    Reads today's file and, if it does not have enough records yet, the
    previous day's, so a request just after midnight still returns a full
    page.
    """
    logs_dir = _logs_dir()
    files = _iter_files(logs_dir)
    out: list[dict[str, Any]] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        records = parse_lines(text)
        records.reverse()
        if kind:
            records = [r for r in records if r.get("kind") == kind]
        out.extend(records)
        if len(out) >= limit:
            break
    return out[:limit]


def list_files() -> list[dict[str, Any]]:
    """Journal files on disk: name, size in bytes, and mtime (epoch seconds)."""
    logs_dir = _logs_dir()
    out = []
    for path in _iter_files(logs_dir):
        try:
            stat = path.stat()
        except OSError:
            continue
        out.append({"name": path.name, "size": stat.st_size, "modified": stat.st_mtime})
    return out


def safe_filename(name: str) -> str | None:
    """Validate a journal filename against path traversal / arbitrary reads.

    Returns the name unchanged when it matches the expected
    ``autopi-YYYYMMDD.jsonl`` shape, otherwise ``None``. Pure, so the guard
    is testable without touching the filesystem.
    """
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        return None
    if not _NAME_RE.match(name):
        return None
    return name


def read_file(name: str) -> str | None:
    """Return a journal file's raw contents, or ``None`` if the name is
    invalid or the file does not exist."""
    safe = safe_filename(name)
    if safe is None:
        return None
    path = _logs_dir() / safe
    try:
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def clear() -> int:
    """Delete every journal file. Returns the count removed."""
    logs_dir = _logs_dir()
    removed = 0
    for path in _iter_files(logs_dir):
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed
