#!/usr/bin/env python3
"""NEXUS OS CEO Discord Bot.

Proof-of-concept: Discord → LangGraph → HuggingFace LLM → Formatted Response.
Listens in #ceo-office, processes every message through the CEO reasoning
workflow, and replies with a structured embed.
"""
import asyncio
import os
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands
from dotenv import load_dotenv

from agent_workflow import NexusAgentWorkflow
from blockchain_logger import get_blockchain_logger
from llm_client import get_llm_client

# ── Logging ──────────────────────────────────────────────────────────

os.makedirs("/opt/nexus/agents/logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-12s %(levelname)-7s %(message)s",
    handlers=[
        logging.FileHandler("/opt/nexus/agents/logs/ceo_bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("ceo_bot")

# ── Environment ──────────────────────────────────────────────────────

load_dotenv("/opt/nexus/agents/.env")
CEO_TOKEN = os.getenv("CEO_TOKEN")
GUILD_ID_STR = os.getenv("GUILD_ID")

if not CEO_TOKEN:
    raise ValueError("CEO_TOKEN not found in /opt/nexus/agents/.env")
if not GUILD_ID_STR:
    raise ValueError("GUILD_ID not found in /opt/nexus/agents/.env")

GUILD_ID = int(GUILD_ID_STR)
CHANNEL_NAME = "ceo-office"

# ── Priority colours ─────────────────────────────────────────────────

_PRIORITY_COLORS = {
    1: discord.Color.green(),
    2: discord.Color.green(),
    3: discord.Color.gold(),
    4: discord.Color.orange(),
    5: discord.Color.red(),
}

_PRIORITY_LABELS = {
    1: "Low",
    2: "Medium",
    3: "High",
    4: "Urgent",
    5: "Critical",
}

# ── Bot setup ────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

workflow: NexusAgentWorkflow | None = None
ceo_channel: discord.TextChannel | None = None


@bot.event
async def on_ready():
    global workflow, ceo_channel

    logger.info("Connected as %s (id=%s)", bot.user, bot.user.id)

    # ── Initialize LangGraph workflow ────────────────────────────────
    workflow = NexusAgentWorkflow("ceo")
    logger.info("LangGraph CEO workflow initialised")

    # ── Find or create #ceo-office ───────────────────────────────────
    guild = discord.utils.get(bot.guilds, id=GUILD_ID)
    if not guild:
        logger.error("Guild %d not found – bot may not be invited", GUILD_ID)
        return

    logger.info("Guild: %s (%d members)", guild.name, guild.member_count)

    ceo_channel = discord.utils.get(guild.text_channels, name=CHANNEL_NAME)
    if ceo_channel:
        logger.info("#%s found (id=%s)", CHANNEL_NAME, ceo_channel.id)
    else:
        logger.warning("#%s not found, creating…", CHANNEL_NAME)
        try:
            ceo_channel = await guild.create_text_channel(
                CHANNEL_NAME,
                topic="NEXUS OS CEO – Strategic decisions and directives",
            )
            logger.info("#%s created (id=%s)", CHANNEL_NAME, ceo_channel.id)
        except discord.Forbidden:
            logger.error("Missing permissions to create #%s", CHANNEL_NAME)
            return

    # ── Announce readiness ───────────────────────────────────────────
    ready_embed = discord.Embed(
        title="NEXUS CEO Online",
        description=(
            "Blockchain-native AI executive ready.\n"
            "Send any message in this channel for a strategic decision."
        ),
        color=discord.Color.blue(),
        timestamp=datetime.now(timezone.utc),
    )
    ready_embed.add_field(name="Model", value="Qwen/Qwen2.5-7B-Instruct", inline=True)
    ready_embed.add_field(name="Pipeline", value="4-node LangGraph", inline=True)
    ready_embed.add_field(name="ECT Budget", value="1000/day", inline=True)
    ready_embed.set_footer(text="NEXUS OS Phase 3")

    try:
        await ceo_channel.send(embed=ready_embed)
    except discord.Forbidden:
        logger.warning("Cannot send to #%s – check bot permissions", CHANNEL_NAME)

    logger.info("CEO bot fully ready")


@bot.event
async def on_message(message: discord.Message):
    # Ignore own messages; allow webhooks and human users
    if message.author == bot.user:
        return
    if message.author.bot and not message.webhook_id:
        return

    # Only act in #ceo-office
    if ceo_channel is None or message.channel.id != ceo_channel.id:
        return

    # Skip empty messages or very short ones
    content = message.content.strip()
    if len(content) < 3:
        return

    logger.info(
        "Message from %s: %s",
        message.author.display_name,
        content[:120],
    )

    try:
        async with message.channel.typing():
            result = await workflow.process_message(content)

        # Log to blockchain
        tx_hash = None
        try:
            bc = get_blockchain_logger()
            tx_hash = await bc.log_decision(
                agent_id="ceo",
                task=content[:100],
                reasoning_hash=result.get("reasoning_hash", ""),
                ect_cost=result.get("ect_cost", 0),
            )
        except Exception as bc_exc:
            logger.warning("Blockchain log skipped: %s", bc_exc)

        await _send_decision_embed(message, result, tx_hash=tx_hash)

    except Exception as exc:
        logger.error("Workflow error: %s", exc, exc_info=True)
        await _send_error_embed(message, exc)


# ── Embed builders ───────────────────────────────────────────────────

async def _send_decision_embed(message: discord.Message, result: dict, *, tx_hash: str | None = None):
    """Format a workflow result as a rich Discord embed."""
    decision = result["decision"]
    priority = int(decision.get("priority", 3))
    color = _PRIORITY_COLORS.get(priority, discord.Color.blue())
    label = _PRIORITY_LABELS.get(priority, "Unknown")

    ts = result.get("timestamp", "")
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        dt = datetime.now(timezone.utc)

    embed = discord.Embed(
        title="NEXUS CEO Decision",
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
        value=", ".join(delegates) if delegates else "None (handling directly)",
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

    # Show analysis summary if present
    analysis = result.get("analysis")
    if analysis:
        embed.add_field(
            name="Situation Analysis",
            value=_trunc(analysis, 1024),
            inline=False,
        )

    # Warning if parsing failed
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
    footer += " | NEXUS OS Blockchain Kernel"
    embed.set_footer(text=footer)

    await message.reply(embed=embed)
    logger.info(
        "Reply sent: priority=%d ect=%s delegates=%s hash=%s…",
        priority,
        result.get("ect_cost"),
        delegates,
        rhash[:12],
    )


async def _send_error_embed(message: discord.Message, exc: Exception):
    embed = discord.Embed(
        title="Error",
        description=_trunc(f"Failed to process request:\n```{exc}```", 2048),
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="NEXUS OS CEO Bot")
    await message.reply(embed=embed)


def _trunc(text: str, limit: int) -> str:
    """Truncate text to fit Discord embed field limits."""
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "…"


# ── Entry point ──────────────────────────────────────────────────────

async def _shutdown():
    """Cleanly close the LLM session."""
    client = get_llm_client()
    await client.close()


if __name__ == "__main__":
    try:
        bot.run(CEO_TOKEN, log_handler=None)
    except discord.LoginFailure:
        logger.error("Invalid CEO_TOKEN – check /opt/nexus/agents/.env")
    except KeyboardInterrupt:
        logger.info("Shutting down…")
    except Exception as exc:
        logger.error("Fatal: %s", exc, exc_info=True)
    finally:
        asyncio.run(_shutdown())
