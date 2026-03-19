"""change_analyzer.py — "What changed" summaries from task log and git log.

Answerable via Discord command (Phase 4).
"""

import logging
import subprocess
from datetime import datetime, timedelta, timezone

from task_logger import read_recent_logs

log = logging.getLogger("change_analyzer")

_NEXUS_ROOT = "/opt/nexus"


def get_changes_since(hours: int = 24) -> dict:
    """Return a structured summary of task and git changes in the last *hours* hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    # ── Task log ──────────────────────────────────────────────────────────────
    all_entries = read_recent_logs(100)
    recent = []
    for e in all_entries:
        ts_raw = e.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_raw)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                recent.append(e)
        except (ValueError, TypeError):
            pass

    succeeded = sum(1 for e in recent if e.get("success"))
    failed    = len(recent) - succeeded

    tasks = []
    files_touched: set[str] = set()
    for e in recent:
        desc = (e.get("description") or "")[:80]
        tasks.append({
            "task_id":       e.get("task_id", ""),
            "description":   desc,
            "status":        e.get("status", ""),
            "files_changed": int(e.get("files_changed") or 0),
            "lines_added":   int(e.get("lines_added") or 0),
            "lines_removed": int(e.get("lines_removed") or 0),
        })
        for f in (e.get("affected_files") or []):
            if f:
                files_touched.add(f)

    # ── Git log ───────────────────────────────────────────────────────────────
    commits: list[str] = []
    try:
        proc = subprocess.run(
            ["git", "log", "--oneline", f"--since={hours} hours ago"],
            cwd=_NEXUS_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            commits = [line for line in proc.stdout.splitlines() if line.strip()]
    except Exception as exc:
        log.warning("change_analyzer: git log failed: %s", exc)

    return {
        "period_hours": hours,
        "task_summary": {
            "total":     len(recent),
            "succeeded": succeeded,
            "failed":    failed,
            "tasks":     tasks,
        },
        "git_summary": {
            "commit_count": len(commits),
            "commits":      commits,
        },
        "files_touched": sorted(files_touched),
    }


def format_changes_report(hours: int = 24) -> str:
    """Return a Discord-formatted changes report for the last *hours* hours."""
    data = get_changes_since(hours)
    ts   = data["task_summary"]
    gs   = data["git_summary"]

    if ts["total"] == 0 and gs["commit_count"] == 0:
        return f"No changes recorded in the last {hours}h."

    lines = [f"📋 **Changes in the last {hours}h**\n"]

    # Tasks
    lines.append(f"**Tasks:** {ts['succeeded']} completed, {ts['failed']} failed")
    display_tasks = ts["tasks"][:15]
    for t in display_tasks:
        tid  = t["task_id"]
        desc = t["description"]
        if t["status"] == "done":
            fc = t["files_changed"]
            la = t["lines_added"]
            lr = t["lines_removed"]
            lines.append(f"✅ `{tid}` — {desc} ({fc} files, +{la}/-{lr})")
        else:
            lines.append(f"❌ `{tid}` — {desc} (failed)")
    if len(ts["tasks"]) > 15:
        lines.append(f"_…and {len(ts['tasks']) - 15} more tasks_")

    # Git commits
    lines.append(f"\n**Git commits:** {gs['commit_count']}")
    display_commits = gs["commits"][:10]
    for c in display_commits:
        lines.append(f"- {c}")
    if len(gs["commits"]) > 10:
        lines.append(f"_…and {len(gs['commits']) - 10} more commits_")

    # Files touched
    ft = data["files_touched"]
    lines.append(f"\n**Files touched:** {len(ft)} unique files")

    return "\n".join(lines)
