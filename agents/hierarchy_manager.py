#!/usr/bin/env python3
"""NEXUS OS Hierarchy Manager — Deploy all 30 agents as a coordinated hierarchy.

Launches 25 active Discord bots (each with its own token) and registers
5 webhook-fallback agents. Includes health monitoring, decision logging,
and graceful shutdown.
"""
import asyncio
import json
import logging
import os
import re
import signal
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import discord
from dotenv import load_dotenv

from agent_registry import AGENT_REGISTRY, get_agent, get_token_env_key
from agent_workflow import NexusAgentWorkflow
from blockchain_logger import get_blockchain_logger
from token_hooks import cost_check

# ECT costs per agent tier (used for pre-flight budget check)
_TIER_ECT_COSTS = {
    "coordinator": 50,   # C-Suite decisions
    "director": 20,      # Director decisions
    "worker": 5,         # Worker tasks
}

# Shared wallet until per-agent wallets are created
_SHARED_WALLET = "0x817B0842B208B76A7665948F8D1A0592F9b1e958"

# ── Logging ───────────────────────────────────────────────────────────

os.makedirs("/opt/nexus/agents/logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-20s %(levelname)-7s %(message)s",
    handlers=[
        logging.FileHandler("/opt/nexus/agents/logs/hierarchy.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("hierarchy")

# ── Environment ───────────────────────────────────────────────────────

load_dotenv("/opt/nexus/agents/.env")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

# ── Agent → Discord channel mapping ──────────────────────────────────
# Maps agent_id to the actual Discord channel name in the guild.
# Uses the original channel set (lower IDs, proper categories).

AGENT_CHANNEL_MAP = {
    # C-Suite
    "ceo":                 "ceo-office",
    "coo":                 "coo-operations",
    # Compute
    "compute_director":    "compute-director",
    "compute_worker_1":    "process-scheduler",
    "compute_worker_2":    "load-balancer",
    "compute_worker_3":    "container-manager",
    # Storage
    "storage_director":    "storage-director",
    "storage_worker_1":    "backup-agent",
    "storage_worker_2":    "cache-manager",
    "storage_worker_3":    "flock-federator",
    # Network
    "network_director":    "network-director",
    "network_worker_1":    "mesh-coordinator",
    "network_worker_2":    "vpn-manager",
    "network_worker_3":    "dns-agent",
    # Security
    "security_director":   "security-director",
    "security_worker_1":   "auth-agent",
    "security_worker_2":   "anomaly-detector",
    "security_worker_3":   "audit-logger",
    # Blockchain
    "blockchain_director": "blockchain-director",
    "blockchain_worker_1": "contract-deployer",
    "blockchain_worker_2": "token-manager",
    "blockchain_worker_3": "consensus-monitor",
    # ML
    "ml_director":         "ml-director",
    "ml_worker_1":         "training-coordinator",
    "ml_worker_2":         "inference-router",
    "ml_worker_3":         "inference-router",     # shares channel (webhook fallback)
    # Quantum
    "quantum_director":    "quantum-director",
    "quantum_worker_1":    "qaoa-optimizer",
    "quantum_worker_2":    "benchmark-agent",
    "quantum_worker_3":    "quantum-solver",
}

# ── Priority embed colours ────────────────────────────────────────────

_PRIORITY_COLORS = {
    1: discord.Color.green(),
    2: discord.Color.green(),
    3: discord.Color.gold(),
    4: discord.Color.orange(),
    5: discord.Color.red(),
}

_PRIORITY_LABELS = {
    1: "Low", 2: "Medium", 3: "High", 4: "Urgent", 5: "Critical",
}

# ── Delegation ECT costs per tier ────────────────────────────────────

_DELEGATION_ECT = {
    "coordinator": 50,
    "director": 20,
    "worker": 5,
}

# Reverse map: channel name → agent_id  (built from AGENT_CHANNEL_MAP at module level)
_CHANNEL_TO_AGENT: dict[str, str] = {}

# Map department name (as LLM returns it) → director agent_id
_DEPT_TO_DIRECTOR = {
    "compute":    "compute_director",
    "storage":    "storage_director",
    "network":    "network_director",
    "security":   "security_director",
    "blockchain": "blockchain_director",
    "ml":         "ml_director",
    "quantum":    "quantum_director",
}


def _resolve_delegate(name: str) -> str | None:
    """Resolve a delegates_to name to an agent_id.

    Accepts: agent_id directly ("storage_director"), department name
    ("Storage"), or display-style ("storage-director").
    """
    lower = name.lower().replace("-", "_")
    # Exact agent_id match
    if lower in AGENT_CHANNEL_MAP:
        return lower
    # Department name → director
    if lower in _DEPT_TO_DIRECTOR:
        return _DEPT_TO_DIRECTOR[lower]
    # Fuzzy: strip "_director" / "_worker_N" and try department
    for dept, agent_id in _DEPT_TO_DIRECTOR.items():
        if dept in lower:
            return agent_id
    return None


class DelegationRouter:
    """Tracks delegation chains and routes tasks between agents."""

    DELEGATION_TIMEOUT = 60  # seconds

    def __init__(self):
        self.chains: dict[str, list[str]] = {}  # chain_id → [agent_ids]
        self.pending: dict[str, asyncio.Future] = {}  # chain_id → response future
        self._lock = asyncio.Lock()
        self._log = logging.getLogger("delegation")

    async def delegate(
        self,
        *,
        chain_id: str | None,
        sender_id: str,
        sender_tier: str,
        target_id: str,
        task: str,
        manager: "HierarchyManager",
    ) -> dict | None:
        """Route a task to target_id's Discord channel and wait for response.

        Returns the target's workflow result, or None on timeout.
        """
        target_bot = manager.bots.get(target_id)
        if not target_bot or not target_bot.channel:
            self._log.warning("Cannot delegate to %s — no channel", target_id)
            return None

        target_tier = target_bot.config.get("tier", "worker")

        # ECT cost: sender pays their tier cost, target pays theirs
        sender_cost = _DELEGATION_ECT.get(sender_tier, 5)
        target_cost = _DELEGATION_ECT.get(target_tier, 5)
        total_cost = sender_cost + target_cost

        # Build or extend chain
        async with self._lock:
            if chain_id is None:
                chain_id = uuid.uuid4().hex[:12]
                self.chains[chain_id] = [sender_id]
            self.chains[chain_id].append(target_id)

        self._log.info(
            "Delegation [%s]: %s → %s (cost=%d ECT)",
            chain_id, sender_id, target_id, total_cost,
        )

        # Post delegated task to target's channel
        delegation_msg = (
            f"**Delegated from {sender_id}** (chain `{chain_id}`):\n{task}"
        )
        try:
            await target_bot.channel.send(delegation_msg)
        except Exception as exc:
            self._log.error("Failed to send delegation to #%s: %s",
                            target_bot.channel_name, exc)
            return None

        # Wait for the target's workflow to process and respond
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        async with self._lock:
            self.pending[chain_id] = future

        try:
            result = await asyncio.wait_for(future, timeout=self.DELEGATION_TIMEOUT)
            result["ect_cost"] = total_cost
            return result
        except asyncio.TimeoutError:
            self._log.warning(
                "Delegation timeout [%s]: %s did not respond in %ds",
                chain_id, target_id, self.DELEGATION_TIMEOUT,
            )
            return None
        finally:
            async with self._lock:
                self.pending.pop(chain_id, None)

    async def complete(self, chain_id: str, result: dict):
        """Called when a delegated agent finishes — resolves the waiting future."""
        async with self._lock:
            future = self.pending.get(chain_id)
        if future and not future.done():
            future.set_result(result)

    async def log_chain(self, chain_id: str, total_ect: int):
        """Log a completed delegation chain to ReasoningLedger."""
        chain = self.chains.pop(chain_id, [])
        if not chain:
            return
        task_summary = f"delegation_chain:{','.join(chain)}"
        reasoning_hash = ""
        try:
            import hashlib
            payload = json.dumps({"chain_id": chain_id, "agents": chain}, sort_keys=True)
            reasoning_hash = hashlib.sha256(payload.encode()).hexdigest()
        except Exception:
            pass
        try:
            bc = get_blockchain_logger()
            await bc.log_decision(
                agent_id=chain[0],
                task=task_summary[:100],
                reasoning_hash=reasoning_hash,
                ect_cost=total_ect,
            )
            self._log.info("Chain [%s] logged on-chain: %s, %d ECT", chain_id, chain, total_ect)
        except Exception as exc:
            self._log.warning("Chain [%s] blockchain log failed: %s", chain_id, exc)


# ── Decision log directory ────────────────────────────────────────────

DECISION_LOG_DIR = Path("/opt/nexus/agents/logs/decisions")
DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _trunc(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "…"


def _log_decision(agent_id: str, result: dict, tx_hash: str | None = None):
    """Append a decision to per-agent JSONL log."""
    path = DECISION_LOG_DIR / f"{agent_id}.jsonl"
    entry = {
        "agent_id": agent_id,
        "timestamp": result.get("timestamp", ""),
        "decision": result.get("decision", {}),
        "delegates_to": result.get("delegates_to", []),
        "ect_cost": result.get("ect_cost", 0),
        "reasoning_hash": result.get("reasoning_hash", ""),
        "tx_hash": tx_hash,
        "error": result.get("error"),
    }
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ═══════════════════════════════════════════════════════════════════════
# NexusAgentBot — one Discord client per active agent
# ═══════════════════════════════════════════════════════════════════════

class NexusAgentBot:
    """Wraps a discord.Client for a single agent in the hierarchy."""

    def __init__(self, agent_id: str, manager: "HierarchyManager | None" = None):
        self.agent_id = agent_id
        self.config = get_agent(agent_id)
        self.display_name = self.config["display_name"]
        self.token_env = get_token_env_key(agent_id)
        self.token = os.getenv(self.token_env, "")
        self.is_webhook = not self.token or self.token == "WEBHOOK_FALLBACK"
        self.channel_name = AGENT_CHANNEL_MAP.get(agent_id, "")
        self.workflow: NexusAgentWorkflow | None = None
        self.channel: discord.TextChannel | None = None
        self.client: discord.Client | None = None
        self.manager: "HierarchyManager | None" = manager
        self.ready = asyncio.Event()
        self._log = logging.getLogger(f"bot.{agent_id}")

    async def start(self):
        """Start the Discord client for this agent."""
        if self.is_webhook:
            self._log.info("Webhook fallback — skipping client start")
            self.ready.set()
            return

        intents = discord.Intents.default()
        intents.message_content = True
        intents.messages = True
        intents.guilds = True

        self.client = discord.Client(intents=intents)
        self.workflow = NexusAgentWorkflow(self.agent_id)

        @self.client.event
        async def on_ready():
            guild = discord.utils.get(self.client.guilds, id=GUILD_ID)
            if not guild:
                self._log.error("Guild %d not found", GUILD_ID)
                self.ready.set()
                return

            # Find channel — prefer first match (original set, lower position)
            matches = [
                ch for ch in guild.text_channels
                if ch.name == self.channel_name
            ]
            if matches:
                self.channel = matches[0]
                self._log.info(
                    "Ready: %s in #%s (id=%s)",
                    self.display_name, self.channel.name, self.channel.id,
                )
            else:
                self._log.warning(
                    "Channel '%s' not found for %s",
                    self.channel_name, self.agent_id,
                )

            self.ready.set()

        @self.client.event
        async def on_message(message: discord.Message):
            if message.author == self.client.user:
                return
            if message.author.bot and not message.webhook_id:
                return
            if self.channel is None or message.channel.id != self.channel.id:
                return
            content = message.content.strip()
            if len(content) < 3:
                return

            # Check if this message is a delegated task completing
            # (sent by another bot with the delegation prefix)
            chain_id = self._extract_chain_id(content)

            self._log.info(
                "Message from %s: %s",
                message.author.display_name, content[:120],
            )
            try:
                # Pre-flight ECT budget check
                tier = self.config.get("tier", "worker")
                ect_cost = _TIER_ECT_COSTS.get(tier, 5)
                allowed, _ = cost_check(_SHARED_WALLET, "exec", _SHARED_WALLET)
                if not allowed:
                    await message.reply(
                        f"⚠️ **{self.display_name}**: Insufficient ECT budget "
                        f"for this operation ({ect_cost} ECT required). Deferring."
                    )
                    self._log.warning("ECT budget check failed for %s (tier=%s, cost=%d)",
                                      self.agent_id, tier, ect_cost)
                    return

                async with message.channel.typing():
                    result = await self.workflow.process_message(content)
                # Log to blockchain (non-blocking — failures queued for retry)
                tx_hash = None
                try:
                    bc = get_blockchain_logger()
                    tx_hash = await bc.log_decision(
                        agent_id=self.agent_id,
                        task=content[:100],
                        reasoning_hash=result.get("reasoning_hash", ""),
                        ect_cost=result.get("ect_cost", 0),
                    )
                except Exception as bc_exc:
                    self._log.warning("Blockchain log skipped: %s", bc_exc)

                _log_decision(self.agent_id, result, tx_hash=tx_hash)
                await self._send_embed(message, result, tx_hash=tx_hash)

                # If this was a delegated task, complete the chain
                if chain_id and self.manager:
                    await self.manager.delegation_router.complete(chain_id, result)

                # Route delegation if the response has delegates_to
                delegates = result.get("delegates_to", [])
                if delegates and self.manager:
                    await self._handle_delegation(
                        result, delegates, content, chain_id,
                    )

            except Exception as exc:
                self._log.error("Workflow error: %s", exc, exc_info=True)
                await self._send_error(message, exc)

        try:
            await self.client.start(self.token, reconnect=True)
        except discord.LoginFailure:
            self._log.error("Invalid token for %s (%s)", self.agent_id, self.token_env)
            self.ready.set()
        except Exception as exc:
            self._log.error("Client error for %s: %s", self.agent_id, exc)
            self.ready.set()

    async def stop(self):
        """Gracefully close the Discord client."""
        if self.client and not self.client.is_closed():
            await self.client.close()
            self._log.info("Stopped %s", self.display_name)

    @staticmethod
    def _extract_chain_id(content: str) -> str | None:
        """Extract chain_id from a delegation message prefix."""
        # Format: "**Delegated from ...**  (chain `<id>`):\n..."
        m = re.search(r"\(chain `([a-f0-9]+)`\)", content)
        return m.group(1) if m else None

    async def _handle_delegation(
        self,
        result: dict,
        delegates: list[str],
        original_task: str,
        chain_id: str | None,
    ):
        """Route task to each delegate and handle timeout escalation."""
        router = self.manager.delegation_router
        tier = self.config.get("tier", "worker")
        total_chain_ect = result.get("ect_cost", 0)

        for delegate_name in delegates:
            target_id = _resolve_delegate(delegate_name)
            if not target_id:
                self._log.warning("Cannot resolve delegate: %s", delegate_name)
                continue

            task_text = result.get("decision", {}).get("decision", original_task)
            del_result = await router.delegate(
                chain_id=chain_id,
                sender_id=self.agent_id,
                sender_tier=tier,
                target_id=target_id,
                task=task_text,
                manager=self.manager,
            )

            if del_result is None:
                # Timeout — escalate back to this agent's channel
                timeout_msg = (
                    f"⏱️ **Delegation timeout**: {target_id} did not respond "
                    f"within {router.DELEGATION_TIMEOUT}s for task: {task_text[:200]}"
                )
                if self.channel:
                    try:
                        await self.channel.send(timeout_msg)
                    except Exception as exc:
                        self._log.error("Failed to post timeout notice: %s", exc)
            else:
                total_chain_ect += del_result.get("ect_cost", 0)

        # Log completed chain to ReasoningLedger
        final_chain_id = chain_id or (list(router.chains.keys()) or [None])[-1]
        if final_chain_id:
            await router.log_chain(final_chain_id, total_chain_ect)

    async def _send_embed(self, message: discord.Message, result: dict, *, tx_hash: str | None = None):
        """Send a formatted decision embed."""
        decision = result.get("decision", {})
        priority = int(decision.get("priority", 3))
        color = _PRIORITY_COLORS.get(priority, discord.Color.blue())
        label = _PRIORITY_LABELS.get(priority, "Unknown")

        ts = result.get("timestamp", "")
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            dt = datetime.now(timezone.utc)

        embed = discord.Embed(
            title=f"{self.display_name} Decision",
            color=color,
            timestamp=dt,
        )

        embed.add_field(
            name="Decision",
            value=_trunc(decision.get("decision", "N/A"), 1024),
            inline=False,
        )
        embed.add_field(
            name="Reasoning",
            value=_trunc(decision.get("reasoning", "N/A"), 1024),
            inline=False,
        )

        delegates = result.get("delegates_to", [])
        embed.add_field(
            name="Delegates To",
            value=", ".join(delegates) if delegates else "None",
            inline=True,
        )
        embed.add_field(
            name="Priority",
            value=f"{label} ({priority}/5)",
            inline=True,
        )
        embed.add_field(
            name="ECT Cost",
            value=f"{result.get('ect_cost', '?')} ECT",
            inline=True,
        )

        analysis = result.get("analysis")
        if analysis:
            embed.add_field(
                name="Analysis",
                value=_trunc(analysis, 1024),
                inline=False,
            )

        if result.get("error"):
            embed.add_field(
                name="Warning",
                value=_trunc(f"Parse issue: {result['error']}", 256),
                inline=False,
            )

        rhash = result.get("reasoning_hash", "")
        footer = f"Hash: {rhash[:16]}…"
        if tx_hash:
            footer += f" | Tx: {tx_hash[:16]}…"
        footer += f" | {self.agent_id} | NEXUS OS"
        embed.set_footer(text=footer)

        await message.reply(embed=embed)
        self._log.info(
            "Reply: priority=%d ect=%s delegates=%s",
            priority, result.get("ect_cost"), delegates,
        )

    async def _send_error(self, message: discord.Message, exc: Exception):
        embed = discord.Embed(
            title=f"{self.display_name} Error",
            description=_trunc(f"```{exc}```", 2048),
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"{self.agent_id} | NEXUS OS")
        await message.reply(embed=embed)

    @property
    def is_connected(self) -> bool:
        if self.is_webhook:
            return True
        return (
            self.client is not None
            and not self.client.is_closed()
            and self.client.is_ready()
        )

    def status_line(self) -> str:
        if self.is_webhook:
            return f"  {self.agent_id:<25s} WEBHOOK"
        if self.is_connected:
            ch = f"#{self.channel.name}" if self.channel else "no-channel"
            return f"  {self.agent_id:<25s} ONLINE  {ch}"
        return f"  {self.agent_id:<25s} OFFLINE"


# ═══════════════════════════════════════════════════════════════════════
# HierarchyManager — orchestrates all bots
# ═══════════════════════════════════════════════════════════════════════

class HierarchyManager:
    """Launch, monitor, and gracefully shut down all 30 agents."""

    HEALTH_INTERVAL = 300  # 5 minutes

    def __init__(self):
        self.bots: dict[str, NexusAgentBot] = {}
        self.delegation_router = DelegationRouter()
        self._shutdown = asyncio.Event()
        self._health_task: asyncio.Task | None = None
        self._heartbeat_channel: discord.TextChannel | None = None

        for agent_id in AGENT_REGISTRY:
            self.bots[agent_id] = NexusAgentBot(agent_id, manager=self)

        # Build reverse channel→agent map
        for aid, ch_name in AGENT_CHANNEL_MAP.items():
            _CHANNEL_TO_AGENT[ch_name] = aid

    async def start_all(self):
        """Launch all bots concurrently with staggered starts."""
        logger.info("Starting %d agents (%d active, %d webhook)…",
                     len(self.bots),
                     sum(1 for b in self.bots.values() if not b.is_webhook),
                     sum(1 for b in self.bots.values() if b.is_webhook))

        # Stagger bot logins to avoid rate limits (0.5s between each)
        tasks = []
        for i, (agent_id, bot) in enumerate(self.bots.items()):
            if bot.is_webhook:
                bot.ready.set()
                continue
            task = asyncio.create_task(bot.start(), name=f"bot-{agent_id}")
            tasks.append(task)
            # Small delay between connection attempts
            if i < len(self.bots) - 1:
                await asyncio.sleep(0.5)

        # Wait for all bots to be ready (timeout 60s)
        ready_waiters = [bot.ready.wait() for bot in self.bots.values()]
        try:
            await asyncio.wait_for(
                asyncio.gather(*ready_waiters),
                timeout=60,
            )
        except asyncio.TimeoutError:
            logger.warning("Some bots did not become ready within 60s")

        # Report status
        active = sum(1 for b in self.bots.values() if b.is_connected and not b.is_webhook)
        webhook = sum(1 for b in self.bots.values() if b.is_webhook)
        offline = len(self.bots) - active - webhook
        logger.info("Status: %d active, %d webhook, %d offline", active, webhook, offline)
        for bot in self.bots.values():
            logger.info(bot.status_line())

        # Find heartbeat channel for health reports
        await self._find_heartbeat_channel()

        # Start health monitor
        self._health_task = asyncio.create_task(self._health_loop())

        # Send initial status to heartbeat channel
        await self._post_heartbeat("Hierarchy online", active, webhook, offline)

        # Keep running until shutdown
        await self._shutdown.wait()

    async def stop_all(self):
        """Gracefully shut down all bots."""
        logger.info("Shutting down hierarchy…")

        # Cancel health monitor
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        # Stop all bots concurrently
        await asyncio.gather(
            *(bot.stop() for bot in self.bots.values()),
            return_exceptions=True,
        )

        logger.info("All agents stopped")
        self._shutdown.set()

    async def _find_heartbeat_channel(self):
        """Find the heartbeat-monitor channel from any connected bot."""
        for bot in self.bots.values():
            if bot.client and bot.client.is_ready():
                guild = discord.utils.get(bot.client.guilds, id=GUILD_ID)
                if guild:
                    ch = discord.utils.get(guild.text_channels, name="heartbeat-monitor")
                    if ch:
                        self._heartbeat_channel = ch
                        logger.info("Heartbeat channel: #heartbeat-monitor (id=%s)", ch.id)
                        return
        logger.warning("heartbeat-monitor channel not found")

    async def _health_loop(self):
        """Periodic health check every HEALTH_INTERVAL seconds."""
        try:
            while True:
                await asyncio.sleep(self.HEALTH_INTERVAL)
                active = sum(1 for b in self.bots.values() if b.is_connected and not b.is_webhook)
                webhook = sum(1 for b in self.bots.values() if b.is_webhook)
                offline = len(self.bots) - active - webhook
                logger.info("Health: %d active, %d webhook, %d offline", active, webhook, offline)

                # Process pending blockchain logs
                try:
                    bc = get_blockchain_logger()
                    await bc.process_pending()
                except Exception as exc:
                    logger.warning("Blockchain retry failed: %s", exc)

                await self._post_heartbeat("Health check", active, webhook, offline)
        except asyncio.CancelledError:
            pass

    async def _post_heartbeat(self, title: str, active: int, webhook: int, offline: int):
        """Send a heartbeat embed to #heartbeat-monitor."""
        if not self._heartbeat_channel:
            return

        color = discord.Color.green() if offline == 0 else discord.Color.orange()
        embed = discord.Embed(
            title=f"NEXUS Hierarchy: {title}",
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Active Bots", value=str(active), inline=True)
        embed.add_field(name="Webhook Agents", value=str(webhook), inline=True)
        embed.add_field(name="Offline", value=str(offline), inline=True)

        # List offline agents if any
        if offline > 0:
            names = [
                b.agent_id for b in self.bots.values()
                if not b.is_connected and not b.is_webhook
            ]
            embed.add_field(
                name="Offline Agents",
                value=", ".join(names[:10]) or "None",
                inline=False,
            )

        # Blockchain stats
        try:
            bc = get_blockchain_logger()
            entries = bc.get_entry_count()
            pending = len(bc.pending_logs)
            bc_status = f"{entries} entries"
            if pending:
                bc_status += f", {pending} pending"
            connected = bc.is_connected()
            embed.add_field(
                name="Blockchain",
                value=f"{'Online' if connected else 'OFFLINE'} | {bc_status}",
                inline=False,
            )
        except Exception:
            embed.add_field(name="Blockchain", value="Unavailable", inline=False)

        # Token economy stats
        try:
            from token_hooks import _get_client
            tc = _get_client()
            if tc:
                bal = tc.get_balances(_SHARED_WALLET)
                totals = tc.get_totals()
                embed.add_field(
                    name="Token Economy",
                    value=(
                        f"ECT: {bal['ect']} | RST: {bal['rst']}\n"
                        f"Total spent: {totals['ect_spent']} ECT | "
                        f"Earned: {totals['rst_earned']} RST | Slashed: {totals['rst_slashed']} RST"
                    ),
                    inline=False,
                )
        except Exception:
            pass

        embed.set_footer(text="NEXUS OS Hierarchy Manager")

        try:
            await self._heartbeat_channel.send(embed=embed)
        except discord.Forbidden:
            logger.warning("Cannot send to heartbeat channel")
        except Exception as exc:
            logger.error("Heartbeat send failed: %s", exc)


# ═══════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════

async def main():
    manager = HierarchyManager()

    loop = asyncio.get_running_loop()

    def _signal_handler():
        logger.info("Signal received, initiating shutdown…")
        asyncio.ensure_future(manager.stop_all())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    try:
        await manager.start_all()
    except KeyboardInterrupt:
        pass
    finally:
        await manager.stop_all()


if __name__ == "__main__":
    asyncio.run(main())
