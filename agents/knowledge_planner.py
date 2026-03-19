"""knowledge_planner.py — Formats past task outcomes as LLM planning context.

Queries ChromaDB via knowledge_indexer and produces ready-to-inject text blocks
for the coordinator LLM prompt (Phase 4).
"""

import logging

from knowledge_indexer import query_similar_tasks

log = logging.getLogger("knowledge_planner")

_MAX_DESC_LEN  = 120
_MAX_ERROR_LEN = 200
_MAX_ENTRIES   = 5


def get_planning_context(task_description: str, n: int = 5) -> str:
    """Return a formatted context block of similar past tasks, or '' if none."""
    n = min(n, _MAX_ENTRIES)
    try:
        results = query_similar_tasks(task_description, n=n)
    except Exception as exc:
        log.warning("knowledge_planner: query failed: %s", exc)
        return ""

    if not results:
        return ""

    lines = ["PAST TASK CONTEXT (most similar previous tasks):"]
    for entry in results:
        desc  = (entry.get("description") or "")[:_MAX_DESC_LEN]
        status = entry.get("status", "unknown")
        dur   = entry.get("duration_seconds", 0)
        error = (entry.get("error") or "none")[:_MAX_ERROR_LEN]
        lines.append("---")
        lines.append(f"Task: {desc} | Outcome: {status} | Duration: {dur}s")
        lines.append(f"Error: {error}")

    lines.append("---")
    lines.append(
        "USE THIS CONTEXT: Avoid approaches that failed before. "
        "Prefer approaches that succeeded.\n"
        "If a similar task failed due to a specific error, address that error "
        "proactively in your plan."
    )

    return "\n".join(lines)


def get_failure_warnings(task_description: str, n: int = 3) -> str:
    """Return a warning block listing similar tasks that previously failed, or ''."""
    try:
        results = query_similar_tasks(task_description, n=n, include_failures=True)
    except Exception as exc:
        log.warning("knowledge_planner: failure query failed: %s", exc)
        return ""

    failures = [r for r in results if not r.get("success", True)]
    if not failures:
        return ""

    lines = ["⚠️ WARNING — Similar tasks have failed before:"]
    for entry in failures:
        desc  = (entry.get("description") or "")[:_MAX_DESC_LEN]
        error = (entry.get("error") or "unknown")[:_MAX_ERROR_LEN]
        lines.append(f'- "{desc}" failed: {error}')
    lines.append("Address these failure modes in your plan.")

    return "\n".join(lines)
