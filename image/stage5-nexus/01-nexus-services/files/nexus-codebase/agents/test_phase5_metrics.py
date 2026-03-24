"""Tests for metrics.py — Phase 5 Performance Metrics."""

from unittest.mock import patch

import metrics


def _entry(task_id: str, success: bool, duration: float = 1.0, error: str = None, hours_ago: float = 1.0) -> dict:
    return {
        "id": f"log-{task_id}",
        "task_id": task_id,
        "description": f"Task {task_id}",
        "status": "success" if success else "failed",
        "success": success,
        "error": error,
        "duration_seconds": duration,
        "timestamp": f"2026-03-21T00:00:00+00:00",
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_summary_empty():
    with patch("task_logger.read_recent_logs", return_value=[]), \
         patch("failure_analyzer.analyze_failures", return_value={"categories": {}, "top_errors": []}):
        result = metrics.get_performance_summary(24)

    assert result["window_hours"] == 24
    assert result["total_tasks"] == 0
    assert result["success_rate"] == 0.0
    assert result["avg_duration_seconds"] == 0.0
    assert result["rollback_count"] == 0
    assert result["tasks_per_hour"] == 0.0
    assert result["failure_categories"] == {}
    assert result["top_errors"] == []
    assert result["trend"] == "stable"


def test_summary_mixed():
    entries = [
        _entry("t1", True,  duration=10.0),
        _entry("t2", True,  duration=6.0),
        _entry("t3", False, duration=2.0, error="context overflow"),
        _entry("t4", True,  duration=4.0),
        _entry("t5", False, duration=3.0, error="scope violation"),
    ]
    fa_result = {"categories": {"context_overflow": 1, "scope_violation": 1}, "top_errors": ["context overflow"]}
    with patch("task_logger.read_recent_logs", return_value=entries), \
         patch("failure_analyzer.analyze_failures", return_value=fa_result):
        result = metrics.get_performance_summary(24)

    assert result["total_tasks"] == 5
    assert result["rollback_count"] == 2
    assert result["success_rate"] == round(3 / 5 * 100, 1)
    assert result["avg_duration_seconds"] == round((10.0 + 6.0 + 2.0 + 4.0 + 3.0) / 5, 2)
    assert result["tasks_per_hour"] == round(5 / 24, 2)
    assert result["failure_categories"] == {"context_overflow": 1, "scope_violation": 1}
    assert result["top_errors"] == ["context overflow"]


def test_trend_improving():
    # First half: 1/4 success (25%), second half: 4/4 success (100%) → improving
    entries = [
        _entry("t1", False),
        _entry("t2", False),
        _entry("t3", False),
        _entry("t4", True),
        _entry("t5", True),
        _entry("t6", True),
        _entry("t7", True),
        _entry("t8", True),
    ]
    with patch("task_logger.read_recent_logs", return_value=entries), \
         patch("failure_analyzer.analyze_failures", return_value={"categories": {}, "top_errors": []}):
        result = metrics.get_performance_summary(24)

    assert result["trend"] == "improving"


def test_trend_degrading():
    # First half: 4/4 success (100%), second half: 1/4 success (25%) → degrading
    entries = [
        _entry("t1", True),
        _entry("t2", True),
        _entry("t3", True),
        _entry("t4", True),
        _entry("t5", False),
        _entry("t6", False),
        _entry("t7", False),
        _entry("t8", True),
    ]
    with patch("task_logger.read_recent_logs", return_value=entries), \
         patch("failure_analyzer.analyze_failures", return_value={"categories": {}, "top_errors": []}):
        result = metrics.get_performance_summary(24)

    assert result["trend"] == "degrading"


def test_trend_stable():
    # First half: 3/4 (75%), second half: 3/4 (75%) → stable (diff == 0)
    entries = [
        _entry("t1", True),
        _entry("t2", True),
        _entry("t3", True),
        _entry("t4", False),
        _entry("t5", True),
        _entry("t6", True),
        _entry("t7", True),
        _entry("t8", False),
    ]
    with patch("task_logger.read_recent_logs", return_value=entries), \
         patch("failure_analyzer.analyze_failures", return_value={"categories": {}, "top_errors": []}):
        result = metrics.get_performance_summary(24)

    assert result["trend"] == "stable"


def test_format_report():
    summary = {
        "window_hours": 24,
        "total_tasks": 10,
        "success_rate": 80.0,
        "avg_duration_seconds": 5.5,
        "rollback_count": 2,
        "tasks_per_hour": 0.42,
        "failure_categories": {"context_overflow": 1, "timeout": 1},
        "top_errors": [],
        "trend": "improving",
    }
    report = metrics.format_metrics_report(summary)

    assert "Performance Dashboard" in report
    assert "last 24h" in report
    assert "Tasks: 10" in report
    assert "Success: 80.0%" in report
    assert "Avg: 5.5s" in report
    assert "0.42/hr" in report
    assert "Rollbacks: 2" in report
    assert "improving" in report
    assert "context_overflow" in report
    assert "timeout" in report


def test_should_propose_low_success():
    summary = {
        "window_hours": 24,
        "total_tasks": 10,
        "success_rate": 60.0,
        "avg_duration_seconds": 3.0,
        "rollback_count": 4,
        "tasks_per_hour": 0.5,
        "failure_categories": {},
        "top_errors": [],
        "trend": "stable",
    }
    should, reason = metrics.should_propose_improvement(summary)

    assert should is True
    assert "60.0%" in reason
    assert "Low success rate" in reason


def test_should_propose_high_category():
    summary = {
        "window_hours": 24,
        "total_tasks": 10,
        "success_rate": 75.0,
        "avg_duration_seconds": 3.0,
        "rollback_count": 4,
        "tasks_per_hour": 0.5,
        # context_overflow = 3/4 = 75% of failures → over 30% threshold
        "failure_categories": {"context_overflow": 3, "other": 1},
        "top_errors": [],
        "trend": "stable",
    }
    should, reason = metrics.should_propose_improvement(summary)

    assert should is True
    assert "context_overflow" in reason


def test_should_not_propose_healthy():
    summary = {
        "window_hours": 24,
        "total_tasks": 20,
        "success_rate": 90.0,
        "avg_duration_seconds": 3.0,
        "rollback_count": 2,
        "tasks_per_hour": 1.0,
        # 4 failures spread across 4 categories → each 25%, all under 30%
        "failure_categories": {"context_overflow": 1, "timeout": 1, "missing_file": 1, "other": 1},
        "top_errors": [],
        "trend": "stable",
    }
    should, reason = metrics.should_propose_improvement(summary)

    assert should is False
    assert reason == ""
