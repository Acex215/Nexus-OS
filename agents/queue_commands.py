#!/usr/bin/env python3
"""NEXUS OS Dev Assistant — Discord Command Handler (Phase 2)

Parses queue management commands from Discord messages and routes them
to the TaskQueue and AutonomousLoop.

Designed to be called from dev_assistant.py's on_message handler.
Returns (handled: bool, response: str|None) — if handled is False,
fall through to the existing task analysis flow.

Usage in dev_assistant.py:
    from queue_commands import handle_queue_command
    handled, response = handle_queue_command(message.content, queue, auto_loop)
    if handled:
        await message.channel.send(response)
        return
"""

import logging
import re
from typing import Optional

log = logging.getLogger("queue_commands")


def handle_queue_command(
    text: str,
    queue,           # TaskQueue
    auto_loop=None,  # AutonomousLoop (may be None if not started)
) -> tuple[bool, Optional[str]]:
    """Parse and handle a queue management command.

    Returns (handled, response_text).
    handled=False means the message is not a queue command — pass it through.
    """
    stripped = text.strip()
    lower = stripped.lower()

    # ── show queue / queue ────────────────────────────────────────────────────
    if lower in ("show queue", "queue", "q", "show q", "list tasks", "tasks"):
        return True, _cmd_show_queue(queue)

    # ── status ────────────────────────────────────────────────────────────────
    if lower in ("status", "stat", "s"):
        return True, _cmd_status(queue, auto_loop)

    # ── show last N ───────────────────────────────────────────────────────────
    m = re.match(r"^show\s+last\s+(\d+)$", lower)
    if m:
        n = min(int(m.group(1)), 20)
        return True, _cmd_show_last(queue, n)

    # ── add task: <description> ───────────────────────────────────────────────
    m = re.match(r"^add\s+task:\s*(.+)$", stripped, re.IGNORECASE)
    if m:
        desc = m.group(1).strip()
        return True, _cmd_add_task(queue, desc)

    # ── add task with priority: add P1 task: <description> ────────────────────
    m = re.match(r"^add\s+(P[0-3])\s+task:\s*(.+)$", stripped, re.IGNORECASE)
    if m:
        priority = m.group(1).upper()
        desc = m.group(2).strip()
        return True, _cmd_add_task(queue, desc, priority=priority)

    # ── pause ─────────────────────────────────────────────────────────────────
    if lower in ("pause", "stop", "hold"):
        if auto_loop:
            auto_loop.pause()
            return True, "⏸️ Autonomous execution paused. Say `resume` to continue."
        return True, "⏸️ Autonomous loop not active."

    # ── resume ────────────────────────────────────────────────────────────────
    if lower in ("resume", "continue", "unpause"):
        if auto_loop:
            auto_loop.resume()
            return True, "▶️ Autonomous execution resumed."
        return True, "▶️ Autonomous loop not active."

    # ── focus on <task-id> ────────────────────────────────────────────────────
    m = re.match(r"^focus\s+(?:on\s+)?(\S+)$", lower)
    if m:
        task_id = m.group(1)
        return True, _cmd_focus(queue, auto_loop, task_id)

    # ── remove <task-id> ──────────────────────────────────────────────────────
    m = re.match(r"^(?:remove|delete|cancel)\s+(\S+)$", lower)
    if m:
        task_id = m.group(1)
        return True, _cmd_remove(queue, task_id)

    # ── summary ───────────────────────────────────────────────────────────────
    if lower in ("summary", "report", "recap"):
        return True, _cmd_summary(queue)

    # ── health ────────────────────────────────────────────────────────────────
    if lower in ("health", "health check", "healthcheck"):
        return True, "__HEALTH_CHECK__"

    # ── help ──────────────────────────────────────────────────────────────────
    if lower in ("help", "commands", "?"):
        return True, _cmd_help()

    # ── Not a queue command ───────────────────────────────────────────────────
    return False, None


# ── Command implementations ───────────────────────────────────────────────────

def _cmd_show_queue(queue) -> str:
    pending = queue.list_pending()
    if not pending:
        counts = queue.count_by_status()
        done = counts.get("done", 0)
        failed = counts.get("failed", 0)
        return f"📋 **Queue empty.** ({done} done, {failed} failed total)"

    lines = [f"📋 **Task Queue** ({len(pending)} pending)\n"]
    for i, t in enumerate(pending[:15], 1):
        tid = t["id"]
        pri = t.get("priority", "P2")
        risk = t.get("risk", "?")
        desc = t["description"][:55]
        deps = t.get("depends_on", [])
        dep_str = f" ⏳ blocked by {', '.join(deps)}" if deps else ""
        lines.append(f"{i}. [{pri}/{risk}] `{tid}` — {desc}{dep_str}")

    if len(pending) > 15:
        lines.append(f"\n_…and {len(pending) - 15} more_")

    return "\n".join(lines)


def _cmd_status(queue, auto_loop) -> str:
    if auto_loop:
        return auto_loop.status_text()

    # Fallback if no auto_loop
    counts = queue.count_by_status()
    parts = ["⏹️ **Autonomous loop not active**"]
    parts.append(
        f"📋 Queue: {counts.get('pending', 0)} pending, "
        f"{counts.get('done', 0)} done, {counts.get('failed', 0)} failed"
    )
    return "\n".join(parts)


def _cmd_show_last(queue, n: int) -> str:
    recent = queue.list_recent(n)
    if not recent:
        return "No completed or failed tasks yet."

    lines = [f"📜 **Last {len(recent)} tasks:**\n"]
    for t in recent:
        tid = t["id"]
        desc = t["description"][:45]
        result = t.get("result", {})
        fc = result.get("files_changed", 0)
        la = result.get("lines_added", 0)
        lr = result.get("lines_removed", 0)

        if t["status"] == "done":
            lines.append(f"✅ `{tid}`: {desc} ({fc} files, +{la}/-{lr})")
        else:
            err = (result.get("error") or "unknown")[:35]
            lines.append(f"❌ `{tid}`: {desc} (FAILED: {err})")

    return "\n".join(lines)


def _cmd_add_task(queue, description: str, priority: str = "P2") -> str:
    # Infer risk from description keywords
    risk = "low"
    lower_desc = description.lower()
    if any(w in lower_desc for w in ["deploy", "contract", "blockchain", "delete", "remove", "migration"]):
        risk = "high"
    elif any(w in lower_desc for w in ["refactor", "rewrite", "restructure", "security"]):
        risk = "medium"

    tid = queue.add(description, priority=priority, risk=risk)
    depth = queue.queue_depth()
    return (
        f"📝 Added `{tid}` [{priority}/{risk}]\n"
        f"_{description}_\n"
        f"Queue depth: {depth}"
    )


def _cmd_focus(queue, auto_loop, task_id: str) -> str:
    task = queue.get(task_id)
    if not task:
        return f"⚠️ Task `{task_id}` not found."
    if task["status"] != "pending":
        return f"⚠️ Task `{task_id}` is `{task['status']}`, not pending."

    if auto_loop:
        auto_loop.focus(task_id)
    else:
        queue.focus(task_id)

    return f"📌 Focused on `{task_id}` — it will be picked up next."


def _cmd_remove(queue, task_id: str) -> str:
    task = queue.get(task_id)
    if not task:
        return f"⚠️ Task `{task_id}` not found."

    if queue.remove(task_id):
        return f"🗑️ Removed `{task_id}`."
    else:
        return f"⚠️ Cannot remove `{task_id}` — status is `{task['status']}`."


def _cmd_summary(queue) -> str:
    stats = queue.recent_stats(10)
    if stats["total"] == 0:
        return "No completed tasks to summarize yet."

    lines = [f"📊 **Summary** (last {stats['total']} tasks)\n"]
    lines.append(
        f"Success rate: {stats['success']}/{stats['total']} ({stats['rate']:.0f}%)"
    )
    lines.append(
        f"Total changes: +{stats['lines_added']}/-{stats['lines_removed']} "
        f"across {stats['files_changed']} files"
    )

    pending_count = queue.queue_depth()
    lines.append(f"Queue depth: {pending_count} pending")

    return "\n".join(lines)


def _cmd_help() -> str:
    return (
        "**📖 Queue Commands:**\n"
        "`show queue` — list pending tasks\n"
        "`add task: <description>` — add a new task\n"
        "`add P1 task: <description>` — add with priority\n"
        "`status` — current state and stats\n"
        "`show last 5` — recent task results\n"
        "`summary` — performance summary\n"
        "`focus on <task-id>` — prioritize a task\n"
        "`remove <task-id>` — remove a pending task\n"
        "`pause` / `resume` — control autonomous execution\n"
        "`health` — check LLM endpoints, blockchain, disk space\n"
        "`help` — this message\n\n"
        "_Tasks are also analyzed as before if not a queue command._"
    )
