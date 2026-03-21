import logging
from typing import Optional

logger = logging.getLogger("metrics")


def get_performance_summary(window_hours: int = 24) -> dict:
    """Compute performance metrics from the task log for the given time window."""
    try:
        from task_logger import read_recent_logs
    except ImportError:
        logger.warning("task_logger not available")
        return _empty_summary(window_hours)

    try:
        from failure_analyzer import analyze_failures
    except ImportError:
        logger.warning("failure_analyzer not available")
        analyze_failures = None

    try:
        logs = read_recent_logs(window_hours)
    except Exception as e:
        logger.error("Failed to read task logs: %s", e)
        logs = []

    if not logs:
        summary = _empty_summary(window_hours)
        if analyze_failures:
            try:
                fa = analyze_failures([])
                summary["failure_categories"] = fa.get("categories", {})
                summary["top_errors"] = fa.get("top_errors", [])
            except Exception as e:
                logger.error("failure_analyzer error: %s", e)
        return summary

    total = len(logs)
    successes = [t for t in logs if t.get("status") == "success"]
    failures = [t for t in logs if t.get("status") == "failed"]
    success_rate = (len(successes) / total * 100) if total else 0.0

    durations = [
        t.get("duration_seconds", 0)
        for t in logs
        if t.get("duration_seconds") is not None
    ]
    avg_duration = sum(durations) / len(durations) if durations else 0.0

    tasks_per_hour = total / window_hours if window_hours else 0.0

    # Trend: compare success rate of first half vs second half
    mid = total // 2
    trend = "stable"
    if total >= 4:
        first_half = logs[:mid]
        second_half = logs[mid:]
        first_sr = sum(1 for t in first_half if t.get("status") == "success") / len(first_half) * 100
        second_sr = sum(1 for t in second_half if t.get("status") == "success") / len(second_half) * 100
        diff = second_sr - first_sr
        if diff > 5:
            trend = "improving"
        elif diff < -5:
            trend = "degrading"

    failure_categories: dict = {}
    top_errors: list = []
    if analyze_failures:
        try:
            fa = analyze_failures(failures)
            failure_categories = fa.get("categories", {})
            top_errors = fa.get("top_errors", [])
        except Exception as e:
            logger.error("failure_analyzer error: %s", e)

    return {
        "window_hours": window_hours,
        "total_tasks": total,
        "success_rate": round(success_rate, 1),
        "avg_duration_seconds": round(avg_duration, 2),
        "rollback_count": len(failures),
        "tasks_per_hour": round(tasks_per_hour, 2),
        "failure_categories": failure_categories,
        "top_errors": top_errors,
        "trend": trend,
    }


def _empty_summary(window_hours: int) -> dict:
    return {
        "window_hours": window_hours,
        "total_tasks": 0,
        "success_rate": 0.0,
        "avg_duration_seconds": 0.0,
        "rollback_count": 0,
        "tasks_per_hour": 0.0,
        "failure_categories": {},
        "top_errors": [],
        "trend": "stable",
    }


def format_metrics_report(summary: Optional[dict] = None) -> str:
    """Return a Discord-formatted performance report string."""
    if summary is None:
        summary = get_performance_summary()

    trend = summary.get("trend", "stable")
    trend_emoji = {"improving": "📈", "stable": "➡️", "degrading": "📉"}.get(trend, "➡️")

    lines = [
        f"📈 **Performance Dashboard** (last {summary['window_hours']}h)",
        f"Tasks: {summary['total_tasks']} | Success: {summary['success_rate']}% | Avg: {summary['avg_duration_seconds']}s",
        f"Throughput: {summary['tasks_per_hour']}/hr | Rollbacks: {summary['rollback_count']}",
        f"Trend: {trend_emoji} {trend}",
    ]

    categories = summary.get("failure_categories", {})
    if categories:
        lines.append("")
        lines.append("**Failure Breakdown:**")
        for category, count in sorted(categories.items(), key=lambda x: -x[1]):
            lines.append(f"  • {category}: {count}")

    return "\n".join(lines)


def should_propose_improvement(summary: Optional[dict] = None) -> tuple:
    """Return (True, reason) if metrics suggest a self-improvement task should be created."""
    if summary is None:
        summary = get_performance_summary()

    success_rate = summary.get("success_rate", 0.0)
    if success_rate < 70:
        return (True, f"Low success rate ({success_rate}%)")

    categories = summary.get("failure_categories", {})
    total_failures = sum(categories.values()) if categories else 0
    if total_failures > 0:
        for category, count in categories.items():
            if count / total_failures > 0.30:
                return (True, f"High {category} failure rate")

    trend = summary.get("trend", "stable")
    if trend == "degrading":
        return (True, "Performance degrading")

    return (False, "")
