"""Tests for task_logger.py — Phase 4 Knowledge & Learning."""

import asyncio
import json
from pathlib import Path

import pytest
import pytest_asyncio

import task_logger as tl

# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_TASK = {
    "id": "task-001",
    "description": "Add unit tests for auth module",
    "priority": "P1",
    "risk": "low",
    "affected_files": ["/opt/nexus/agents/auth.py"],
    "sub_task_of": None,
}

SAMPLE_RESULT_OK = {
    "success": True,
    "commit_hash": "abc1234",
    "blockchain_tx": "0xdeadbeef",
    "branch": "task/task-001",
    "diffs": ["--- a/auth.py\n+++ b/auth.py\n@@ -1 +1 @@"],
    "lines_added": 10,
    "lines_removed": 2,
    "files_changed": 1,
    "error": None,
}

SAMPLE_RESULT_FAIL = {
    "success": False,
    "commit_hash": None,
    "blockchain_tx": None,
    "branch": "task/task-002",
    "diffs": [],
    "lines_added": 0,
    "lines_removed": 0,
    "files_changed": 0,
    "error": "Compilation error on line 42",
}


def make_task(task_id: str, **kwargs) -> dict:
    t = dict(SAMPLE_TASK)
    t["id"] = task_id
    t.update(kwargs)
    return t


def make_result(success: bool) -> dict:
    return dict(SAMPLE_RESULT_OK if success else SAMPLE_RESULT_FAIL)


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_log_task_creates_file(tmp_path):
    log_file = tmp_path / "task_log.jsonl"
    await tl.log_task(SAMPLE_TASK, SAMPLE_RESULT_OK, _log_file=log_file)
    assert log_file.exists()
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1


@pytest.mark.asyncio
async def test_log_task_fields(tmp_path):
    log_file = tmp_path / "task_log.jsonl"
    entry_id = await tl.log_task(SAMPLE_TASK, SAMPLE_RESULT_OK, _log_file=log_file)

    line = log_file.read_text(encoding="utf-8").strip()
    entry = json.loads(line)

    expected_fields = [
        "id", "task_id", "description", "priority", "risk", "affected_files",
        "status", "success", "error", "commit_hash", "blockchain_tx", "branch",
        "diffs", "lines_added", "lines_removed", "files_changed",
        "plan_summary", "duration_seconds", "timestamp", "sub_task_of",
    ]
    for field in expected_fields:
        assert field in entry, f"Missing field: {field}"

    assert entry["id"] == entry_id
    assert entry["task_id"] == "task-001"
    assert entry["success"] is True
    assert entry["status"] == "done"
    assert entry["commit_hash"] == "abc1234"
    assert entry["error"] is None
    assert entry["lines_added"] == 10


@pytest.mark.asyncio
async def test_log_task_append(tmp_path):
    log_file = tmp_path / "task_log.jsonl"
    for i in range(3):
        await tl.log_task(make_task(f"task-{i:03d}"), make_result(True), _log_file=log_file)

    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3


@pytest.mark.asyncio
async def test_read_recent_logs(tmp_path):
    log_file = tmp_path / "task_log.jsonl"
    for i in range(5):
        await tl.log_task(make_task(f"task-{i:03d}"), make_result(True), _log_file=log_file)

    entries = tl.read_recent_logs(3, _log_file=log_file)
    assert len(entries) == 3
    # newest first — task-004 should be first
    assert entries[0]["task_id"] == "task-004"
    assert entries[1]["task_id"] == "task-003"
    assert entries[2]["task_id"] == "task-002"


@pytest.mark.asyncio
async def test_read_failed_logs(tmp_path):
    log_file = tmp_path / "task_log.jsonl"
    for i in range(3):
        await tl.log_task(make_task(f"ok-{i}"), make_result(True), _log_file=log_file)
    for i in range(2):
        await tl.log_task(make_task(f"fail-{i}"), make_result(False), _log_file=log_file)

    failed = tl.read_failed_logs(20, _log_file=log_file)
    assert len(failed) == 2
    for e in failed:
        assert e["success"] is False


def test_read_missing_file(tmp_path):
    log_file = tmp_path / "nonexistent.jsonl"
    result = tl.read_recent_logs(10, _log_file=log_file)
    assert result == []


def test_corrupt_line_handling(tmp_path):
    log_file = tmp_path / "task_log.jsonl"
    # Write one corrupt line and one valid line
    valid_entry = {
        "id": "log-valid",
        "task_id": "task-good",
        "description": "good task",
        "priority": "P1",
        "risk": "low",
        "affected_files": [],
        "status": "done",
        "success": True,
        "error": None,
        "commit_hash": "aaa",
        "blockchain_tx": None,
        "branch": "main",
        "diffs": [],
        "lines_added": 1,
        "lines_removed": 0,
        "files_changed": 1,
        "plan_summary": None,
        "duration_seconds": 1.0,
        "timestamp": "2026-03-19T00:00:00+00:00",
        "sub_task_of": None,
    }
    log_file.write_text(
        "{this is not valid json}\n" + json.dumps(valid_entry) + "\n",
        encoding="utf-8",
    )

    entries = tl.read_recent_logs(10, _log_file=log_file)
    assert len(entries) == 1
    assert entries[0]["task_id"] == "task-good"
