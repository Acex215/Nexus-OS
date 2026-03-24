"""Tests for self_improver.py — Phase 5 Self-Improvement Proposer."""

from unittest.mock import patch

import self_improver as si


def _summary(success_rate=90.0, categories=None, trend="stable"):
    return {
        "window_hours": 24,
        "total_tasks": 20,
        "success_rate": success_rate,
        "avg_duration_seconds": 3.0,
        "rollback_count": 2,
        "tasks_per_hour": 1.0,
        "failure_categories": categories or {},
        "top_errors": [],
        "trend": trend,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_no_proposals_when_healthy():
    summary = _summary(success_rate=90.0, categories={"context_overflow": 0, "timeout": 0})
    proposals = si.generate_proposals(summary)
    assert proposals == []


def test_proposal_low_success_rate():
    summary = _summary(success_rate=40.0, categories={})
    proposals = si.generate_proposals(summary)

    assert len(proposals) >= 1
    priorities = [p["priority"] for p in proposals]
    assert "P1" in priorities
    # The general low-rate proposal should mention the rate
    descriptions = " ".join(p["description"] for p in proposals)
    assert "40.0%" in descriptions


def test_proposal_context_overflow():
    summary = _summary(success_rate=80.0, categories={"context_overflow": 3})
    proposals = si.generate_proposals(summary)

    assert len(proposals) >= 1
    categories = [p["category"] for p in proposals]
    assert "context_overflow" in categories
    descriptions = " ".join(p["description"] for p in proposals)
    assert "context" in descriptions.lower()
    assert "trim" in descriptions.lower()


def test_proposal_coder_partial():
    summary = _summary(success_rate=80.0, categories={"coder_partial": 2})
    proposals = si.generate_proposals(summary)

    assert len(proposals) >= 1
    categories = [p["category"] for p in proposals]
    assert "coder_partial" in categories
    descriptions = " ".join(p["description"] for p in proposals)
    assert "split" in descriptions.lower() or "sub-task" in descriptions.lower()


def test_max_three_proposals():
    # All six known failure categories have hits → should cap at 3
    summary = _summary(
        success_rate=30.0,
        categories={
            "context_overflow": 2,
            "scope_violation": 1,
            "missing_file": 1,
            "coder_partial": 1,
            "timeout": 1,
            "lm_unavailable": 1,
        },
    )
    proposals = si.generate_proposals(summary)

    assert len(proposals) <= 3


def test_format_proposals():
    proposals = [
        {
            "description": "Add context size monitoring",
            "priority": "P1",
            "risk": "medium",
            "rationale": "Context overflows are causing repeated failures",
            "category": "context_overflow",
        },
        {
            "description": "Split multi-file changes into sub-tasks",
            "priority": "P2",
            "risk": "low",
            "rationale": "Partial patches indicate tasks are too broad",
            "category": "coder_partial",
        },
    ]
    report = si.format_proposals(proposals)

    assert "Self-Improvement Proposals" in report
    assert "1." in report
    assert "2." in report
    assert "[P1]" in report
    assert "[P2]" in report
    assert "Rationale:" in report
    assert "Context overflows are causing repeated failures" in report
    assert "approve" in report
