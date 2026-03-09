#!/usr/bin/env python3
"""NEXUS OS CAF — Persona module

The voice of the assistant. Every Discord-bound message passes through here
to ensure consistent, collegial tone.

Two modes:
  template — fast, deterministic, no LLM (used by default for structured events)
  llm      — generates natural prose via LLM + persona filter (optional)

Public API:
    format_for_human(message_type, raw_data)              -> str
    humanize_response(raw_llm_output)                     -> str
    generate_human_message(message_type, context={},
                            use_llm=False)                -> str
"""
import logging
import re

log = logging.getLogger("persona")

# ── Persona system prompt ─────────────────────────────────────────────────────

PERSONA_SYSTEM = """\
You are NEXUS OS, an autonomous development assistant talking to Md (the \
project founder) via Discord. Your role is to keep him informed without \
overwhelming him.

Tone: direct, collegial — like a senior engineer giving a quick status update. \
Not a chatbot. Not a log file. Not a wall of text.

Rules:
- One paragraph maximum unless complexity genuinely requires more
- Lead with the outcome, not the process
- Use past tense for completed work ("finished", "deployed", "fixed")
- Use plain language — no jargon, no bullet storms unless listing items
- Never say "I successfully completed" — just say what happened
- NEVER output thinking steps, internal reasoning, or planning artifacts
- Keep replies under 120 words unless asked for more detail\
"""

# ── Reasoning-strip patterns ──────────────────────────────────────────────────

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

_REASONING_HEADERS = [
    "thinking process", "analysis:", "reasoning:", "internal logic",
    "chain of thought", "step-by-step", "let me think", "let me consider",
    "drafting", "refining", "final polish", "determine the persona",
    "constraint:", "draft:", "check word count",
]

_STEP_VERBS = [
    "analyze", "consider", "evaluate", "assess", "determine", "draft",
    "refin", "check", "ensure", "scan", "review", "process", "establish",
    "identify", "examine", "think", "plan",
]


def humanize_response(raw: str) -> str:
    """Strip reasoning blocks from LLM output and return Discord-ready text.

    Handles:
    - <think>...</think> blocks (Qwen3 chain-of-thought tokens)
    - "Thinking Process:", "Analysis:", etc. section headers + their content
    - Numbered reasoning steps ("1. Analyze...", "2. Consider...", etc.)
    - Bullet sub-points within reasoning blocks
    - Enforces 1900-char Discord limit
    """
    text = _THINK_RE.sub("", raw)

    lines        = text.split("\n")
    in_reasoning = False
    clean: list[str] = []

    for line in lines:
        stripped = line.strip()
        lower    = stripped.lower()

        if any(p in lower for p in _REASONING_HEADERS):
            in_reasoning = True
            continue

        if stripped and stripped[0].isdigit() and "." in stripped[:4]:
            rest = stripped.split(".", 1)[1].strip().lower()
            if any(rest.startswith(v) for v in _STEP_VERBS):
                in_reasoning = True
                continue

        if in_reasoning and lower and lower[0] in ("*", "•", "-", "∙"):
            continue

        if not lower and in_reasoning:
            in_reasoning = False
            continue

        if not in_reasoning:
            clean.append(line)

    result = "\n".join(clean).strip()
    result = re.sub(r"\n{3,}", "\n\n", result)

    if len(result) < 10:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        result = paragraphs[-1] if paragraphs else text.strip()

    if not result:
        result = "*(empty response)*"
    elif len(result) > 1900:
        result = result[:1900] + "\n_(truncated)_"

    return result


# ── Templates ─────────────────────────────────────────────────────────────────

def format_for_human(message_type: str, raw_data: dict) -> str:
    """Format a structured event as a Discord-ready human message.

    raw_data keys vary by message_type:
      task_complete  : intent_id, title, steps, branch
      need_approval  : intent_id, title, risk, complexity, reason
      failure        : intent_id, title, failed_step, error, rolled_back, blocks
      status         : counts (dict), in_progress, tier1 (bool), tier2 (bool), last_error
      idle           : (no required keys)
      blocked        : intent_id, title, reason
      decomposed     : intent_id, title, sub_count, sub_ids (list)
      retry          : intent_id, title, attempt, max_attempts, reason
    """
    mt = message_type.lower()

    if mt == "task_complete":
        intent_id = raw_data.get("intent_id", "?")
        title     = raw_data.get("title", "task")
        steps     = raw_data.get("steps", "?")
        branch    = raw_data.get("branch", "?")
        return (
            f"✅ **Done:** `{intent_id}` — {title}\n"
            f"Finished in {steps} step(s). Branch: `{branch}`"
        )

    if mt == "need_approval":
        intent_id  = raw_data.get("intent_id", "?")
        title      = raw_data.get("title", "task")
        risk       = raw_data.get("risk", "unknown")
        complexity = raw_data.get("complexity", "unknown")
        reason     = raw_data.get("reason", "")
        risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(
            str(risk).lower(), "⚪"
        )
        body = (
            f"🔒 **Needs your go-ahead:** `{intent_id}` — {title}\n"
            f"{risk_emoji} {risk} risk · {complexity} complexity"
        )
        if reason:
            body += f"\n_{reason}_"
        body += f"\n\nReply `approve {intent_id}` to proceed."
        return body

    if mt == "failure":
        intent_id   = raw_data.get("intent_id", "?")
        title       = raw_data.get("title", "task")
        failed_step = raw_data.get("failed_step", "?")
        error       = str(raw_data.get("error", "unknown error"))
        rolled_back = raw_data.get("rolled_back", True)
        blocks      = raw_data.get("blocks", "none")
        rb_note     = "Rolled back." if rolled_back else "⚠️ No rollback."
        return (
            f"❌ **Failed:** `{intent_id}` — {title}\n"
            f"Step {failed_step} failed: {error[:150]}\n"
            f"{rb_note} Blocks: {blocks}\n\n"
            f"Reply `retry {intent_id}` or `skip {intent_id}`."
        )

    if mt == "status":
        counts     = raw_data.get("counts", {})
        in_prog    = raw_data.get("in_progress", "idle")
        tier1      = "🟢" if raw_data.get("tier1") else "🔴"
        tier2      = "🟢" if raw_data.get("tier2") else "🔴"
        last_error = raw_data.get("last_error") or "None"
        return (
            f"📊 **Status**\n"
            f"✅ {counts.get('completed', 0)} done · "
            f"⚙️ {counts.get('in_progress', 0)} running · "
            f"⏳ {counts.get('pending', 0)} pending · "
            f"❌ {counts.get('failed', 0)} failed\n"
            f"Now: `{in_prog}`\n"
            f"Tier 1 (ThinkPad): {tier1}  Tier 2 (nexus-ai2): {tier2}\n"
            f"Last error: {str(last_error)[:100]}"
        )

    if mt == "idle":
        return "Everything's caught up — no pending tasks right now."

    if mt == "blocked":
        intent_id = raw_data.get("intent_id", "?")
        title     = raw_data.get("title", "task")
        reason    = raw_data.get(
            "reason", "manual block or unmet dependencies"
        )
        return (
            f"🚫 **Blocked:** `{intent_id}` — {title}\n"
            f"Reason: {reason}\n\n"
            f"Reply `approve {intent_id}` to unblock."
        )

    if mt == "decomposed":
        intent_id = raw_data.get("intent_id", "?")
        title     = raw_data.get("title", "task")
        sub_count = raw_data.get("sub_count", 0)
        sub_ids   = raw_data.get("sub_ids", [])
        ids_str   = ", ".join(f"`{s}`" for s in sub_ids[:5])
        more      = f" + {sub_count - 5} more" if sub_count > 5 else ""
        return (
            f"📋 **Decomposed:** `{intent_id}` — {title}\n"
            f"Split into {sub_count} sub-task(s): {ids_str}{more}\n"
            "They'll run sequentially — I'll update you as each finishes."
        )

    if mt == "retry":
        intent_id    = raw_data.get("intent_id", "?")
        title        = raw_data.get("title", "task")
        attempt      = raw_data.get("attempt", 1)
        max_attempts = raw_data.get("max_attempts", 3)
        reason       = raw_data.get("reason", "LLM unavailable")
        return (
            f"🔄 **Retrying:** `{intent_id}` — {title}\n"
            f"Attempt {attempt}/{max_attempts}. Reason: {reason}"
        )

    if mt == "deadlock":
        failed = raw_data.get("failed", "unknown")
        return (
            f"⚠️ Queue is deadlocked — all pending tasks are blocked by failed intents.\n"
            f"Failed: {failed}\n\n"
            f"Reply `retry all` to unblock, or `status` for details."
        )

    # Unknown type — pass through as-is
    return str(raw_data)


# ── LLM-based generation ──────────────────────────────────────────────────────

def generate_human_message(
    message_type: str,
    context: dict | None = None,
    use_llm: bool = False,
) -> str:
    """Generate a human-facing Discord message.

    For most cases, delegates to format_for_human() — fast, deterministic.
    If use_llm=True and the message type benefits from prose, uses the LLM
    with PERSONA_SYSTEM prompt then passes through humanize_response().

    Args:
        message_type : One of task_complete, need_approval, failure, status,
                       idle, blocked, decomposed, retry, or any custom type.
        context      : Dict of contextual data (varies by message_type).
        use_llm      : If True, attempt LLM prose generation.

    Returns:
        str — ready to send to Discord (≤1900 chars).
    """
    ctx = context or {}

    if not use_llm:
        return format_for_human(message_type, ctx)

    # LLM prose path — only for message types that benefit from natural language
    _PROSE_TYPES = {"failure", "need_approval", "blocked"}
    if message_type.lower() not in _PROSE_TYPES:
        return format_for_human(message_type, ctx)

    try:
        from llm_router import route_llm_call  # lazy — avoid circular at module level
        user_prompt = (
            f"Write a Discord message for this event (type={message_type}):\n"
            f"{ctx}\n\n"
            "Keep it under 120 words. No reasoning, no preamble. Just the message."
        )
        result = route_llm_call("ask_human", PERSONA_SYSTEM, user_prompt)
        if result.get("response"):
            cleaned = humanize_response(result["response"])
            if len(cleaned) > 30:
                return cleaned
    except Exception as e:
        log.warning("generate_human_message LLM call failed: %s", e)

    # Fallback to template if LLM fails or response is too short
    return format_for_human(message_type, ctx)
