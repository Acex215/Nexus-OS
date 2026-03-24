#!/usr/bin/env python3
"""NEXUS OS CAF — Discord Communication Module

Runs as a background thread within the orchestrator (NOT a separate service).
Provides thread-safe send_notification(), blocking request_approval(), and
an inbound command handler for human-in-the-loop control.

SECURITY: DISCORD_TOKEN is loaded from .env and NEVER logged, printed, or
written to any file (audit.jsonl, orchestrator.log, stdout, stderr).

Public API:
    start_discord_listener(message_callback) -> None
    send_notification(mode, message)         -> None
    request_approval(intent_id, desc)        -> bool
    should_notify(event_type, complexity)    -> bool
    set_idle_mode(flag)                      -> None
    is_idle_mode()                           -> bool
    update_stats(**kwargs)                   -> None
"""

import asyncio
import logging
import os
import threading
from datetime import datetime, timedelta

import discord
from dotenv import load_dotenv

log = logging.getLogger("discord_comms")

# ── Credentials (loaded once at import; token NEVER re-logged) ─────────────────

load_dotenv("/opt/nexus/agents/.env")
DISCORD_TOKEN: str | None = os.getenv("CAF_DISCORD_TOKEN")
CHANNEL_ID: int = 1446026349528616990

if not DISCORD_TOKEN:
    log.error(
        "CAF_DISCORD_TOKEN not found in /opt/nexus/agents/.env — "
        "Discord integration disabled. Add CAF_DISCORD_TOKEN=<token> to .env."
    )

# ── Notification mode prefixes ─────────────────────────────────────────────────

_PREFIXES = {
    "progress": "✅ **Completed:** ",
    "failure":  "❌ **Failed:** ",
    "approval": "🔒 **Approval needed:** ",
    "question": "❓ **Question:** ",
    "opinion":  "🤔 **Decision needed:** ",
    "status":   "",   # callers supply their own emoji/header
    "chat":     "",   # conversational LLM replies — no prefix
    "alert":    "🚨 **Alert:** ",
}

# ── Discord chat system prompt ─────────────────────────────────────────────────

_DISCORD_SYSTEM = (
    "You are the NEXUS OS assistant talking with Md (the project founder) via Discord. "
    "Be conversational and direct — like a knowledgeable colleague, not a log file. "
    "NEVER output a 'Thinking Process', reasoning steps, numbered analysis, bullet "
    "chains, or any internal thought process. "
    "Answer the question directly and concisely. "
    "Keep replies under 150 words unless the user explicitly asks for more detail."
)

# ── Module state ───────────────────────────────────────────────────────────────

_client: discord.Client | None = None
_channel: discord.TextChannel | None = None
_bot_loop: asyncio.AbstractEventLoop | None = None

# pending_approvals: message_id → {"event": Event, "result": {"approved": bool}}
_pending_approvals: dict[int, dict] = {}

_idle_lock = threading.Lock()
_idle_mode: bool = False

_message_callback = None

_stats: dict = {
    "completed_today":  0,
    "completed_date":   datetime.utcnow().date().isoformat(),
    "in_progress":      "idle",
    "queue_pending":    0,
    "last_error":       None,
    "tier1_online":     False,
    "tier2_online":     True,
}

# ── Threshold logic ────────────────────────────────────────────────────────────

def should_notify(event_type: str, complexity: str = "low") -> bool:
    """Return True if this event warrants a Discord notification."""
    ALWAYS = {"service_failure", "approval_needed", "security_alert", "task_failed"}
    NEVER  = {"health_check_pass", "idle_cycle", "tier_heartbeat", "reindex_complete"}

    if event_type in ALWAYS:
        return True
    if event_type in NEVER:
        return False
    if event_type == "task_completed":
        return complexity in ("medium", "high", "very_high")
    return False


# ── Response cleaner ──────────────────────────────────────────────────────────

# Keywords that signal the start of a reasoning block
_REASONING_PATTERNS = [
    "thinking process", "analyze", "analysis:", "reasoning:",
    "internal logic", "drafting", "refining", "final polish",
    "determine the persona", "constraint:", "draft:", "check word count",
    "chain of thought", "step-by-step", "let me think", "let me consider",
]

# Verbs that follow numbered steps in reasoning ("1. Analyze...", "2. Consider...")
_STEP_VERBS = [
    "analyze", "consider", "evaluate", "assess", "determine", "draft",
    "refin", "check", "ensure", "scan", "review", "process", "establish",
    "identify", "examine", "think", "plan",
]


def clean_for_discord(text: str) -> str:
    """Aggressively strip reasoning chains from LLM output via line-walk.

    Handles:
    - <think>...</think> blocks (Qwen3 chain-of-thought tokens)
    - "Thinking Process:", "Analysis:", etc. section headers + their content
    - Numbered reasoning steps ("1. Analyze...", "2. Consider...", etc.)
    - ∙ / • / * bullet sub-points within reasoning blocks
    - Blank lines that demarcate reasoning sections
    """
    import re

    # First pass: strip explicit <think> blocks entirely
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)

    # Second pass: line-walk to catch varied reasoning formats
    lines = text.split("\n")
    in_reasoning = False
    clean_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        lower    = stripped.lower()

        # Detect a reasoning-block header
        if any(p in lower for p in _REASONING_PATTERNS):
            in_reasoning = True
            continue

        # Detect numbered reasoning step: "1. Analyze..." / "2.  Consider..."
        if stripped and stripped[0].isdigit() and "." in stripped[:4]:
            rest = stripped.split(".", 1)[1].strip().lower()
            if any(rest.startswith(v) for v in _STEP_VERBS):
                in_reasoning = True
                continue

        # Inside a reasoning block: skip bullets (sub-points of reasoning)
        if in_reasoning and lower and lower[0] in ("*", "•", "-", "∙"):
            continue

        # An empty line ends a reasoning block
        if not lower and in_reasoning:
            in_reasoning = False
            continue

        if not in_reasoning:
            clean_lines.append(line)

    result = "\n".join(clean_lines).strip()
    result = re.sub(r"\n{3,}", "\n\n", result)

    # If we stripped everything, fall back to the last non-empty paragraph
    if len(result) < 10:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        result = paragraphs[-1] if paragraphs else text.strip()

    if not result:
        result = "*(empty response)*"
    elif len(result) > 1900:
        result = result[:1900] + "\n_(truncated)_"

    return result


# ── Idle mode ──────────────────────────────────────────────────────────────────

def set_idle_mode(flag: bool) -> None:
    global _idle_mode
    with _idle_lock:
        _idle_mode = flag
    log.info("Idle mode set to %s", flag)


def is_idle_mode() -> bool:
    with _idle_lock:
        return _idle_mode


# ── Stats update ───────────────────────────────────────────────────────────────

def update_stats(**kwargs) -> None:
    """Called by orchestrator to keep status report data current."""
    today = datetime.utcnow().date().isoformat()
    if _stats.get("completed_date") != today:
        _stats["completed_today"] = 0
        _stats["completed_date"]  = today
    _stats.update(kwargs)


# ── Async send helper ──────────────────────────────────────────────────────────

async def _send_async(text: str) -> discord.Message | None:
    if _channel is None:
        log.warning("Discord channel not ready, dropping message")
        return None
    try:
        return await _channel.send(text[:2000])
    except discord.DiscordException as e:
        log.error("Discord send failed: %s", e)
        return None


# ── Public: thread-safe send ───────────────────────────────────────────────────

def send_notification(mode: str, message: str) -> None:
    """Send a Discord message from any thread.

    Non-blocking — schedules the send on the bot event loop and returns.
    Silently drops the message if Discord is not connected.
    """
    prefix = _PREFIXES.get(mode, "")
    text = prefix + message[:1900]

    if _bot_loop is None or _channel is None:
        log.warning("Discord not ready, dropping: %.80s", text)
        return

    asyncio.run_coroutine_threadsafe(_send_async(text), _bot_loop)


# ── Public: blocking approval request ─────────────────────────────────────────

def request_approval(intent_id: str, description: str) -> bool:
    """Send an approval request and block until reacted to (max 24 hours).

    Returns True if ✅ reaction received, False on ❌ or timeout.
    Safe to call from the orchestrator main thread.
    """
    if _bot_loop is None or _channel is None:
        log.warning("Discord not ready — auto-rejecting approval for %s", intent_id)
        return False

    ev = threading.Event()
    result_box: dict = {"approved": False}

    async def _ask() -> None:
        msg = await _send_async(
            f"🔒 **Approval needed:** `{intent_id}` — {description[:200]}\n"
            "React ✅ to approve, ❌ to reject."
        )
        if msg:
            try:
                await msg.add_reaction("✅")
                await msg.add_reaction("❌")
            except discord.DiscordException:
                pass
            _pending_approvals[msg.id] = {"event": ev, "result": result_box}

    asyncio.run_coroutine_threadsafe(_ask(), _bot_loop)

    # Block until reaction or 24-hour timeout
    reacted = ev.wait(timeout=86400)
    if not reacted:
        log.info("Approval timeout for %s — treating as rejected", intent_id)
    return result_box["approved"]


# ── Status report ──────────────────────────────────────────────────────────────

def send_status_summary() -> None:
    """Format and send the current CAF status to Discord.

    Live counts (in_progress, pending) are read directly from intent_registry.yaml
    so the report is accurate even after a process restart.
    completed_today and last_error remain in _stats (restart-ephemeral by design).
    """
    from llm_router import check_tier_health  # avoid circular at module level
    from planning_engine import load_intent_registry  # single source of truth

    t1 = "🟢 online" if check_tier_health(1) else "🔴 offline"
    t2 = "🟢 online" if check_tier_health(2) else "🔴 offline"
    last_err = _stats.get("last_error") or "None"

    # Derive live counts from YAML registry instead of stale _stats
    try:
        registry = load_intent_registry()
        live_in_progress = [i for i in registry if i.get("status") == "in_progress"]
        live_pending     = sum(1 for i in registry if i.get("status") == "pending")
        if live_in_progress:
            in_progress_str = ", ".join(i["id"] for i in live_in_progress[:3])
            if len(live_in_progress) > 3:
                in_progress_str += f" (+{len(live_in_progress) - 3} more)"
        else:
            in_progress_str = "idle"
    except Exception:
        # Fallback to in-memory stats if registry is unreadable
        in_progress_str = str(_stats["in_progress"])
        live_pending     = _stats["queue_pending"]

    body = (
        "📊 **CAF Status**\n"
        f"Completed today: **{_stats['completed_today']}** intents\n"
        f"In progress: `{in_progress_str}`\n"
        f"Pending queue: **{live_pending}** intents\n"
        f"Tier 1 (ThinkPad): {t1}\n"
        f"Tier 2 (nexus-ai2): {t2}\n"
        f"Last error: {str(last_err)[:120]}"
    )
    send_notification("status", body)


# ── Inbound message handler ────────────────────────────────────────────────────

def handle_discord_message(message: discord.Message) -> None:
    """Route inbound Discord messages.

    CATEGORY A — State queries: answered from actual data (registry, audit log).
                 NEVER sent to LLM — it hallucinates without access to these files.
    CATEGORY B — Commands: parsed by quick regex patterns and executed directly.
    CATEGORY C — Conversational: sent to LLM, but grounded with real system state.

    Called from within the bot event loop via run_in_executor, so
    blocking operations (including send_notification) are safe here.
    """
    import re as _re
    from intent_parser import parse_message
    from command_executor import execute_command
    from discord_reporter import send_oneshot
    from system_queries import (
        get_status, get_queue, diagnose_failure,
        get_completed_summary, get_recent_errors,
    )

    text = message.content.strip()
    log.info("Discord message from %s: %.80s", message.author.name, text)

    # ── CATEGORY A: State queries — always answer from data, never from LLM ────
    _STATE_ROUTES = [
        (r'(?i)(^status$|what.?s the status|how.?s it going|^update$|^sitrep$)',
         get_status),
        (r'(?i)(^queue$|what.?s pending|in the queue|show.*pending|'
         r'what can you work on|what are the options|show.*intents|'
         r'list.*intents|what.?s available|what.?s next)',
         get_queue),
        (r'(?i)(what are you (doing|working on)|what.?s (running|happening|in progress))',
         get_status),
        (r'(?i)(what did you (do|finish|complete)|what.?s (done|completed)|'
         r'what have you (done|finished))',
         get_completed_summary),
        (r'(?i)(show.*log|show.*error|last error|what went wrong|recent error)',
         get_recent_errors),
    ]

    for pattern, handler in _STATE_ROUTES:
        if _re.search(pattern, text):
            try:
                reply = handler()
            except Exception as e:
                log.error("State handler error: %s", e)
                reply = "⚠️ Error reading system data: %s" % e
            if reply:
                send_oneshot(reply)
            return

    # Diagnose pattern needs special handling (extracts intent id from text)
    if _re.search(r'(?i)(why.*(fail|block|stuck|error|broken|issue|problem))', text):
        m = _re.search(r'([a-z]{2,3}-[\d.]+)', text)
        intent_id = m.group(1) if m else None
        try:
            reply = diagnose_failure(intent_id)
        except Exception as e:
            reply = "⚠️ Could not diagnose: %s" % e
        if reply:
            send_oneshot(reply)
        return

    # ── CATEGORY B: Commands — parse and execute ──────────────────────────────
    try:
        parsed = parse_message(text)
        log.debug("Parsed: action=%s intent_id=%s needs_llm=%s",
                  parsed["action"], parsed["intent_id"], parsed["needs_llm"])

        if parsed.get("action") not in ("unknown", "question"):
            reply = execute_command(parsed)
            if reply:
                send_oneshot(reply)
            return
    except Exception as e:
        log.error("parse/execute error: %s", e)
        send_oneshot("⚠️ Error: %s" % e)
        return

    # ── CATEGORY C: Conversational — LLM grounded with real system state ─────
    # Give the LLM ACTUAL data so it cannot hallucinate status/errors.
    try:
        current_status = get_status()
        current_queue  = get_queue()

        from llm_router import route_llm_call
        from persona import PERSONA_SYSTEM, humanize_response

        grounded_prompt = (
            'Mo said: "%s"\n\n'
            "ACTUAL SYSTEM STATE (use ONLY this — do NOT invent information):\n"
            "%s\n\n%s\n\n"
            "Respond conversationally based ONLY on the facts above. "
            "If you don't know something from the data, say so explicitly. "
            "NEVER invent status updates, error reasons, or completed tasks."
        ) % (text, current_status, current_queue)

        result   = route_llm_call("ask_human", PERSONA_SYSTEM, grounded_prompt)
        raw_resp = result.get("response") or (
            "I'm not sure what you're asking. Try `status`, `queue`, or `help`."
        )
        reply = humanize_response(raw_resp)
    except Exception as e:
        log.error("LLM fallback error: %s", e)
        reply = "Not sure what you mean. Try `status`, `queue`, or `help`."

    if reply:
        send_oneshot(reply)


# ── Bot event loop (runs in background thread) ─────────────────────────────────

def _run_bot() -> None:
    global _client, _channel, _bot_loop

    intents = discord.Intents.default()
    intents.messages        = True
    intents.reactions       = True
    intents.message_content = True

    _client = discord.Client(intents=intents)

    # Set the loop reference BEFORE run so send_notification can queue early
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _bot_loop = loop

    @_client.event
    async def on_ready() -> None:
        global _channel
        _channel = _client.get_channel(CHANNEL_ID)
        # Log connected status WITHOUT the token
        log.info(
            "Discord connected as %s (id=%s), channel=%s",
            _client.user.name, _client.user.id, _channel,
        )

    @_client.event
    async def on_message(message: discord.Message) -> None:
        if message.author == _client.user:
            return
        if message.channel.id != CHANNEL_ID:
            return
        if _message_callback:
            # Run in executor so blocking calls inside callback don't stall the loop
            await asyncio.get_event_loop().run_in_executor(
                None, _message_callback, message
            )

    @_client.event
    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
        if payload.channel_id != CHANNEL_ID:
            return
        if _client.user and payload.user_id == _client.user.id:
            return  # ignore bot's own reactions

        entry = _pending_approvals.pop(payload.message_id, None)
        if entry is None:
            return

        emoji_str = str(payload.emoji)
        entry["result"]["approved"] = (emoji_str == "✅")
        log.info(
            "Approval reaction %s on msg %d → %s",
            emoji_str, payload.message_id, entry["result"]["approved"],
        )
        entry["event"].set()

    try:
        loop.run_until_complete(_client.start(DISCORD_TOKEN))
    except Exception as e:
        # Redact token from any exception message before logging
        safe_err = str(e).replace(DISCORD_TOKEN or "", "[REDACTED]") if DISCORD_TOKEN else str(e)
        log.error("Discord bot error: %s", safe_err)
    finally:
        loop.close()


# ── Public: start background bot thread ───────────────────────────────────────

def start_discord_listener(message_callback) -> None:
    """Start the Discord bot in a daemon background thread.

    message_callback(message) is called for every inbound message in CHANNEL_ID
    that isn't from the bot itself.

    Safe to call multiple times — subsequent calls are no-ops if bot is running.
    """
    global _message_callback

    if not DISCORD_TOKEN:
        log.error(
            "Cannot start Discord listener: CAF_DISCORD_TOKEN missing from .env. "
            "Add CAF_DISCORD_TOKEN=<token> to /opt/nexus/agents/.env and restart."
        )
        return

    _message_callback = message_callback

    t = threading.Thread(target=_run_bot, daemon=True, name="nexus-discord-bot")
    t.start()
    log.info("Discord bot thread started")
