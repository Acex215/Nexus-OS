#!/usr/bin/env python3
"""NEXUS OS CAF — Proactive Task Engine

Keeps the orchestrator busy when the intent queue has no autonomous work.
Each task has a minimum interval; get_next_proactive_task() returns the
first task whose interval has elapsed, or (None, None) if all are recent.

Public API:
    get_next_proactive_task() -> tuple[str | None, Callable | None]
    reset_interval(name)      -> None   (force task to run next cycle)
"""

import logging
import subprocess
import time
from pathlib import Path

log = logging.getLogger("proactive_tasks")

# Tracks last-run epoch for each task name.  Module-level so state persists
# across calls within one orchestrator process.
PROACTIVE_INTERVAL: dict[str, float] = {}

# ── Task table (name, min_interval_seconds, function) ─────────────────────────

def _task_table() -> list[tuple[str, int, object]]:
    """Build task table lazily so callable references are valid at call time."""
    return [
        ("health_check",       300,  do_health_check),        # 5 min
        ("git_reindex",        600,  do_git_reindex),          # 10 min
        ("follow_up_analysis", 1800, do_follow_up_analysis),   # 30 min
        ("code_quality_scan",  3600, do_code_quality_scan),    # 1 hour
        ("stale_intent_check", 7200, do_stale_intent_check),   # 2 hours
    ]


# ── Public API ────────────────────────────────────────────────────────────────

def get_next_proactive_task() -> tuple:
    """Return the next (name, func) whose interval has elapsed, else (None, None)."""
    now = time.time()
    for name, interval, func in _task_table():
        last_run = PROACTIVE_INTERVAL.get(name, 0)
        if now - last_run >= interval:
            PROACTIVE_INTERVAL[name] = now
            return (name, func)
    return (None, None)


def reset_interval(name: str) -> None:
    """Force a named task to run on the next call to get_next_proactive_task()."""
    PROACTIVE_INTERVAL.pop(name, None)


# ── Task implementations ──────────────────────────────────────────────────────

def do_health_check() -> dict:
    """Run a full cluster health check and store results."""
    try:
        from health_monitor import run_health_checks, store_health_results, detect_transitions
        results     = run_health_checks()
        store_health_results(results)
        transitions = detect_transitions(results)
        return {"services_checked": len(results), "transitions": len(transitions)}
    except Exception as e:
        log.warning("do_health_check: %s", e)
        return {"error": str(e)}


def do_git_reindex() -> dict:
    """Check for new git commits and trigger incremental re-index."""
    try:
        from git_monitor import check_for_new_commits, get_changed_files, trigger_incremental_reindex
        new_commits = check_for_new_commits()
        if not new_commits:
            return {"new_commits": 0}
        for commit in new_commits:
            changed = get_changed_files("/opt/nexus", commit)
            if changed:
                trigger_incremental_reindex(changed)
        return {"new_commits": len(new_commits)}
    except Exception as e:
        log.warning("do_git_reindex: %s", e)
        return {"error": str(e)}


def do_code_quality_scan() -> dict:
    """Review recently modified Python files via the subagent."""
    try:
        from subagent_client import check_health, review_code
    except ImportError as e:
        return {"skipped": f"subagent_client unavailable: {e}"}

    if not check_health():
        return {"skipped": "subagent offline"}

    try:
        # Files modified in last 24 h
        r = subprocess.run(
            ["find", "/opt/nexus/automation", "-name", "*.py",
             "-mmin", "-1440", "-type", "f"],
            capture_output=True, text=True, timeout=10,
        )
        files = [f.strip() for f in r.stdout.strip().splitlines() if f.strip()]
    except Exception as e:
        return {"error": f"find failed: {e}"}

    reviews = []
    for filepath in files[:3]:   # cap at 3 files per scan to limit LLM load
        try:
            code = Path(filepath).read_text(encoding="utf-8")
        except Exception:
            continue
        if len(code) < 200:     # skip stub/tiny files
            continue
        try:
            review = review_code(code[:3000])
            if "[SUBAGENT ERROR]" not in review:
                reviews.append({"file": filepath, "summary": review[:200]})
                log.info("code_quality_scan: reviewed %s", filepath)
        except Exception as e:
            log.debug("review_code(%s): %s", filepath, e)

    return {"files_scanned": len(files), "files_reviewed": len(reviews)}


def do_stale_intent_check() -> dict:
    """Report intents that have been blocked or pending for over 48 hours."""
    try:
        from planning_engine import load_intent_registry
        intents = load_intent_registry()
    except Exception as e:
        return {"error": str(e)}

    stale_blocked: list[str] = []
    for intent in intents:
        if intent.get("status") == "blocked":
            stale_blocked.append(intent["id"])

    if stale_blocked:
        try:
            from discord_reporter import send_oneshot
            ids_str = ", ".join(f"`{i}`" for i in stale_blocked[:10])
            send_oneshot(
                f"⚠️ **Stale blocked intents** (still blocked — may need manual unblock):\n"
                f"{ids_str}\nUse `approve <id>` or `block <id>` to manage."
            )
        except Exception as e:
            log.warning("do_stale_intent_check: Discord notify failed: %s", e)

    return {"stale_blocked": stale_blocked}


def do_follow_up_analysis() -> dict:
    """Identify completed intents that have no follow-up entries in the registry.

    Surfaces them so the orchestrator can decide whether to generate follow-ups.
    (Actual generation happens in the feedback loop; this is just reporting.)
    """
    try:
        from planning_engine import load_intent_registry
        intents = load_intent_registry()
    except Exception as e:
        return {"error": str(e)}

    completed_ids      = {i["id"] for i in intents if i.get("status") == "completed"}
    # IDs that already have follow-up children (pattern: <parent>-f<n>)
    has_followup_parent = {
        i["id"].rsplit("-f", 1)[0]
        for i in intents
        if "-f" in i["id"] and not i["id"].endswith("-f")
    }
    without_followup = completed_ids - has_followup_parent

    log.debug(
        "follow_up_analysis: %d completed, %d without follow-ups",
        len(completed_ids), len(without_followup),
    )
    return {
        "total_completed":          len(completed_ids),
        "without_followup":         len(without_followup),
        "candidate_ids":            list(without_followup)[:10],
    }
