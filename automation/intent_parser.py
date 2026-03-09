#!/usr/bin/env python3
"""NEXUS OS CAF — Intent Parser

Converts Md's casual Discord messages into structured command objects
without requiring an LLM for common patterns.

Public API:
    parse_message(text)                            -> dict
    set_context(intent_id=None, approval_id=None)  -> None

Return format:
    {
        "action":     str,          # approve|retry|skip|block|status|queue|
                                    # current_work|reprioritize|add_task|
                                    # pause|resume|reindex|help|ack|
                                    # question|direction|unknown
        "intent_id":  str | None,   # target intent if applicable
        "params":     dict,         # action-specific parameters
        "needs_llm":  bool,         # True if we fell back to LLM parsing
        "raw":        str,          # original message text
    }
"""
import json
import logging
import re

log = logging.getLogger("intent_parser")

# ── Conversation context (for pronoun resolution) ─────────────────────────────

_last_mentioned_intent: str | None = None
_last_approval_request: str | None = None


def set_context(intent_id: str | None = None, approval_id: str | None = None) -> None:
    """Update conversation context so the parser can resolve 'that', 'it', etc."""
    global _last_mentioned_intent, _last_approval_request
    if intent_id is not None:
        _last_mentioned_intent = intent_id
    if approval_id is not None:
        _last_approval_request = approval_id


# ── Quick patterns (regex, no LLM) ────────────────────────────────────────────
# Each tuple: (action_name, compiled_regex, id_group_index | None)
# id_group_index = None means no specific intent_id (use context or "all")

_ID_PAT = r"([a-z0-9][a-z0-9\-_.]*)"   # permissive intent-id fragment

QUICK_PATTERNS: list[tuple[str, re.Pattern, int | None]] = [
    # ── approve ───────────────────────────────────────────────────────────────
    (
        "approve_all",
        re.compile(r"^approve\s+all\b", re.I),
        None,
    ),
    (
        "approve",
        re.compile(r"^approve\s+" + _ID_PAT, re.I),
        1,
    ),
    (
        "approve_ctx",
        re.compile(
            r"^(approve|yes|yeah|yep|ok|okay|go ahead|do it|sure|proceed|lgtm|approved"
            r"|yeah\s+go\s+ahead|yes\s+go\s+ahead|yep\s+go\s+ahead"
            r"|yeah\s+sure|yes\s+sure|sounds\s+good|go\s+for\s+it"
            r")\s*[!.]?\s*$",
            re.I,
        ),
        None,
    ),

    # ── retry ─────────────────────────────────────────────────────────────────
    (
        "retry_all",
        re.compile(r"^retry\s+all\b", re.I),
        None,
    ),
    (
        "retry",
        re.compile(r"^retry\s+" + _ID_PAT, re.I),
        1,
    ),

    # ── skip / block ──────────────────────────────────────────────────────────
    (
        "skip_ctx",
        re.compile(r"^(skip it|skip that|move on)\s*[!.]?\s*$", re.I),
        None,
    ),
    (
        "skip",
        re.compile(r"^skip\s+" + _ID_PAT, re.I),
        1,
    ),
    (
        "block",
        re.compile(r"^block\s+" + _ID_PAT, re.I),
        1,
    ),

    # ── status / what are you doing ───────────────────────────────────────────
    (
        "status",
        re.compile(
            r"^(status|what are you (working on|doing)|how('s| is) it going)\s*\??$",
            re.I,
        ),
        None,
    ),
    (
        "current_work",
        re.compile(
            r"^(what('s| is) (running|in progress|current))\s*\??$",
            re.I,
        ),
        None,
    ),

    # ── queue ─────────────────────────────────────────────────────────────────
    (
        "queue",
        re.compile(
            r"^(queue|list|show queue|show tasks|what('s| is) (next|pending))\s*\??$",
            re.I,
        ),
        None,
    ),

    # ── reindex ───────────────────────────────────────────────────────────────
    (
        "reindex",
        re.compile(r"^reindex\b", re.I),
        None,
    ),

    # ── pause / resume ────────────────────────────────────────────────────────
    (
        "pause",
        re.compile(r"^(stop|pause|hold on|hold)\b", re.I),
        None,
    ),
    (
        "resume",
        re.compile(r"^(resume|start|continue|go)\b", re.I),
        None,
    ),

    # ── reprioritize — only quick-match explicit intent IDs (e.g. np-001)
    # Free-form "focus on blockchain" goes to LLM for proper interpretation
    (
        "reprioritize",
        re.compile(r"^(focus on|prioritize|bump)\s+([a-z][a-z0-9]*-[\d.]+)\s*$", re.I),
        2,
    ),

    # ── add task ──────────────────────────────────────────────────────────────
    (
        "add_task",
        re.compile(r"^add\s+(?:task|intent)\s*:?\s*(.+)", re.I),
        1,
    ),

    # ── approve_and_start — "start working", "work on all pending", etc. ─────
    (
        "approve_and_start",
        re.compile(
            r"^(start\s+(working|on\s+(all|the|it|them))|"
            r"work\s+on\s+(all|the|pending)|"
            r"get\s+(started|going|to\s+work)|"
            r"kick\s+it\s+off|"
            r"let'?s?\s+go|"
            r"run\s+(all|the\s+pending|them|it)|"
            r"begin|"
            r"get\s+to\s+work|"
            r"start\s+on\s+everything|"
            r"pick\s+up\s+.*work|"
            r"do\s+something|"
            r"move\s+on)\b",
            re.I,
        ),
        None,
    ),

    # ── focus — "focus on np-002", "work on np-004" ───────────────────────────
    (
        "reprioritize",
        re.compile(
            r"^(focus\s+on|work\s+on|start\s+on|pick\s+up)\s+"
            r"(?:intent\s+)?([a-z][a-z0-9]*-[\d.]+)\s*$",
            re.I,
        ),
        2,
    ),

    # ── queue — extended natural language variants ────────────────────────────
    (
        "queue",
        re.compile(
            r"(?i)^(what\s+are\s+the\s+options|what\s+can\s+you\s+work\s+on|"
            r"what.?s\s+available|show\s+(me\s+)?intents|list\s+intents|"
            r"is\s+there\s+anything\s+else|anything\s+(else\s+)?to\s+work\s+on|"
            r"can\s+you\s+work\s+on\s+anything)\s*\??$",
            re.I,
        ),
        None,
    ),

    # ── help ──────────────────────────────────────────────────────────────────
    (
        "help",
        re.compile(r"^(help|commands|what can (i|you) (do|say))\s*\??$", re.I),
        None,
    ),

    # ── acknowledgement — no reply needed ─────────────────────────────────────
    (
        "ack",
        re.compile(
            r"^(ok|okay|thanks?|got it|noted|cool|sounds good|"
            r"nice|great|perfect|k)\b[\s!.]*$",
            re.I,
        ),
        None,
    ),
]


# ── Parser ────────────────────────────────────────────────────────────────────

def parse_message(text: str) -> dict:
    """Parse a Discord message into a structured command dict.

    Tries quick regex patterns first (fast, no LLM).
    Falls back to LLM for complex or ambiguous messages.
    """
    stripped = text.strip()

    for action, pattern, id_group in QUICK_PATTERNS:
        m = pattern.match(stripped)
        if not m:
            continue

        intent_id: str | None = None
        params: dict = {}

        if id_group is not None and id_group <= len(m.groups()):
            intent_id = m.group(id_group).strip()

        # Context resolution for bare "yes" / "ok" after an approval request
        if action == "approve_ctx":
            intent_id = _last_approval_request
            action    = "approve" if intent_id else "ack"

        # Context resolution for "skip it" / "skip that"
        if action == "skip_ctx":
            intent_id = _last_mentioned_intent
            action    = "skip"

        # Normalize combined-variant actions to canonical names
        if action == "approve_all":
            action, intent_id = "approve", "all"
        elif action == "retry_all":
            action, intent_id = "retry", "all"

        if action == "add_task":
            params["title"] = intent_id or stripped
            intent_id = None

        log.debug("Quick-match: action=%s intent_id=%s", action, intent_id)
        return {
            "action":    action,
            "intent_id": intent_id,
            "params":    params,
            "needs_llm": False,
            "raw":       text,
        }

    # ── LLM fallback ──────────────────────────────────────────────────────────
    return _llm_parse(stripped)


def _llm_parse(text: str) -> dict:
    """Use the LLM to interpret an ambiguous or complex message."""
    try:
        from llm_router import route_llm_call
        from planning_engine import load_intent_registry
        intents = load_intent_registry()
        in_prog = [i["id"] for i in intents if i.get("status") == "in_progress"]
        pending = [i["id"] for i in intents if i.get("status") == "pending"][:10]
        failed  = [i["id"] for i in intents if i.get("status") == "failed"]
    except Exception:
        in_prog, pending, failed = [], [], []

    system = (
        "You interpret messages from a human to their autonomous assistant. "
        "Return ONLY JSON — no explanation, no markdown.\n"
        'Format: {"action": "...", "intent_id": null, "params": {}}\n'
        "Valid actions: approve, retry, skip, block, status, queue, "
        "current_work, add_task, reprioritize, direction, help, ack, "
        "question, pause, resume, reindex, unknown"
    )

    context_str = (
        f"In progress: {in_prog}\n"
        f"Pending: {pending}\n"
        f"Failed: {failed}\n"
        f"Last mentioned intent: {_last_mentioned_intent}\n"
    )

    user_prompt = (
        f"Current state:\n{context_str}\n"
        f'Human said: "{text}"\n\n'
        "What action do they want? "
        'If it is a general question about the project, use action="question". '
        'If it is a direction like "use Python for that", use action="direction".'
    )

    result = route_llm_call("classify", system, user_prompt)
    if result.get("error") or not result.get("response"):
        return _unknown(text)

    try:
        raw = result["response"]
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
        m   = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return _unknown(text)
        data = json.loads(m.group())
        return {
            "action":    str(data.get("action", "unknown")),
            "intent_id": data.get("intent_id"),
            "params":    dict(data.get("params", {})),
            "needs_llm": True,
            "raw":       text,
        }
    except Exception as e:
        log.debug("_llm_parse JSON error: %s", e)
        return _unknown(text)


def _unknown(text: str) -> dict:
    return {
        "action":    "unknown",
        "intent_id": None,
        "params":    {},
        "needs_llm": False,
        "raw":       text,
    }
