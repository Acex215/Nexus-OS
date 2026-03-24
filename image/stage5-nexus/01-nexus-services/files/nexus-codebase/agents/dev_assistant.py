#!/usr/bin/env python3
"""
NEXUS OS Development Assistant Bot

Human-in-the-loop replacement for the autonomous nexus_agent_v2 pipeline.
Bridges Md (human) ↔ AI agent hierarchy for codebase development tasks.
Operates exclusively in #agent-chat.

Lessons learned from agent_v2 failures:
- Never apply changes autonomously — always require human ✅ approval
- Never write outside /opt/nexus/ or touch protected paths
- Keep each task small and auditable (MAX_STEPS_PER_TASK = 10)
- Generate complete file content (no patch-apply failures)
- Git branch per task with full rollback on any error
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import discord
from workspace_loader import WorkspaceLoader
from discord import RawReactionActionEvent

sys.path.insert(0, "/opt/nexus/agents")
from llm_router_v2 import LLMRouter
from blockchain_logger import get_blockchain_logger
from task_queue import TaskQueue
from queue_commands import handle_queue_command
from autonomous_loop import AutonomousLoop
from task_decomposer import decompose_task
from knowledge_planner import get_planning_context
from safety_gates import ScopeEnforcer

scope_enforcer = ScopeEnforcer()

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [dev-assistant] %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/opt/nexus/agents/logs/dev_assistant.log"),
    ],
)
log = logging.getLogger("dev_assistant")

# ─── Constants ────────────────────────────────────────────────────────────────

NEXUS_ROOT        = Path("/opt/nexus")
MAX_STEPS_PER_TASK       = 10
MAX_CLARIFICATION_ROUNDS = 2     # after this many rounds, force clear=True and proceed
MAX_FILE_SIZE            = 12000  # chars sent to LLM; longer files are truncated

PROTECTED_PATHS: List[str] = [
    ".env",
    "keystore",
    "password.txt",
    "deployed/",
    "swarm.key",
    ".git/",
    "masterseed",
    "clef.ipc",
    ".key",
    ".pem",
    "id_rsa",
    "id_ed25519",
    "dev_assistant.py",
]

_APPROVE_WORDS = {"approve", "yes", "go", "ok", "proceed", "lgtm", "ship it"}
_REJECT_WORDS  = {"reject", "no", "cancel", "abort", "stop", "discard", "nope"}


# ─── Task Context ─────────────────────────────────────────────────────────────

@dataclass
class TaskContext:
    task_id: str
    description: str
    status: str                          # analyzing / awaiting_clarification / planning / awaiting_approval / executing / done / failed
    analysis: Optional[dict]             = None
    plan: Optional[List[dict]]           = None
    branch_name: Optional[str]           = None
    patches: List[str]                   = field(default_factory=list)   # captured git diffs
    files_read: Dict[str, str]           = field(default_factory=dict)   # path → content cache
    plan_msg_id: Optional[int]           = None   # Discord message ID for ✅/❌ reactions
    stashed: bool                        = False
    clarification_rounds: int            = 0      # number of times we've asked for clarification


# Phase 2: Task queue and autonomous loop
task_queue = TaskQueue("/opt/nexus/agents/task_queue.yaml")
auto_loop = None  # Created when user says "go" / "start autonomous"

# ─── Bot ──────────────────────────────────────────────────────────────────────

class DevAssistant(discord.Client):
    """NEXUS OS development assistant — human-in-the-loop codebase dev bot."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.router      = LLMRouter()
        self.bc          = get_blockchain_logger()
        self.workspace   = WorkspaceLoader()
        self.guild_id         = int(os.getenv("GUILD_ID", "0"))
        self.channel_name     = "agent-chat"
        self.channel: Optional[discord.TextChannel] = None
        self.owner_id         = int(os.getenv("OWNER_DISCORD_ID", "0"))
        self.active_task: Optional[TaskContext] = None
        self.cancel_requested: bool = False   # set True mid-execution to request abort

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def on_ready(self) -> None:
        log.info("DevAssistant online as %s (guild_id=%d)", self.user, self.guild_id)

        guild = self.get_guild(self.guild_id)
        if guild is None and self.guilds:
            guild = self.guilds[0]
            log.warning("GUILD_ID not found; using first guild: %s (%d)", guild.name, guild.id)

        if guild:
            for ch in guild.text_channels:
                if ch.name == self.channel_name:
                    self.channel = ch
                    log.info("Bound to #%s (id=%d)", ch.name, ch.id)
                    break
            if self.channel is None:
                log.error("#%s not found in guild %s", self.channel_name, guild.name)

        # Startup embed
        if self.channel:
            embed = discord.Embed(
                title="🔧 Dev Assistant Online",
                description=(
                    "Ready to assist with NEXUS OS development.\n"
                    "4 LLM tiers available: Coordinator · Coder · Director · Worker\n\n"
                    "Send me a development task to get started."
                ),
                color=discord.Color.blue(),
            )
            embed.add_field(name="Coordinator", value="`qwen3.5-35b-a3b` @ ThinkStation:1234", inline=True)
            embed.add_field(name="Coder",       value="`qwen2.5-coder-14b` @ ThinkPad:1234",  inline=True)
            embed.add_field(name="Worker",      value="`llama3.2:1b` @ nexus-ai2:11434",        inline=True)
            await self.channel.send(embed=embed)

        # Blockchain: log startup
        try:
            startup_hash = hashlib.sha256(b"dev_assistant:online").hexdigest()
            await self.bc.log_decision("dev_assistant", "online", startup_hash, 0)
        except Exception as exc:
            log.warning("Startup blockchain log failed: %s", exc)

        # Phase 4B: warm up ChromaDB client to avoid first-call event loop block
        try:
            import asyncio
            from knowledge_indexer import _get_client
            await asyncio.to_thread(_get_client)
            log.info("ChromaDB client warmed up")
        except Exception as exc:
            log.warning("ChromaDB warm-up failed (non-fatal): %s", exc)

    # ── Message handler ───────────────────────────────────────────────────────

    async def on_message(self, message: discord.Message) -> None:
        global auto_loop
        if message.author == self.user or message.author.bot:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return
        if message.channel.name != self.channel_name:
            return
        if self.owner_id and message.author.id != self.owner_id:
            return

        # Phase 3: suppress normal routing while safety gate is listening
        if auto_loop and auto_loop.gate_active:
            lower_check = message.content.strip().lower()
            if lower_check in ("approve", "yes", "reject", "no", "cancel", "abort"):
                return

        # --- Phase 2: Queue commands ---
        handled, response = handle_queue_command(message.content, task_queue, auto_loop)
        if handled:
            if response == "__HEALTH_CHECK__":
                from health_monitor import HealthMonitor
                monitor = HealthMonitor(
                    llm_endpoints={
                        "coordinator": "http://10.0.30.3:1234/v1/models",
                        "coder": "http://10.0.30.2:1234/v1/models",
                    },
                )
                hresult = await monitor.check_all()
                response = monitor.format_report(hresult)
            if response:
                await message.channel.send(response)
            return

        # --- Phase 2: Start/stop autonomous mode ---
        _lower = message.content.strip().lower()
        if _lower in ("go", "start", "start autonomous", "autonomous"):
            channel = message.channel
            if auto_loop and auto_loop.is_running:
                await channel.send("Already running. Say `pause` to stop.")
            else:
                auto_loop = AutonomousLoop(
                    queue=task_queue,
                    channel=channel,
                    execute_fn=execute_task_from_queue,
                    decompose_fn=decompose_task_wrapper,
                    bot=bot,
                    owner_id=bot.owner_id,
                )
                await auto_loop.start()
                await channel.send("🤖 Autonomous mode started.")
            return

        content_lower = message.content.strip().lower()
        task = self.active_task

        # ── 1. Executing: bot is applying patches ─────────────────────────────
        if task and task.status == "executing":
            words = set(re.split(r"[\s,!.]+", content_lower)) - {""}
            if words & _REJECT_WORDS:
                self.cancel_requested = True
                await self.channel.send(
                    "🔧 ⚠️ Cancellation requested — will stop after the current step "
                    "and roll back all changes."
                )
            else:
                await self.channel.send(
                    f"🔧 Executing ({len(task.patches)}/{len(task.plan or [])} steps done). "
                    "Type **cancel** to abort and roll back."
                )
            return

        # ── 2. Awaiting clarification: user answering the bot's questions ─────
        if task and task.status == "awaiting_clarification":
            task.description += f"\n\nClarification: {message.content}"
            task.status = "analyzing"
            await self.channel.send("🔧 Got it — re-analyzing with your answers…")
            asyncio.create_task(self._continue_after_clarification())
            return

        # ── 3. Awaiting approval: approve / reject / revise ───────────────────
        if task and task.status == "awaiting_approval":
            words = set(re.split(r"[\s,!.]+", content_lower)) - {""}

            if words & _APPROVE_WORDS:
                asyncio.create_task(self._execute())
                return

            if words & _REJECT_WORDS:
                await self.channel.send("🔧 ❌ Task rejected. No files were modified.")
                task.status = "failed"
                self.active_task = None
                return

            # Treat as a modification request — append revision and re-plan
            task.description += f"\n\nRevision: {message.content}"
            await self.channel.send("🔧 Got it — updating plan…")
            asyncio.create_task(self._plan())
            return

        # ── 4. Still busy (analyzing / planning) ─────────────────────────────
        if task and task.status not in ("done", "failed"):
            await self.channel.send(
                f"🔧 Still working (status: `{task.status}`). Please wait."
            )
            return

        # ── 5. No live task (or previous done/failed): start fresh ────────────
        if not message.content.strip():
            return

        asyncio.create_task(self._start_task(message.content.strip()))

    # ── Reaction handler (✅/❌ on plan embed) ────────────────────────────────

    async def on_raw_reaction_add(self, payload: RawReactionActionEvent) -> None:
        if payload.user_id == self.user.id:
            return
        if self.owner_id and payload.user_id != self.owner_id:
            return
        if not self.active_task:
            return
        if self.active_task.status != "awaiting_approval":
            return
        if payload.message_id != self.active_task.plan_msg_id:
            return

        emoji = str(payload.emoji)
        if emoji == "✅":
            asyncio.create_task(self._execute())
        elif emoji == "❌":
            await self.channel.send("🔧 ❌ Plan rejected via reaction. No files were modified.")
            self.active_task.status = "failed"
            self.active_task = None

    # ── Task Flow ─────────────────────────────────────────────────────────────

    async def _start_task(self, description: str) -> None:
        self.cancel_requested = False
        task_id = str(int(time.time()))
        self.active_task = TaskContext(
            task_id=task_id,
            description=description,
            status="analyzing",
        )
        await self._post_embed(
            "🔧 Analyzing task…",
            f"> {description[:300]}",
            discord.Color.greyple(),
        )

        await self._analyze(description)

        if self.active_task and self.active_task.status == "analyzing":
            # _analyze completed without needing clarification — move to planning
            await self._plan()

    async def _continue_after_clarification(self) -> None:
        """Re-run analysis on the updated description, then plan if clear."""
        task = self.active_task
        if task is None:
            return
        await self._analyze(task.description)
        if self.active_task and self.active_task.status == "analyzing":
            await self._plan()

    async def _analyze(self, description: str) -> None:
        """Ask Coordinator to assess clarity, files, and risk. Reads files into cache."""
        task = self.active_task
        if task is None:
            return

        # Pre-read any files mentioned in the description (heuristic: /opt/nexus/ paths)
        mentioned = re.findall(r"/opt/nexus/[^\s\"'`,]+", description)
        for path in mentioned:
            content = self._read_file(path)
            if content:
                task.files_read[path] = content

        file_context = self._format_file_context(task.files_read)

        # Load workspace context for analysis
        workspace_ctx = self.workspace.build_system_prompt(description)
        system = (
            f"{workspace_ctx}\n\n"
            "Given the above context, analyze this development task. Identify "
            "which files need to change and the risk level. "
            "Default to clear=true unless the task is genuinely ambiguous about WHAT to do. "
            "Questions about code quality, edge cases, or implementation details should NOT "
            "block progress — those are handled during planning. "
            "Respond with ONLY JSON (no explanation):\n"
            '{"clear": bool, "files": ["path"], "risk": "low|medium|high", '
            '"questions": ["..."], "summary": "..."}'
        )
        user = f"Task: {description}"
        if file_context:
            user += f"\n\nCurrent files:\n{file_context}"
        planning_ctx = get_planning_context(description)
        if planning_ctx:
            user += f"\n\n{planning_ctx}"

        async with self.channel.typing():
            result = await self.router.generate(
                "ceo",
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                task_type="planning",
                max_tokens=1024,
                temperature=0.3,
            )

        if result.get("error") or not result.get("content"):
            await self._post_embed("🔧 Error", f"Coordinator error: {result.get('error')}", discord.Color.red())
            task.status = "failed"
            self.active_task = None
            return

        analysis = self._parse_json(result["content"])
        if not analysis:
            await self._post_embed("🔧 Error", "Coordinator returned invalid JSON.", discord.Color.red())
            task.status = "failed"
            self.active_task = None
            return

        task.analysis = analysis

        # Read any additional files the coordinator identified
        for fpath in analysis.get("files", []):
            if fpath not in task.files_read:
                content = self._read_file(fpath)
                if content:
                    task.files_read[fpath] = content

        task.clarification_rounds += 1

        if not analysis.get("clear", True):
            if task.clarification_rounds <= MAX_CLARIFICATION_ROUNDS:
                questions = analysis.get("questions", [])
                q_text = "\n".join(f"• {q}" for q in questions) or "(needs more detail)"
                await self._post_embed(
                    "🔧 Needs Clarification",
                    f"{q_text}\n\nPlease reply with answers — I'll re-analyze.",
                    discord.Color.orange(),
                )
                # Keep task alive so on_message can append the answer and re-analyze
                task.status = "awaiting_clarification"
                return
            else:
                # Forced past max clarification rounds — proceed with what we have
                log.info(
                    "Forcing clear=True after %d clarification rounds for task %s",
                    task.clarification_rounds, task.task_id,
                )
                analysis["clear"] = True
                analysis.setdefault("summary", task.description[:120])
                await self.channel.send(
                    "🔧 ℹ️ Proceeding after max clarification rounds. "
                    "Plan will be based on context gathered so far."
                )

    async def _plan(self) -> None:
        """Ask Coordinator to produce a step-by-step plan given analysis + file contents."""
        task = self.active_task
        if task is None:
            return

        task.status = "planning"
        file_context = self._format_file_context(task.files_read)

        workspace_ctx = self.workspace.get_core_context()
        system = (
            f"{workspace_ctx}\n\n"
            "You are planning code changes. For each change, specify the "
            "file, action (create/modify), and what changes are needed. Keep changes "
            "minimal — do NOT add features not requested. "
            "Respond with ONLY JSON (no explanation):\n"
            '{"steps": [{"file": "path", "action": "modify|create", '
            '"description": "what to change"}]}'
        )
        user = (
            f"Task: {task.description}\n"
            f"Analysis: {json.dumps(task.analysis)}\n\n"
            f"Files:\n{file_context}"
        )

        async with self.channel.typing():
            result = await self.router.generate(
                "ceo",
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                task_type="planning",
                max_tokens=2048,
                temperature=0.3,
            )

        if result.get("error") or not result.get("content"):
            await self._post_embed("🔧 Error", f"Planner error: {result.get('error')}", discord.Color.red())
            task.status = "failed"
            self.active_task = None
            return

        data = self._parse_json(result["content"])
        if not data or "steps" not in data:
            await self._post_embed("🔧 Error", "Planner returned invalid JSON (no 'steps').", discord.Color.red())
            task.status = "failed"
            self.active_task = None
            return

        steps = [s for s in data["steps"] if s.get("file") and s.get("description")]

        if len(steps) > MAX_STEPS_PER_TASK:
            await self.channel.send(
                f"🔧 ⚠️ Plan has **{len(steps)} steps**, exceeding the limit of "
                f"{MAX_STEPS_PER_TASK}. Please break the task into smaller pieces."
            )
            task.status = "failed"
            self.active_task = None
            return

        task.plan = steps
        plan_msg = await self._post_plan_embed(task)
        task.plan_msg_id = plan_msg.id
        task.status = "awaiting_approval"

    async def _execute(self) -> None:
        """Apply all plan steps: write complete file content, show git diffs, commit."""
        task = self.active_task
        if task is None:
            return

        task.status = "executing"
        await self.channel.send("🔧 ✅ Plan approved — executing…")

        # Git: stash dirty work, create task branch
        rc, status_out, _ = await self._run_git("status", "--porcelain")
        if status_out.strip():
            await self._run_git("stash")
            task.stashed = True
            log.info("Stashed uncommitted changes")

        slug = re.sub(r"[^a-z0-9]+", "-", task.description.lower())[:30].strip("-") or "task"
        task.branch_name = f"dev-assistant/{task.task_id}-{slug}"
        # Always delete stale branch first (idempotent — ignores error if branch doesn't exist)
        await self._run_git("branch", "-D", task.branch_name)
        rc, _, stderr = await self._run_git("checkout", "-b", task.branch_name)
        if rc != 0:
            await self.channel.send(f"🔧 ⚠️ Could not create branch: {stderr}")
            await self._rollback()
            return

        for i, step in enumerate(task.plan):
            # Honour a cancellation requested via chat during execution
            if self.cancel_requested:
                await self.channel.send("🔧 ⚠️ Cancellation confirmed — rolling back.")
                self.cancel_requested = False
                await self._rollback()
                return

            fpath     = step["file"]
            action    = step.get("action", "modify").lower()
            step_desc = step["description"]

            await self.channel.send(
                f"🔧 **Step {i + 1}/{len(task.plan)}** — "
                f"`{action.upper()}` `{fpath}`\n> {step_desc}"
            )

            # Read full file content — used for both section extraction and patch application
            current_full = self._read_file_full(fpath) or ""

            # Resolve + protect path early (before coder call)
            abs_path = self._resolve_path(fpath)
            if abs_path is None:
                await self.channel.send(f"🔧 ⚠️ Path `{fpath}` is outside /opt/nexus/ or protected. Aborting.")
                await self._rollback()
                return

            # Phase 3: Scope enforcement
            if hasattr(bot, '_current_queue_task') and bot._current_queue_task:
                in_scope, scope_reason = scope_enforcer.check_scope(bot._current_queue_task, fpath)
                if not in_scope:
                    await self.channel.send(f"🔧 ⚠️ Scope violation: {scope_reason}. Skipping step.")
                    continue

            # Extract a focused section (~50 lines) to keep coder context small
            # Search the full file so functions past the 12K truncation point are found
            section = self._extract_section(current_full, step_desc)

            system = (
                "You are a code editor. Given a file section and a change description,\n"
                "output ONLY a SEARCH/REPLACE block:\n\n"
                "<<<SEARCH\n"
                "exact lines to find\n"
                ">>>\n"
                "<<<REPLACE\n"
                "replacement lines\n"
                ">>>\n\n"
                "The SEARCH block must match the file EXACTLY (whitespace-sensitive).\n"
                "Keep replacement minimal. Output NOTHING else."
            )
            user = (
                f"File: {fpath}\n"
                f"Change: {step_desc}\n\n"
                f"Relevant section:\n{section}"
            )

            async with self.channel.typing():
                try:
                    result = await asyncio.wait_for(
                        self.router.generate(
                            "ceo",
                            [{"role": "system", "content": system}, {"role": "user", "content": user}],
                            task_type="code_gen",
                            max_tokens=2048,
                            temperature=0.1,
                        ),
                        timeout=180,
                    )
                except asyncio.TimeoutError:
                    await self.channel.send(f"🔧 ⚠️ Coder timed out on step {i + 1}. Rolling back.")
                    await self._rollback()
                    return

            if result.get("error") or not result.get("content"):
                await self.channel.send(f"🔧 ⚠️ Coder failed for step {i + 1}: {result.get('error')}. Rolling back.")
                await self._rollback()
                return

            # Parse SEARCH/REPLACE block
            patch = self._parse_search_replace(result["content"])
            if patch is None:
                await self.channel.send(
                    f"🔧 ⚠️ Coder returned invalid SEARCH/REPLACE for step {i + 1}. Rolling back."
                )
                await self._rollback()
                return

            search_str, replace_str = patch

            if search_str not in current_full:
                await self.channel.send(
                    f"🔧 ⚠️ SEARCH string not found in `{fpath}` for step {i + 1}. Rolling back."
                )
                log.warning("SEARCH block not found:\n%.200s", search_str)
                await self._rollback()
                return

            if current_full.count(search_str) > 1:
                await self.channel.send(
                    f"🔧 ⚠️ SEARCH string not unique in `{fpath}` for step {i + 1}. Rolling back."
                )
                await self._rollback()
                return

            # Guard: reject patches that delete too many lines
            search_lines = search_str.count("\n")
            replace_lines = replace_str.count("\n")
            net_deleted = search_lines - replace_lines
            from safety_config import MAX_NET_DELETIONS, MAX_SHRINKAGE_PERCENT
            if net_deleted > MAX_NET_DELETIONS:
                await self.channel.send(
                    f"🔧 ⚠️ Patch rejected: would delete {net_deleted} net lines (max {MAX_NET_DELETIONS}). Rolling back."
                )
                log.warning("Destructive patch rejected: %d net lines deleted", net_deleted)
                await self._rollback()
                return
            new_content = current_full.replace(search_str, replace_str, 1)

            # Guard: reject if file shrinks by more than configured threshold
            if len(new_content) < len(current_full) * (1 - MAX_SHRINKAGE_PERCENT):
                shrink_pct = round((1 - len(new_content) / len(current_full)) * 100)
                await self.channel.send(
                    f"🔧 ⚠️ Patch rejected: file would shrink by {shrink_pct}% — likely truncation. Rolling back."
                )
                log.warning("File shrinkage rejected: %d%% for %s", shrink_pct, fpath)
                await self._rollback()
                return
            try:
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                abs_path.write_text(new_content)
            except OSError as exc:
                await self.channel.send(f"🔧 ⚠️ Could not write `{fpath}`: {exc}. Rolling back.")
                await self._rollback()
                return

            # Capture and show the diff
            _, diff_out, _ = await self._run_git("diff", str(abs_path.relative_to(NEXUS_ROOT)))
            if diff_out:
                task.patches.append(diff_out)
                await self._post_code(diff_out, language="diff")
            else:
                await self.channel.send(f"🔧 *(no diff — file may be new or unchanged)*")

            # Stage the file
            await self._run_git("add", str(abs_path.relative_to(NEXUS_ROOT)))

            # Update cache
            task.files_read[fpath] = new_content

        # Commit
        summary = task.description[:60]
        commit_msg = (
            f"dev-assistant: {summary}\n\n"
            f"Task: {task.task_id}\n"
            f"Steps: {len(task.plan)}\n\n"
            "Co-Authored-By: DevAssistant <noreply@nexus>"
        )
        rc, commit_out, commit_err = await self._run_git("commit", "-m", commit_msg)
        if rc != 0:
            await self.channel.send(f"🔧 ⚠️ git commit failed: {commit_err}. Rolling back.")
            await self._rollback()
            return

        m = re.search(r"\b([0-9a-f]{7,40})\b", commit_out)
        commit_hash = m.group(1) if m else "unknown"

        # Blockchain log
        reasoning_str = json.dumps({
            "description": task.description,
            "analysis": task.analysis,
            "plan": task.plan,
        }, sort_keys=True)
        reasoning_hash = hashlib.sha256(reasoning_str.encode()).hexdigest()

        tx_hash: Optional[str] = None
        try:
            tx_hash = await self.bc.log_decision(
                agent_id="dev_assistant",
                task=summary,
                reasoning_hash=reasoning_hash,
                ect_cost=len(task.plan) * 5,
            )
        except Exception as exc:
            log.warning("Blockchain log failed (non-fatal): %s", exc)

        # Summary embed
        embed = discord.Embed(
            title="🔧 Task Complete",
            description=summary[:1024],
            color=discord.Color.green(),
        )
        embed.add_field(name="Branch",  value=f"`{task.branch_name}`", inline=True)
        embed.add_field(name="Steps",   value=str(len(task.plan)),      inline=True)
        embed.add_field(
            name="Commit",
            value=f"`{commit_hash[:12]}…`" if len(commit_hash) >= 12 else f"`{commit_hash}`",
            inline=True,
        )
        if tx_hash:
            embed.add_field(name="Blockchain TX", value=f"`{tx_hash[:32]}…`", inline=False)
        embed.set_footer(text=f"Reasoning hash: {reasoning_hash[:16]}…")
        await self.channel.send(embed=embed)

        log.info(
            "Task done: branch=%s steps=%d commit=%s tx=%s",
            task.branch_name, len(task.plan), commit_hash, (tx_hash or "none")[:16],
        )
        task.status = "done"
        self.active_task = None

    async def _rollback(self) -> None:
        """Undo all file writes and restore main branch."""
        task = self.active_task
        if task is None:
            return
        await self._run_git("checkout", "--", ".")
        await self._run_git("checkout", "main")
        if task.stashed:
            await self._run_git("stash", "pop")
        task.status = "failed"
        self.active_task = None
        self.cancel_requested = False
        await self.channel.send(
            f"🔧 ❌ Rolled back. Branch `{task.branch_name or '(none)'}` abandoned. "
            "Working tree restored to `main`."
        )

    # ── Discord Helpers ───────────────────────────────────────────────────────

    async def _post_plan_embed(self, task: TaskContext) -> discord.Message:
        risk  = (task.analysis or {}).get("risk", "medium")
        color = {"low": discord.Color.green(), "high": discord.Color.red()}.get(
            risk, discord.Color.orange()
        )
        embed = discord.Embed(
            title="🔧 Development Plan — Awaiting Approval",
            description=(task.analysis or {}).get("summary", task.description)[:2048],
            color=color,
        )
        embed.add_field(name="Risk",  value=f"`{risk}`",           inline=True)
        embed.add_field(name="Steps", value=str(len(task.plan)),   inline=True)
        embed.add_field(name="Files", value=str(len({s["file"] for s in task.plan})), inline=True)

        steps_text = "\n".join(
            f"{i + 1}. `{s.get('action','modify').upper()}` `{s['file']}`\n   {s['description']}"
            for i, s in enumerate(task.plan)
        )[:1024]
        embed.add_field(name="Steps Detail", value=steps_text or "—", inline=False)
        embed.set_footer(
            text="React ✅ to approve or ❌ to reject — or type: approve / reject / cancel"
        )

        return await self.channel.send(embed=embed)

    async def _post_embed(
        self,
        title: str,
        description: str,
        color: discord.Color,
        fields: Optional[List[Tuple[str, str, bool]]] = None,
    ) -> discord.Message:
        embed = discord.Embed(title=title, description=description[:2048], color=color)
        for name, value, inline in (fields or []):
            embed.add_field(name=name, value=value[:1024], inline=inline)
        return await self.channel.send(embed=embed)

    async def _post_code(self, content: str, language: str = "diff") -> None:
        """Send content as a fenced code block, splitting if > 1900 chars."""
        chunk_size = 1900
        chunks = [content[i:i + chunk_size] for i in range(0, max(len(content), 1), chunk_size)]
        for idx, chunk in enumerate(chunks):
            suffix = f"\n*(part {idx + 1}/{len(chunks)})*" if len(chunks) > 1 else ""
            await self.channel.send(f"```{language}\n{chunk}\n```{suffix}")

    # ── Git Helper ────────────────────────────────────────────────────────────

    async def _run_git(self, *args: str) -> Tuple[int, str, str]:
        """Run a git command in NEXUS_ROOT. Returns (returncode, stdout, stderr)."""
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=str(NEXUS_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout.decode().strip(), stderr.decode().strip()

    # ── File Helpers ──────────────────────────────────────────────────────────

    def _read_file(self, path_str: str) -> Optional[str]:
        """
        Read a file under /opt/nexus/. Returns None on any error or policy violation.
        Truncates at MAX_FILE_SIZE chars.
        """
        path = self._resolve_path(path_str)
        if path is None:
            return None
        if not path.is_file():
            return None
        try:
            content = path.read_text(errors="replace")
        except OSError as exc:
            log.warning("Cannot read %s: %s", path, exc)
            return None
        if len(content) > MAX_FILE_SIZE:
            content = content[:MAX_FILE_SIZE] + "\n[TRUNCATED]"
        return content

    def _read_file_full(self, path_str: str) -> Optional[str]:
        """Read complete file content without truncation. For patch application only."""
        path = self._resolve_path(path_str)
        if path is None:
            return None
        if not path.is_file():
            return None
        try:
            return path.read_text(errors="replace")
        except OSError as exc:
            log.warning("Cannot read %s: %s", path, exc)
            return None

    def _resolve_path(self, path_str: str) -> Optional[Path]:
        """
        Resolve path to an absolute Path under NEXUS_ROOT.
        Returns None if the path is outside NEXUS_ROOT or matches a protected pattern.
        """
        try:
            path = Path(path_str).expanduser().resolve()
        except Exception:
            return None

        try:
            path.relative_to(NEXUS_ROOT)
        except ValueError:
            log.warning("Path outside NEXUS_ROOT denied: %s", path_str)
            return None

        path_lower = str(path).lower()
        name_lower = path.name.lower()
        for protected in PROTECTED_PATHS:
            if protected in path_lower or protected in name_lower:
                log.warning("Protected path denied (%r): %s", protected, path_str)
                return None

        return path

    def _format_file_context(self, files_read: Dict[str, str]) -> str:
        """Format cached file contents for LLM context."""
        if not files_read:
            return "(no files read yet)"
        blocks = [f"=== {path} ===\n{content}" for path, content in files_read.items()]
        return "\n\n".join(blocks)

    def _parse_json(self, text: str) -> Optional[dict]:
        """Extract the first JSON object from an LLM response."""
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        m = re.search(r"```(?:json)?\s*\n(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        return None

    @staticmethod
    def _extract_section(content: str, description: str, context_lines: int = 50) -> str:
        """Extract the most relevant section of a file for the coder.

        Strategy:
        1. If file is short enough, return it all.
        2. If description mentions 'top', 'beginning', 'header', 'import' → first N lines.
        3. If description mentions 'bottom', 'end', 'append' → last N lines.
        4. If description mentions a function/class name, find it and return ± context.
        5. Fallback: keyword-match scoring (original behavior).
        """
        lines = content.split("\n")
        if len(lines) <= context_lines * 2:
            return content

        desc_lower = description.lower()

        # Heuristic 1: top of file
        top_keywords = {"top", "beginning", "header", "import", "first line", "start of file", "add a comment at the top"}
        if any(kw in desc_lower for kw in top_keywords):
            return "\n".join(lines[:context_lines])

        # Heuristic 2: bottom of file
        bottom_keywords = {"bottom", "end of file", "append", "last line", "add to end"}
        if any(kw in desc_lower for kw in bottom_keywords):
            return "\n".join(lines[-context_lines:])

        # Heuristic 3: find function or class by name
        # Extract potential identifiers from description (camelCase, snake_case, etc.)
        identifiers = re.findall(r'\b[a-zA-Z_]\w{2,}\b', description)
        for ident in identifiers:
            for i, line in enumerate(lines):
                if re.match(rf'^(async\s+)?def\s+{re.escape(ident)}\s*\(', line) or \
                   re.match(rf'^class\s+{re.escape(ident)}[\s:(]', line):
                    # Found the function/class definition — return it with context
                    start = max(0, i - 10)  # 10 lines before for imports/decorators
                    end = min(len(lines), i + context_lines)
                    return "\n".join(lines[start:end])

        # Fallback: keyword scoring (original behavior)
        desc_words = set(re.findall(r"\w+", desc_lower))
        best_idx = 0
        best_score = -1
        for i, line in enumerate(lines):
            line_words = set(re.findall(r"\w+", line.lower()))
            score = len(desc_words & line_words)
            if score > best_score:
                best_score = score
                best_idx = i
        start = max(0, best_idx - context_lines)
        end = min(len(lines), best_idx + context_lines)
        return "\n".join(lines[start:end])

    @staticmethod
    def _parse_search_replace(text: str) -> Optional[Tuple[str, str]]:
        """Parse <<<SEARCH ... >>> <<<REPLACE ... >>> blocks from coder output."""
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text.strip())
        text = re.sub(r"\n?```$", "", text)
        # Primary: well-formed output with closing >>>
        m = re.search(
            r"<<<SEARCH\s*\n(.*?)\n>>>\s*\n<<<REPLACE\s*\n(.*?)\n>>>",
            text, re.DOTALL,
        )
        if not m:
            # Fallback: coder omitted the closing >>> after REPLACE block
            m = re.search(
                r"<<<SEARCH\s*\n(.*?)\n>>>\s*\n<<<REPLACE\s*\n(.*?)$",
                text, re.DOTALL,
            )
        if not m:
            return None
        return m.group(1).rstrip(), m.group(2).rstrip()


# ─── Phase 2: Adapter Functions ───────────────────────────────────────────────

async def execute_task_from_queue(task: dict) -> dict:
    """Adapter: run a queue task through the existing Phase 1 execution pipeline.

    Takes a task dict from TaskQueue (keys: id, description, priority, risk, affected_files).
    Returns a result dict for the AutonomousLoop.
    """
    task_id = task["id"]
    description = task["description"]

    result = {
        "success": False,
        "commit_hash": None,
        "blockchain_tx": None,
        "branch": f"task/{task_id}",
        "error": None,
        "diffs": [],
        "lines_added": 0,
        "lines_removed": 0,
        "files_changed": 0,
    }

    try:
        ctx = TaskContext(
            task_id=task_id,
            description=description,
            status="analyzing",
        )
        # Pre-set clarification_rounds to MAX so _analyze never blocks waiting for user input
        ctx.clarification_rounds = MAX_CLARIFICATION_ROUNDS
        bot.active_task = ctx
        bot._current_queue_task = task
        bot.cancel_requested = False

        # Analysis — wraps bot._analyze (coordinator LLM: clarity check + file identification)
        await bot._analyze(description)
        if bot.active_task is None or ctx.status == "failed":
            result["error"] = "Analysis failed"
            return result

        # Planning — wraps bot._plan (coordinator LLM: step-by-step plan)
        await bot._plan()
        if bot.active_task is None or ctx.status == "failed":
            result["error"] = "Planning failed"
            return result

        # Execution — wraps bot._execute (coder LLM + SEARCH/REPLACE + git branch/commit + blockchain log)
        # _execute sets status="executing" internally; active_task must be set (checked above)
        await bot._execute()

        # Collect results (commit_hash and tx_hash are local to _execute, not stored on ctx)
        if ctx.status == "done":
            result["success"] = True
            result["branch"] = ctx.branch_name or result["branch"]
            result["diffs"] = list(ctx.patches)
            result["files_changed"] = len({s["file"] for s in (ctx.plan or [])})
            for diff in ctx.patches:
                for line in diff.split("\n"):
                    if line.startswith("+") and not line.startswith("+++"):
                        result["lines_added"] += 1
                    elif line.startswith("-") and not line.startswith("---"):
                        result["lines_removed"] += 1
            # Retrieve commit hash via git (consistent with _run_git usage in _execute)
            proc = await asyncio.create_subprocess_exec(
                "git", "log", "-1", "--format=%H",
                cwd=str(NEXUS_ROOT),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            commit_h = stdout.decode().strip()
            if commit_h:
                result["commit_hash"] = commit_h[:12]
        else:
            result["error"] = f"Execution failed (status: {ctx.status})"

    except Exception as e:
        result["error"] = str(e)[:500]

    finally:
        bot._current_queue_task = None

    return result


async def decompose_task_wrapper(task: dict):
    """Adapter: call decompose_task with the bot's existing LLM router."""
    async def llm_call(agent_id, messages, task_type, **kwargs):
        # bot.router.generate is already async — no run_in_executor needed
        return await bot.router.generate(
            agent_id, messages, task_type=task_type, **kwargs
        )

    return await decompose_task(task, llm_call)


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv("/opt/nexus/agents/.env")
    except ImportError:
        pass

    token = os.getenv("DEV_ASSISTANT_TOKEN")
    if not token:
        sys.exit("ERROR: DEV_ASSISTANT_TOKEN not set. Add it to /opt/nexus/agents/.env")

    # Ensure log directory exists
    os.makedirs("/opt/nexus/agents/logs", exist_ok=True)

    intents = discord.Intents.default()
    intents.message_content = True
    intents.messages         = True
    intents.guilds           = True
    intents.reactions        = True

    bot = DevAssistant(intents=intents)
    bot.run(token)
