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
from discord import RawReactionActionEvent

sys.path.insert(0, "/opt/nexus/agents")
from llm_router_v2 import LLMRouter
from blockchain_logger import get_blockchain_logger

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
MAX_CLARIFICATION_ROUNDS = 2    # after this many rounds, force clear=True and proceed
MAX_FILE_SIZE            = 6000  # chars sent to LLM; longer files are truncated

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


# ─── Bot ──────────────────────────────────────────────────────────────────────

class DevAssistant(discord.Client):
    """NEXUS OS development assistant — human-in-the-loop codebase dev bot."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.router      = LLMRouter()
        self.bc          = get_blockchain_logger()
        self.guild_id    = int(os.getenv("GUILD_ID", "0"))
        self.channel_name = "agent-chat"
        self.channel: Optional[discord.TextChannel] = None
        self.owner_id    = int(os.getenv("OWNER_DISCORD_ID", "0"))
        self.active_task: Optional[TaskContext] = None

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

    # ── Message handler ───────────────────────────────────────────────────────

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user or message.author.bot:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return
        if message.channel.name != self.channel_name:
            return
        if self.owner_id and message.author.id != self.owner_id:
            return

        content_lower = message.content.strip().lower()
        task = self.active_task

        # ── 1. Executing: bot is applying patches, cannot be interrupted ──────
        if task and task.status == "executing":
            await self.channel.send(
                f"🔧 Executing — please wait ({len(task.patches)}/{MAX_STEPS_PER_TASK} steps done)."
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

        system = (
            "You are a senior software architect for NEXUS OS, a blockchain-native "
            "operating system on a Pi cluster. Analyze this development task. Identify "
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

        system = (
            "You are planning code changes for NEXUS OS. For each change, specify the "
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
        rc, _, stderr = await self._run_git("checkout", "-b", task.branch_name)
        if rc != 0:
            await self.channel.send(f"🔧 ⚠️ Could not create branch: {stderr}")
            await self._rollback()
            return

        for i, step in enumerate(task.plan):
            fpath     = step["file"]
            action    = step.get("action", "modify").lower()
            step_desc = step["description"]

            await self.channel.send(
                f"🔧 **Step {i + 1}/{len(task.plan)}** — "
                f"`{action.upper()}` `{fpath}`\n> {step_desc}"
            )

            # Current content (for context to coder)
            current = task.files_read.get(fpath) or self._read_file(fpath) or ""

            # Ask CODER to produce the complete new file content
            system = (
                "Generate the COMPLETE updated file content for this change. "
                "Output ONLY the file content — no markdown fences, no explanation. "
                "Do NOT add any features or changes beyond what is described."
            )
            user = (
                f"File: {fpath}\n"
                f"Change: {step_desc}\n\n"
                f"Current content:\n{current}"
            )

            async with self.channel.typing():
                result = await self.router.generate(
                    "ceo",   # agent_id; task_type selects coder tier
                    [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    task_type="code_gen",
                    max_tokens=4096,
                    temperature=0.1,
                )

            if result.get("error") or not result.get("content"):
                await self.channel.send(f"🔧 ⚠️ Coder failed for step {i + 1}: {result.get('error')}. Rolling back.")
                await self._rollback()
                return

            new_content = result["content"]
            # Strip accidental markdown fences the coder might still emit
            new_content = re.sub(r"^```[a-zA-Z]*\n?", "", new_content)
            new_content = re.sub(r"\n?```$", "", new_content)

            # Write file
            abs_path = self._resolve_path(fpath)
            if abs_path is None:
                await self.channel.send(f"🔧 ⚠️ Path `{fpath}` is outside /opt/nexus/ or protected. Aborting.")
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
        embed.set_footer(text="✅ Approve  •  ❌ Reject  •  or type approve/reject")

        msg = await self.channel.send(embed=embed)
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")
        return msg

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
