"""Tests for knowledge_planner.py — Phase 4 Knowledge & Learning."""

from unittest.mock import patch

import pytest

import knowledge_planner as kp

# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_result(
    task_id: str,
    description: str,
    success: bool,
    error: str = "none",
    status: str = None,
    duration_seconds: float = 1.0,
) -> dict:
    return {
        "task_id":          task_id,
        "description":      description,
        "status":           status or ("done" if success else "failed"),
        "error":            error,
        "success":          success,
        "timestamp":        "2026-03-19T00:00:00+00:00",
        "distance":         0.1,
        "duration_seconds": duration_seconds,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_get_planning_context_with_results():
    fake_results = [
        _make_result("t1", "Add authentication middleware", True, duration_seconds=5.0),
        _make_result("t2", "Fix database pool", False, error="Timeout after 30s", duration_seconds=12.0),
        _make_result("t3", "Implement JWT refresh", True, duration_seconds=8.0),
    ]
    with patch("knowledge_planner.query_similar_tasks", return_value=fake_results):
        ctx = kp.get_planning_context("add auth to the API")

    assert "PAST TASK CONTEXT" in ctx
    assert "Add authentication middleware" in ctx
    assert "Fix database pool" in ctx
    assert "Implement JWT refresh" in ctx
    assert "Timeout after 30s" in ctx
    assert "USE THIS CONTEXT" in ctx
    # Should have 3 "---" separators (one before each entry + one after last entry)
    assert ctx.count("---") == 4  # 3 before entries + 1 after last


def test_get_planning_context_empty():
    with patch("knowledge_planner.query_similar_tasks", return_value=[]):
        ctx = kp.get_planning_context("some task description")
    assert ctx == ""


def test_get_failure_warnings_with_failures():
    fake_results = [
        _make_result("t1", "Deploy contract to chain", True),
        _make_result("t2", "Deploy contract to testnet", False, error="Gas limit exceeded"),
        _make_result("t3", "Update contract ABI", False, error="ABI mismatch on line 7"),
    ]
    with patch("knowledge_planner.query_similar_tasks", return_value=fake_results):
        warn = kp.get_failure_warnings("deploy smart contract")

    assert "⚠️ WARNING" in warn
    assert "Gas limit exceeded" in warn
    assert "ABI mismatch on line 7" in warn
    # Successful task should NOT appear
    assert "Deploy contract to chain" not in warn or "failed" not in warn.split("Deploy contract to chain")[1][:10]
    assert "Address these failure modes" in warn


def test_get_failure_warnings_no_failures():
    fake_results = [
        _make_result("t1", "Write unit tests", True),
        _make_result("t2", "Add logging", True),
    ]
    with patch("knowledge_planner.query_similar_tasks", return_value=fake_results):
        warn = kp.get_failure_warnings("add tests to module")
    assert warn == ""


def test_truncation():
    long_desc  = "A" * 500
    long_error = "E" * 500
    fake_results = [
        _make_result("t1", long_desc, False, error=long_error, duration_seconds=3.0),
    ]
    with patch("knowledge_planner.query_similar_tasks", return_value=fake_results):
        ctx = kp.get_planning_context("something")

    # Description must be capped at 120 chars
    assert "A" * 121 not in ctx
    assert "A" * 120 in ctx

    # Error must be capped at 200 chars
    assert "E" * 201 not in ctx
    assert "E" * 200 in ctx
