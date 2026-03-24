"""Tests for failure_analyzer.py — Phase 4 Knowledge & Learning."""

from unittest.mock import patch

import failure_analyzer as fa


def _entry(task_id: str, success: bool, error: str = None, duration: float = 1.0) -> dict:
    return {
        "id": f"log-{task_id}",
        "task_id": task_id,
        "description": f"Task {task_id}",
        "success": success,
        "status": "done" if success else "failed",
        "error": error,
        "duration_seconds": duration,
        "timestamp": "2026-03-19T00:00:00+00:00",
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_analyze_empty():
    with patch("failure_analyzer.read_recent_logs", return_value=[]):
        result = fa.analyze_failures()

    assert result["total_tasks"] == 0
    assert result["total_failures"] == 0
    assert result["success_rate"] == 0.0
    assert result["most_common_errors"] == []
    assert result["avg_duration_success"] == 0.0
    assert result["avg_duration_failure"] == 0.0
    for cat in ("context_overflow", "scope_violation", "missing_file",
                "coder_partial", "timeout", "lm_unavailable", "other"):
        assert result["failure_categories"][cat] == 0


def test_analyze_mixed():
    # newest first (as read_recent_logs returns)
    entries = [
        _entry("t8", True,  duration=10.0),
        _entry("t7", True,  duration=8.0),
        _entry("t6", False, error="context length exceeded for coordinator", duration=5.0),
        _entry("t5", True,  duration=6.0),
        _entry("t4", False, error="scope violation: out of scope path", duration=3.0),
        _entry("t3", True,  duration=4.0),
        _entry("t2", False, error="connection refused to LM studio", duration=2.0),
        _entry("t1", True,  duration=1.0),
    ]
    with patch("failure_analyzer.read_recent_logs", return_value=entries):
        result = fa.analyze_failures()

    assert result["total_tasks"] == 8
    assert result["total_failures"] == 3
    assert result["success_rate"] == round(5 / 8 * 100, 1)
    assert result["failure_categories"]["context_overflow"] == 1
    assert result["failure_categories"]["scope_violation"] == 1
    assert result["failure_categories"]["lm_unavailable"] == 1
    assert result["failure_categories"]["other"] == 0
    assert len(result["most_common_errors"]) == 3  # 3 distinct errors


def test_categorization():
    entries = [
        _entry("c1", False, error="token limit exceeded"),
        _entry("c2", False, error="scope violation detected"),
        _entry("c3", False, error="file not found at path"),
        _entry("c4", False, error="no such file or directory"),
        _entry("c5", False, error="partial patch applied only"),
        _entry("c6", False, error="only patched 2 of 4 call sites"),
        _entry("c7", False, error="request timeout after 30s"),
        _entry("c8", False, error="timed out waiting for response"),
        _entry("c9", False, error="connection refused on port 1234"),
        _entry("c10", False, error="endpoint unreachable"),
        _entry("c11", False, error="something completely different"),
    ]
    with patch("failure_analyzer.read_recent_logs", return_value=entries):
        result = fa.analyze_failures()

    cats = result["failure_categories"]
    assert cats["context_overflow"] == 1   # token limit exceeded
    assert cats["scope_violation"] == 1    # scope violation
    assert cats["missing_file"] == 2       # not found + no such file
    assert cats["coder_partial"] == 2      # partial + only patched
    assert cats["timeout"] == 2            # timeout + timed out
    assert cats["lm_unavailable"] == 2     # connection refused + unreachable
    assert cats["other"] == 1              # something completely different


def test_format_report():
    entries = [
        _entry("t1", True,  duration=5.0),
        _entry("t2", False, error="context length exceeded", duration=3.0),
        _entry("t3", False, error="scope violation in path", duration=2.0),
    ]
    with patch("failure_analyzer.read_recent_logs", return_value=entries):
        report = fa.format_failure_report()

    assert "📊 **Failure Analysis**" in report
    assert "Success rate:" in report
    assert "Avg duration:" in report
    assert "Current streak:" in report
    assert "**Failure categories:**" in report
    assert "**Recommendations:**" in report
    assert "Context overflow" in report
    assert "Scope violation" in report


def test_recent_streak():
    # newest first: success, success, failure, success, success, success
    entries = [
        _entry("t6", True),
        _entry("t5", True),
        _entry("t4", False, error="oops"),
        _entry("t3", True),
        _entry("t2", True),
        _entry("t1", True),
    ]
    with patch("failure_analyzer.read_recent_logs", return_value=entries):
        result = fa.analyze_failures()

    assert result["recent_streak"] == "success x 2"
