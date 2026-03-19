#!/usr/bin/env python3
"""NEXUS OS Dev Assistant — Autonomous Execution Loop (Phase 2)

Picks tasks from TaskQueue, executes them through the dev_assistant pipeline,
posts summary reports every N tasks, and handles sub-task decomposition.

This module is imported by dev_assistant.py and driven by its Discord bot event loop.
It does NOT run its own event loop or Discord connection.

Usage in dev_assistant.py:
    from autonomous_loop import AutonomousLoop
    loop = AutonomousLoop(bot, queue, channel)
    # In on_ready or a command:
    await loop.start()
    # To pause/resume:
    loop.pause()
    loop.resume()
"""

import asyncio
import logging
import time as _time
import traceback
from datetime import datetime, timezone
from typing import Optional, Callable, Awaitable

import discord

from knowledge_indexer import index_task as index_task_to_chroma
from safety_gates import SafetyGate, ScopeEnforcer, RetryPolicy
from task_logger import log_task, read_recent_logs
from test_validator import TestValidator

log = logging.getLogger("autonomous_loop")

# ── Configuration ─────────────────────────────────────────────────────────────

SUMMARY_INTERVAL = 5          # Post summary every N completed tasks
TASK_COOLDOWN_SECONDS = 5     # Pause between tasks
POLL_INTERVAL_SECONDS = 30    # How often to check queue when idle
MAX_CONSECUTIVE_FAILURES = 3  # Pause after this many failures in a row


class AutonomousLoop:
    """Autonomous task execution loop.

    Requires:
      - bot: the dev_assistant bot instance (has _analyze, _execute, _rollback, etc.)
      - queue: TaskQueue instance
      - channel: discord.TextChannel to post in
      - execute_fn: async callable(task_dict) -> dict with keys:
            success: bool, commit_hash: str|None, error: str|None,
            branch: str|None, diffs: list, lines_added: int,
            lines_removed: int, files_changed: int, blockchain_tx: str|None
    """

    def __init__(
        self,
        queue,  # TaskQueue
        channel: discord.TextChannel,
        execute_fn: Callable[[dict], Awaitable[dict]],
        decompose_fn: Optional[Callable[[dict], Awaitable[Optional[list[dict]]]]] = None,
        bot: Optional[discord.Client] = None,
        owner_id: int = 0,
    ):
        self.queue = queue
        self.channel = channel
        self.execute_fn = execute_fn
        self.decompose_fn = decompose_fn
        self.bot = bot
        self.owner_id = owner_id

        self.safety_gate = SafetyGate()
        self.scope_enforcer = ScopeEnforcer()
        self.retry_policy = RetryPolicy()
        self.test_validator = TestValidator()

        self._running = False
        self._paused = False
        self._gate_active = False
        self._task: Optional[asyncio.Task] = None
        self._current_task_id: Optional[str] = None
        self._completed_since_summary = 0
        self._consecutive_failures = 0
        self._focus_task_id: Optional[str] = None

    # ── Control ───────────────────────────────────────────────────────────────

    async def start(self):
        """Start the autonomous loop. Idempotent."""
        if self._running:
            return
        self._running = True
        self._paused = False
        self._task = asyncio.create_task(self._loop())
        log.info("Autonomous loop started")

    def pause(self):
        """Pause after current task completes."""
        self._paused = True
        log.info("Autonomous loop paused")

    def resume(self):
        """Resume the loop."""
        self._paused = False
        log.info("Autonomous loop resumed")

    async def stop(self):
        """Stop the loop entirely."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("Autonomous loop stopped")

    @property
    def is_running(self) -> bool:
        return self._running and not self._paused

    @property
    def current_task_id(self) -> Optional[str]:
        return self._current_task_id

    @property
    def gate_active(self) -> bool:
        return self._gate_active

    def focus(self, task_id: str) -> bool:
        """Set a specific task to be picked next."""
        result = self.queue.focus(task_id)
        if result:
            self._focus_task_id = task_id
        return result

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def _loop(self):
        """Core autonomous execution loop."""
        await self._post(
            "🤖 **Autonomous mode active.** "
            f"Polling every {POLL_INTERVAL_SECONDS}s. "
            f"Summaries every {SUMMARY_INTERVAL} tasks. "
            "Say `pause` to stop, `status` for current state."
        )

        while self._running:
            # Check pause
            if self._paused:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            # Check consecutive failure limit
            if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                await self._post(
                    f"⚠️ **Pausing autonomous execution** — "
                    f"{self._consecutive_failures} consecutive failures. "
                    "Review the queue and say `resume` when ready."
                )
                self._paused = True
                self._consecutive_failures = 0
                continue

            # Pop next task
            task = self.queue.pop_next()
            if task is None:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            # Execute
            task_id = task["id"]
            self._current_task_id = task_id
            desc_short = task["description"][:60]
            log.info("Starting task %s: %s", task_id, desc_short)

            try:
                # Phase: analyzing → check if decomposition needed
                if self.decompose_fn and task.get("risk", "low") != "low":
                    sub_tasks = await self.decompose_fn(task)
                    if sub_tasks and len(sub_tasks) > 1:
                        # Decompose: create sub-tasks, mark parent as done
                        self.queue.add_sub_tasks(task_id, sub_tasks)
                        self.queue.update_status(task_id, "done")
                        await self._post(
                            f"🔀 Decomposed `{task_id}` into {len(sub_tasks)} sub-tasks."
                        )
                        self._current_task_id = None
                        await asyncio.sleep(TASK_COOLDOWN_SECONDS)
                        continue

                # Phase 3: Risk-based approval gate
                task["risk"] = self.safety_gate.classify_risk(task)
                self._gate_active = True
                try:
                    approved, reason = await self.safety_gate.check(
                        task, self.channel, self.owner_id, self.bot
                    )
                finally:
                    self._gate_active = False

                if not approved:
                    log.info("Task %s rejected by safety gate: %s", task_id, reason)
                    self.queue.update_status(task_id, "blocked_human", error=reason)
                    await self.channel.send(f"🛑 `{task_id}` blocked: {reason}")
                    continue

                # Phase: executing
                self.queue.update_status(task_id, "executing", branch=f"task/{task_id}")

                _task_start = _time.monotonic()
                result = await self.retry_policy.execute_with_retry(self.execute_fn, task)

                success = result.get("success", False)

                if result["success"]:
                    modified_files = list(task.get("affected_files") or [])
                    if not modified_files and result.get("diffs"):
                        import re as _re
                        for diff in result["diffs"]:
                            m = _re.search(r"^--- a/(.+)$", diff, _re.MULTILINE)
                            if m:
                                modified_files.append("/opt/nexus/" + m.group(1))

                    test_result = await self.test_validator.validate(modified_files)
                    if not test_result["passed"]:
                        log.warning("Task %s passed execution but failed tests: %s",
                                    task_id, test_result["output"][:200])
                        await self.channel.send(
                            f"🔧 ⚠️ `{task_id}` tests failed:\n```\n{test_result['output'][:500]}\n```"
                        )
                        result["success"] = False
                        result["error"] = f"Tests failed: {test_result['output'][:200]}"

                success = result.get("success", False)

                if success:
                    self.queue.update_status(
                        task_id, "done",
                        commit_hash=result.get("commit_hash"),
                        blockchain_tx=result.get("blockchain_tx"),
                        branch=result.get("branch"),
                        diffs=result.get("diffs", []),
                        lines_added=result.get("lines_added", 0),
                        lines_removed=result.get("lines_removed", 0),
                        files_changed=result.get("files_changed", 0),
                    )
                    self._consecutive_failures = 0
                    log.info("Task %s completed successfully", task_id)
                    try:
                        _duration = _time.monotonic() - _task_start
                        await log_task(task, result, duration_seconds=_duration)
                    except Exception as _log_err:
                        log.warning("Task logging failed: %s", _log_err)
                    try:
                        recent = read_recent_logs(1)
                        if recent:
                            await index_task_to_chroma(recent[0])
                    except Exception as _idx_err:
                        log.warning("ChromaDB indexing failed: %s", _idx_err)
                else:
                    self.queue.update_status(
                        task_id, "failed",
                        error=result.get("error", "unknown error"),
                        branch=result.get("branch"),
                    )
                    self._consecutive_failures += 1
                    log.warning("Task %s failed: %s", task_id, result.get("error", "?"))
                    try:
                        _duration = _time.monotonic() - _task_start
                        await log_task(task, result, duration_seconds=_duration)
                    except Exception as _log_err:
                        log.warning("Task logging failed: %s", _log_err)
                    try:
                        recent = read_recent_logs(1)
                        if recent:
                            await index_task_to_chroma(recent[0])
                    except Exception as _idx_err:
                        log.warning("ChromaDB indexing failed: %s", _idx_err)

                self._completed_since_summary += 1

                # Post summary if threshold reached
                if self._completed_since_summary >= SUMMARY_INTERVAL:
                    await self._post_summary()
                    self._completed_since_summary = 0

            except Exception as e:
                log.error("Unhandled error executing %s: %s", task_id, traceback.format_exc())
                self.queue.update_status(task_id, "failed", error=str(e)[:500])
                self._consecutive_failures += 1
                self._completed_since_summary += 1

            finally:
                self._current_task_id = None
                await asyncio.sleep(TASK_COOLDOWN_SECONDS)

    # ── Summary report ────────────────────────────────────────────────────────

    async def _post_summary(self):
        """Post a development summary to the channel."""
        stats = self.queue.recent_stats(SUMMARY_INTERVAL)
        if stats["total"] == 0:
            return

        lines = [f"📊 **Development Summary** (last {stats['total']} tasks)\n"]

        for t in stats["tasks"]:
            tid = t["id"]
            desc = t["description"][:50]
            result = t.get("result", {})
            fc = result.get("files_changed", 0)
            la = result.get("lines_added", 0)
            lr = result.get("lines_removed", 0)

            if t["status"] == "done":
                lines.append(f"✅ `{tid}`: {desc} ({fc} files, +{la}/-{lr})")
            else:
                err = (result.get("error") or "unknown")[:40]
                lines.append(f"❌ `{tid}`: {desc} (FAILED: {err})")

        lines.append("")
        lines.append(
            f"**Success rate:** {stats['success']}/{stats['total']} "
            f"({stats['rate']:.0f}%)"
        )
        lines.append(
            f"**Total:** +{stats['lines_added']}/-{stats['lines_removed']} "
            f"across {stats['files_changed']} files"
        )

        # Show what's next
        pending = self.queue.list_pending()
        if pending:
            p_summary = ", ".join(
                f"{sum(1 for p in pending if p.get('priority') == prio)} {prio}"
                for prio in ["P0", "P1", "P2", "P3"]
                if any(p.get("priority") == prio for p in pending)
            )
            lines.append(f"**Next in queue:** {len(pending)} tasks ({p_summary})")
        else:
            lines.append("**Queue empty** — add more tasks!")

        await self._post("\n".join(lines))

    # ── Discord helpers ───────────────────────────────────────────────────────

    async def _post(self, message: str):
        """Post a message to the channel, truncating if needed."""
        if not self.channel:
            log.warning("No channel set, cannot post: %s", message[:100])
            return
        try:
            await self.channel.send(message[:1990])
        except discord.HTTPException as e:
            log.error("Failed to post to Discord: %s", e)

    # ── Status for Discord commands ───────────────────────────────────────────

    def status_text(self) -> str:
        """Generate a status string for the `status` command."""
        counts = self.queue.count_by_status()
        parts = []

        if self._paused:
            parts.append("⏸️ **Paused**")
        elif self._running:
            parts.append("▶️ **Running**")
        else:
            parts.append("⏹️ **Stopped**")

        if self._current_task_id:
            task = self.queue.get(self._current_task_id)
            if task:
                parts.append(f"⚙️ Working on: `{self._current_task_id}` — {task['description'][:50]}")

        depth = counts.get("pending", 0)
        done = counts.get("done", 0)
        failed = counts.get("failed", 0)
        parts.append(f"📋 Queue: {depth} pending, {done} done, {failed} failed")

        if done + failed > 0:
            rate = done / (done + failed) * 100
            parts.append(f"📈 Success rate: {rate:.0f}%")

        parts.append(f"📝 Tasks since last summary: {self._completed_since_summary}/{SUMMARY_INTERVAL}")

        return "\n".join(parts)
