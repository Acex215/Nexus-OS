"""Tests for change_analyzer.py — Phase 4 Knowledge & Learning."""

import subprocess
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import change_analyzer as ca


def _ts(hours_ago: float) -> str:
    """ISO-8601 timestamp that is *hours_ago* hours before now."""
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.isoformat()


def _entry(task_id: str, success: bool, hours_ago: float = 1.0, files: list = None) -> dict:
    return {
        "id":             f"log-{task_id}",
        "task_id":        task_id,
        "description":    f"Task {task_id} description",
        "status":         "done" if success else "failed",
        "success":        success,
        "error":          None if success else "timeout error",
        "affected_files": files or [],
        "files_changed":  len(files or []),
        "lines_added":    10,
        "lines_removed":  2,
        "duration_seconds": 5.0,
        "timestamp":      _ts(hours_ago),
    }


_EMPTY_GIT = MagicMock(returncode=0, stdout="", stderr="")


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_get_changes_empty():
    with patch("change_analyzer.read_recent_logs", return_value=[]), \
         patch("change_analyzer.subprocess.run", return_value=_EMPTY_GIT):
        result = ca.get_changes_since(24)

    assert result["period_hours"] == 24
    assert result["task_summary"]["total"] == 0
    assert result["task_summary"]["succeeded"] == 0
    assert result["task_summary"]["failed"] == 0
    assert result["task_summary"]["tasks"] == []
    assert result["git_summary"]["commit_count"] == 0
    assert result["git_summary"]["commits"] == []
    assert result["files_touched"] == []


def test_get_changes_filters_by_time():
    entries = [
        _entry("t1", True,  hours_ago=0.5),
        _entry("t2", False, hours_ago=2.0),
        _entry("t3", True,  hours_ago=10.0),
        _entry("t4", True,  hours_ago=30.0),   # outside 24h window
        _entry("t5", False, hours_ago=48.0),   # outside 24h window
    ]
    with patch("change_analyzer.read_recent_logs", return_value=entries), \
         patch("change_analyzer.subprocess.run", return_value=_EMPTY_GIT):
        result = ca.get_changes_since(24)

    assert result["task_summary"]["total"] == 3
    ids = {t["task_id"] for t in result["task_summary"]["tasks"]}
    assert ids == {"t1", "t2", "t3"}
    assert result["task_summary"]["succeeded"] == 2
    assert result["task_summary"]["failed"] == 1


def test_format_report_with_data():
    entries = [
        _entry("task-001", True,  hours_ago=1.0, files=["/opt/nexus/agents/foo.py"]),
        _entry("task-002", False, hours_ago=2.0),
        _entry("task-003", True,  hours_ago=3.0, files=["/opt/nexus/agents/bar.py"]),
    ]
    git_mock = MagicMock(
        returncode=0,
        stdout="abc1234 feat: Phase 3 safety gates\ndef5678 fix: remove debug log\n",
        stderr="",
    )
    with patch("change_analyzer.read_recent_logs", return_value=entries), \
         patch("change_analyzer.subprocess.run", return_value=git_mock):
        report = ca.format_changes_report(24)

    assert "📋 **Changes in the last 24h**" in report
    assert "**Tasks:**" in report
    assert "task-001" in report
    assert "task-002" in report
    assert "task-003" in report
    assert "✅" in report
    assert "❌" in report
    assert "**Git commits:** 2" in report
    assert "abc1234" in report
    assert "def5678" in report
    assert "**Files touched:** 2" in report


def test_format_report_empty():
    with patch("change_analyzer.read_recent_logs", return_value=[]), \
         patch("change_analyzer.subprocess.run", return_value=_EMPTY_GIT):
        report = ca.format_changes_report(24)

    assert "No changes recorded in the last 24h." == report


def test_git_subprocess_failure():
    entries = [_entry("t1", True, hours_ago=1.0)]
    with patch("change_analyzer.read_recent_logs", return_value=entries), \
         patch("change_analyzer.subprocess.run", side_effect=OSError("git not found")):
        # Should not raise — git failure is handled gracefully
        result = ca.get_changes_since(24)

    assert result["task_summary"]["total"] == 1
    assert result["git_summary"]["commit_count"] == 0
    assert result["git_summary"]["commits"] == []
