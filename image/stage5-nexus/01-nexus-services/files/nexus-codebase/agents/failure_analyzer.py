"""failure_analyzer.py — Analyzes task log JSONL for recurring failure patterns.

Produces actionable summaries and Discord-formatted reports (Phase 4).
"""

import logging
from collections import Counter

from task_logger import read_recent_logs

log = logging.getLogger("failure_analyzer")

# ── Category keyword maps ──────────────────────────────────────────────────────

_CATEGORIES = [
    ("context_overflow", ("context", "token", "exceeded")),
    ("scope_violation",  ("scope",)),
    ("missing_file",     ("not found", "no such file")),
    ("coder_partial",    ("partial", "only patched", "call site")),
    ("timeout",          ("timeout", "timed out")),
    ("lm_unavailable",   ("connection", "refused", "unreachable")),
]

_RECOMMENDATIONS = {
    "context_overflow": "Consider trimming the coordinator system prompt or splitting large tasks",
    "scope_violation":  "Ensure affected_files is set correctly on tasks before execution",
    "missing_file":     "Verify file paths in task descriptions match actual codebase layout",
    "coder_partial":    "Break multi-location changes into separate sub-tasks",
    "timeout":          "Check LLM endpoint health and consider reducing context size",
    "lm_unavailable":   "Verify ThinkStation/ThinkPad are awake and LM Studio is running",
}

_ZEROED = {
    "total_tasks": 0,
    "total_failures": 0,
    "success_rate": 0.0,
    "failure_categories": {
        "context_overflow": 0,
        "scope_violation": 0,
        "missing_file": 0,
        "coder_partial": 0,
        "timeout": 0,
        "lm_unavailable": 0,
        "other": 0,
    },
    "most_common_errors": [],
    "avg_duration_success": 0.0,
    "avg_duration_failure": 0.0,
    "recent_streak": "success x 0",
}


def _categorize_error(error_lower: str) -> str:
    for cat, keywords in _CATEGORIES:
        if any(kw in error_lower for kw in keywords):
            return cat
    return "other"


def analyze_failures(n: int = 50) -> dict:
    """Read the last *n* task log entries and compute failure statistics."""
    entries = read_recent_logs(n)
    if not entries:
        return dict(_ZEROED)

    total = len(entries)
    failures = [e for e in entries if not e.get("success", True)]
    total_failures = len(failures)
    success_rate = (total - total_failures) / total * 100.0

    # Failure categories
    cats = {cat: 0 for cat, _ in _CATEGORIES}
    cats["other"] = 0
    error_counter: Counter = Counter()

    for e in failures:
        err_raw = e.get("error") or ""
        err_lower = err_raw.lower()
        cat = _categorize_error(err_lower)
        cats[cat] += 1
        if err_raw:
            error_counter[err_raw[:150]] += 1

    most_common_errors = [
        {"error": err, "count": cnt}
        for err, cnt in error_counter.most_common(5)
    ]

    # Duration averages
    success_durations = [e.get("duration_seconds", 0) for e in entries if e.get("success")]
    failure_durations = [e.get("duration_seconds", 0) for e in failures]
    avg_success = sum(success_durations) / len(success_durations) if success_durations else 0.0
    avg_failure = sum(failure_durations) / len(failure_durations) if failure_durations else 0.0

    # Recent streak — entries are newest-first
    streak_state = "success" if entries[0].get("success", True) else "failure"
    streak_count = 0
    for e in entries:
        e_state = "success" if e.get("success", True) else "failure"
        if e_state == streak_state:
            streak_count += 1
        else:
            break
    recent_streak = f"{streak_state} x {streak_count}"

    return {
        "total_tasks":          total,
        "total_failures":       total_failures,
        "success_rate":         round(success_rate, 1),
        "failure_categories":   cats,
        "most_common_errors":   most_common_errors,
        "avg_duration_success": round(avg_success, 2),
        "avg_duration_failure": round(avg_failure, 2),
        "recent_streak":        recent_streak,
    }


def format_failure_report(analysis: dict = None) -> str:
    """Return a Discord-formatted failure analysis report."""
    if analysis is None:
        analysis = analyze_failures()

    total   = analysis["total_tasks"]
    failed  = analysis["total_failures"]
    success = total - failed
    rate    = analysis["success_rate"]
    avg_s   = analysis["avg_duration_success"]
    avg_f   = analysis["avg_duration_failure"]
    streak  = analysis["recent_streak"]
    cats    = analysis["failure_categories"]
    errors  = analysis["most_common_errors"]

    lines = [
        f"📊 **Failure Analysis** (last {total} tasks)\n",
        f"Success rate: {success}/{total} ({rate:.1f}%)",
        f"Avg duration: {avg_s:.1f}s (success) / {avg_f:.1f}s (failure)",
        f"Current streak: {streak}",
        "",
        "**Failure categories:**",
        f"- Context overflow: {cats['context_overflow']}",
        f"- Scope violation: {cats['scope_violation']}",
        f"- Missing file: {cats['missing_file']}",
        f"- Coder partial patch: {cats['coder_partial']}",
        f"- Timeout: {cats['timeout']}",
        f"- LM unavailable: {cats['lm_unavailable']}",
        f"- Other: {cats['other']}",
    ]

    if errors:
        lines.append("")
        lines.append("**Top errors:**")
        for i, item in enumerate(errors, 1):
            lines.append(f'{i}. ({item["count"]}x) "{item["error"]}"')

    # Recommendations for categories with hits
    recs = [
        _RECOMMENDATIONS[cat]
        for cat in _RECOMMENDATIONS
        if cats.get(cat, 0) > 0
    ]
    if recs:
        lines.append("")
        lines.append("**Recommendations:**")
        for rec in recs:
            lines.append(f"- {rec}")

    return "\n".join(lines)
