"""The logging journal: append, read, rotation/pruning math, and the
path-traversal guard on file reads.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.services import journal


def test_make_record_shape():
    when = datetime(2026, 7, 8, 12, 30, 0, tzinfo=timezone.utc)
    record = journal.make_record("action", "Ran page_next", {"ok": True}, when=when)
    assert record["kind"] == "action"
    assert record["message"] == "Ran page_next"
    assert record["data"] == {"ok": True}
    assert record["ts"].startswith("2026-07-08T12:30:00")


def test_parse_lines_skips_malformed_and_non_dict():
    text = '{"kind": "a"}\nnot json\n[1,2,3]\n{"kind": "b"}\n\n'
    records = journal.parse_lines(text)
    assert [r["kind"] for r in records] == ["a", "b"]


def test_files_to_prune_keeps_window():
    names = ["autopi-20260708.jsonl", "autopi-20260707.jsonl", "autopi-20260601.jsonl"]
    stale = journal.files_to_prune(names, keep_days=14, today="20260708")
    assert stale == ["autopi-20260601.jsonl"]


def test_files_to_prune_none_when_all_recent():
    names = ["autopi-20260708.jsonl", "autopi-20260707.jsonl"]
    assert journal.files_to_prune(names, keep_days=14, today="20260708") == []


def test_safe_filename_rejects_traversal():
    assert journal.safe_filename("../../etc/passwd") is None
    assert journal.safe_filename("..") is None
    assert journal.safe_filename("/etc/passwd") is None
    assert journal.safe_filename("autopi-20260708.jsonl/../x") is None
    assert journal.safe_filename("not-a-log.txt") is None


def test_safe_filename_accepts_expected_shape():
    assert journal.safe_filename("autopi-20260708.jsonl") == "autopi-20260708.jsonl"


def test_log_event_and_recent_round_trip(temp_data_dir):
    journal.log_event("action", "Ran page_next", {"action_id": "page_next"})
    journal.log_event("can", "Frame seen")
    events = journal.recent(limit=10)
    assert len(events) == 2
    # Newest first.
    assert events[0]["kind"] == "can"
    assert events[1]["kind"] == "action"


def test_log_event_filters_by_kind(temp_data_dir):
    journal.log_event("action", "a")
    journal.log_event("can", "c")
    events = journal.recent(kind="can")
    assert len(events) == 1
    assert events[0]["kind"] == "can"


def test_log_event_noop_when_disabled(temp_data_dir, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "logging_enabled", False)
    journal.log_event("action", "should not be recorded")
    assert journal.recent() == []


def test_list_files_and_read_file(temp_data_dir):
    journal.log_event("action", "hello")
    files = journal.list_files()
    assert len(files) == 1
    name = files[0]["name"]
    text = journal.read_file(name)
    assert text is not None
    assert "hello" in text


def test_read_file_rejects_traversal(temp_data_dir):
    journal.log_event("action", "hello")
    assert journal.read_file("../settings.json") is None
    assert journal.read_file("does-not-exist.jsonl") is None


def test_clear_removes_all_files(temp_data_dir):
    journal.log_event("action", "hello")
    assert len(journal.list_files()) == 1
    removed = journal.clear()
    assert removed == 1
    assert journal.list_files() == []
    assert journal.recent() == []


def test_recent_respects_limit(temp_data_dir):
    for i in range(5):
        journal.log_event("action", f"event {i}")
    assert len(journal.recent(limit=2)) == 2
