#!/usr/bin/env python3
"""NEXUS OS CAF — Command Executor

Bridges parsed human commands (from intent_parser) to orchestrator actions.

Public API:
    execute_command(parsed) -> str   (Discord-ready reply, or "" for ack)
"""
import logging
import re
import subprocess
from pathlib import Path

log = logging.getLogger("command_executor")

REGISTRY_PATH = Path("/opt/nexus/automation/intent_registry.yaml")


# ── Main dispatcher ───────────────────────────────────────────────────────────

def execute_command(parsed: dict) -> str:
    """Execute a parsed command and return a Discord-ready reply string.

    Returns "" for ack-only messages that need no visible reply.
    """
    action    = parsed.get("action", "unknown")
    intent_id = parsed.get("intent_id")
    params    = parsed.get("params", {})
    raw       = parsed.get("raw", "")

    _DISPATCH = {
        "approve":          _handle_approve,
        "approve_and_start": _handle_approve_and_start,
        "retry":            _handle_retry,
        "skip":             _handle_skip,
        "block":            _handle_block,
        "status":           _handle_status,
        "current_work":     _handle_current_work,
        "queue":            _handle_queue,
        "reprioritize":     _handle_reprioritize,
        "add_task":         _handle_add_task,
        "direction":        _handle_direction,
        "help":             _handle_help,
        "ack":              _handle_ack,
        "question":         _handle_question,
        "pause":            _handle_pause,
        "resume":           _handle_resume,
        "reindex":          _handle_reindex,
        "unknown":          _handle_unknown,
    }

    handler = _DISPATCH.get(action, _handle_unknown)
    try:
        return handler(intent_id=intent_id, params=params, raw=raw)
    except Exception as e:
        log.error("execute_command(%s) failed: %s", action, e)
        return f"⚠️ Command error: {e}"


# ── Approve ───────────────────────────────────────────────────────────────────

def _handle_approve(intent_id, params, raw) -> str:
    if intent_id == "all":
        return _approve_all()

    if not intent_id:
        return "Which intent should I approve? Try `approve <id>`."

    try:
        from planning_engine import (
            load_intent_registry, update_intent_autonomous, update_intent_status,
        )
        from intent_parser import set_context

        intents    = load_intent_registry()
        intent_map = {i["id"]: i for i in intents}

        if intent_id not in intent_map:
            return f"⚠️ Intent `{intent_id}` not found."

        intent = intent_map[intent_id]
        ok     = update_intent_autonomous(intent_id, True)

        # If blocked or failed, reset to pending so orchestrator can pick it up
        if intent.get("status") in ("blocked", "failed"):
            update_intent_status(intent_id, "pending")
            log.info("_handle_approve: reset %s from %s → pending", intent_id, intent.get("status"))

        set_context(intent_id=intent_id, approval_id=intent_id)

        if ok:
            return (
                f"✅ Approved `{intent_id}` — {intent.get('title', '')}\n"
                "I'll pick it up next cycle."
            )
        return f"⚠️ `{intent_id}` is already autonomous or the field is missing."
    except Exception as e:
        log.error("_handle_approve: %s", e)
        return f"⚠️ Approve failed: {e}"


def _approve_all() -> str:
    try:
        from planning_engine import (
            load_intent_registry, update_intent_autonomous, update_intent_status,
        )

        intents  = load_intent_registry()
        done_ids = {i["id"] for i in intents if i["status"] in ("completed", "decomposed")}
        approved = []

        # Approve all pending intents whose deps are met (regardless of current autonomous flag)
        for intent in intents:
            if intent["status"] != "pending":
                continue
            deps = intent.get("depends_on") or []
            if all(d in done_ids for d in deps):
                update_intent_autonomous(intent["id"], True)
                approved.append(intent["id"])

        # Also reset failed intents to pending so they get retried
        retried = []
        for intent in intents:
            if intent["status"] == "failed":
                if update_intent_status(intent["id"], "pending"):
                    update_intent_autonomous(intent["id"], True)
                    retried.append(intent["id"])

        parts = []
        if approved:
            parts.append("✅ Approved %d pending: %s" % (
                len(approved), ", ".join(f"`{i}`" for i in approved)))
        if retried:
            parts.append("🔄 Reset %d failed for retry: %s" % (
                len(retried), ", ".join(f"`{i}`" for i in retried)))

        # Also unblock blocked intents whose deps are now all met
        unblocked = []
        for intent in intents:
            if intent["status"] == "blocked":
                deps = intent.get("depends_on") or []
                if all(d in done_ids for d in deps):
                    if update_intent_status(intent["id"], "pending"):
                        update_intent_autonomous(intent["id"], True)
                        unblocked.append(intent["id"])
                        log.info("_approve_all: unblocked %s (deps met)", intent["id"])
        if unblocked:
            parts.append("🔓 Unblocked %d (deps met): %s" % (
                len(unblocked), ", ".join(f"`{i}`" for i in unblocked)))

        if parts:
            return "\n".join(parts) + "\nStarting work now."

        # Nothing was actionable — show detailed blocker info
        blocked_by_dep = [i for i in intents if i["status"] == "pending"
                          and any(d not in done_ids for d in (i.get("depends_on") or []))]
        if blocked_by_dep:
            import json as _json
            from datetime import datetime, timezone
            try:
                with open('/opt/nexus/automation/.task_timings.json') as _f:
                    timings = _json.load(_f)
            except Exception:
                timings = {}
            id_to_intent = {i["id"]: i for i in intents}
            now   = datetime.now(timezone.utc)
            lines = [f"⚠️ {len(blocked_by_dep)} intent(s) blocked by unfinished dependencies:\n"]
            for intent in blocked_by_dep[:5]:
                unmet = [d for d in (intent.get("depends_on") or []) if d not in done_ids]
                for dep_id in unmet[:2]:
                    dep        = id_to_intent.get(dep_id, {})
                    dep_status = dep.get("status", "unknown")
                    age_str    = ""
                    ts = timings.get(dep_id, {}).get("started_at")
                    if ts:
                        try:
                            started = datetime.fromisoformat(ts)
                            if started.tzinfo is None:
                                started = started.replace(tzinfo=timezone.utc)
                            secs = int((now - started).total_seconds())
                            h, m = divmod(secs // 60, 60)
                            age_str = f", {h}h {m}m ago" if h else f", {m}m ago"
                        except Exception:
                            pass
                    lines.append(
                        f"  • `{intent['id']}` ← `{dep_id}` (status: **{dep_status}**{age_str})"
                    )
            return "\n".join(lines)

        return "Everything is either running, completed, or blocked by dependencies."
    except Exception as e:
        log.error("_approve_all: %s", e)
        return f"⚠️ Approve all failed: {e}"


# ── Approve and start ─────────────────────────────────────────────────────────

def _handle_approve_and_start(intent_id, params, raw) -> str:
    """Approve all pending intents and ensure orchestrator is running."""
    try:
        from discord_comms import set_idle_mode

        # Lift idle mode if active
        set_idle_mode(False)

        # Reuse the improved _approve_all logic
        result = _approve_all()

        # Replace the generic message with an action-oriented one
        if "Approved" in result or "Reset" in result:
            return result
        return result  # Pass through dep-blocked / already-done messages
    except Exception as e:
        log.error("_handle_approve_and_start: %s", e)
        return f"⚠️ Start failed: {e}"


# ── Retry ─────────────────────────────────────────────────────────────────────

def _handle_retry(intent_id, params, raw) -> str:
    if intent_id == "all":
        return _retry_all()

    if not intent_id:
        return "Which intent should I retry? Try `retry <id>`."

    try:
        from planning_engine import (
            load_intent_registry, update_intent_status, update_intent_autonomous,
        )
        intents    = load_intent_registry()
        intent_map = {i["id"]: i for i in intents}

        if intent_id not in intent_map:
            return f"⚠️ Intent `{intent_id}` not found."

        intent = intent_map[intent_id]
        if intent.get("status") != "failed":
            return (
                f"⚠️ `{intent_id}` is `{intent.get('status')}`, not failed — "
                "nothing to retry."
            )

        ok = update_intent_status(intent_id, "pending")
        if ok:
            update_intent_autonomous(intent_id, True)
            try:
                from failure_analyzer import clear_failure_history
                clear_failure_history(intent_id)
            except Exception:
                pass
            return (
                f"🔄 Retrying `{intent_id}` — {intent.get('title', '')}\n"
                "I'll pick it up next cycle."
            )
        return f"⚠️ Could not reset `{intent_id}` — check logs."
    except Exception as e:
        log.error("_handle_retry: %s", e)
        return f"⚠️ Retry failed: {e}"


def _retry_all() -> str:
    try:
        from planning_engine import (
            load_intent_registry, update_intent_status, update_intent_autonomous,
        )
        intents = load_intent_registry()
        retried = []

        try:
            from failure_analyzer import clear_failure_history as _clf
        except Exception:
            _clf = None

        for intent in intents:
            if intent.get("status") == "failed":
                if update_intent_status(intent["id"], "pending"):
                    update_intent_autonomous(intent["id"], True)
                    if _clf:
                        _clf(intent["id"])
                    retried.append(intent["id"])

        if retried:
            ids_str = ", ".join(f"`{i}`" for i in retried)
            return f"🔄 Retrying {len(retried)} intent(s): {ids_str}"
        return "No failed intents to retry."
    except Exception as e:
        log.error("_retry_all: %s", e)
        return f"⚠️ Retry all failed: {e}"


# ── Skip / Block ──────────────────────────────────────────────────────────────

def _handle_skip(intent_id, params, raw) -> str:
    if not intent_id:
        return "Which intent should I skip? Try `skip <id>`."

    try:
        from planning_engine import (
            load_intent_registry, update_intent_status, remove_as_dependency,
        )
        intents    = load_intent_registry()
        intent_map = {i["id"]: i for i in intents}

        if intent_id not in intent_map:
            return f"⚠️ Intent `{intent_id}` not found."

        intent     = intent_map[intent_id]
        cur_status = intent.get("status", "")
        ok         = update_intent_status(intent_id, "blocked")

        if not ok and cur_status != "blocked":
            return f"⚠️ Cannot skip `{intent_id}` from status `{cur_status}`."

        removed = remove_as_dependency(intent_id)
        return (
            f"⏭️ Skipped `{intent_id}` — {intent.get('title', '')}\n"
            f"Removed from depends_on of {removed} other intent(s). "
            "Dependents will unblock next cycle."
        )
    except Exception as e:
        log.error("_handle_skip: %s", e)
        return f"⚠️ Skip failed: {e}"


def _handle_block(intent_id, params, raw) -> str:
    if not intent_id:
        return "Which intent should I block? Try `block <id>`."

    try:
        from planning_engine import load_intent_registry, update_intent_status

        intents    = load_intent_registry()
        intent_map = {i["id"]: i for i in intents}

        if intent_id not in intent_map:
            return f"⚠️ Intent `{intent_id}` not found."

        ok = update_intent_status(intent_id, "blocked")
        if ok:
            return f"🚫 Blocked `{intent_id}` — will skip until unblocked."
        return f"⚠️ Could not block `{intent_id}` — check id/status."
    except Exception as e:
        log.error("_handle_block: %s", e)
        return f"⚠️ Block failed: {e}"


# ── Status ────────────────────────────────────────────────────────────────────

def _handle_status(intent_id, params, raw) -> str:
    try:
        from planning_engine import load_intent_registry
        from llm_router import check_tier_health
        from persona import format_for_human
        from intent_parser import set_context

        intents = load_intent_registry()
        counts  = {}
        for i in intents:
            s = i.get("status", "?")
            counts[s] = counts.get(s, 0) + 1

        in_prog = [i for i in intents if i.get("status") == "in_progress"]
        failed  = [i for i in intents if i.get("status") == "failed"]

        body = format_for_human("status", {
            "counts":      counts,
            "in_progress": in_prog[0]["title"] if in_prog else "idle",
            "tier1":       check_tier_health(1),
            "tier2":       check_tier_health(2),
            "last_error":  None,
        })

        if failed:
            body += "\n\n**❌ Failed:**"
            for f in failed:
                body += f"\n  `{f['id']}` — {f.get('title', '')[:45]}"
            body += "\n\nReply `retry all` or `retry <id>`."

        if in_prog:
            set_context(intent_id=in_prog[0]["id"])

        return body
    except Exception as e:
        log.error("_handle_status: %s", e)
        return f"⚠️ Status unavailable: {e}"


def _handle_current_work(intent_id, params, raw) -> str:
    try:
        from planning_engine import load_intent_registry
        intents = load_intent_registry()
        in_prog = [i for i in intents if i.get("status") == "in_progress"]
        if not in_prog:
            return "Nothing running right now — I'm between tasks."
        i = in_prog[0]
        return (
            f"⚙️ Working on `{i['id']}` — {i.get('title', '')}\n"
            f"{i.get('description', '')[:120].strip()}"
        )
    except Exception as e:
        return f"⚠️ Status error: {e}"


# ── Queue ─────────────────────────────────────────────────────────────────────

def _handle_queue(intent_id, params, raw) -> str:
    try:
        from planning_engine import load_intent_registry
        intents = load_intent_registry()

        counts: dict[str, list] = {
            "in_progress": [], "pending": [], "failed": [], "blocked": [], "other": []
        }
        for i in intents:
            st = i.get("status", "pending")
            bucket = st if st in counts else "other"
            counts[bucket].append(i)

        lines = []

        # Summary line
        summary_parts = []
        if counts["in_progress"]:
            summary_parts.append(f"⚙️ {len(counts['in_progress'])} running")
        if counts["pending"]:
            summary_parts.append(f"⏳ {len(counts['pending'])} pending")
        if counts["failed"]:
            summary_parts.append(f"❌ {len(counts['failed'])} failed")
        if counts["blocked"]:
            summary_parts.append(f"🚫 {len(counts['blocked'])} blocked")
        completed = sum(1 for i in intents if i.get("status") in ("completed", "decomposed"))
        if completed:
            summary_parts.append(f"✅ {completed} done")
        lines.append("**📋 Queue:** " + " · ".join(summary_parts))

        # Currently running
        if counts["in_progress"]:
            lines.append("")
            for i in counts["in_progress"]:
                lines.append(f"⚙️ `{i['id']}` — {i.get('title', '?')}")

        # Next up: show first 8 autonomous pending intents
        auto_pending = [i for i in counts["pending"] if i.get("autonomous", False)]
        locked_pending = [i for i in counts["pending"] if not i.get("autonomous", False)]
        if auto_pending:
            lines.append("")
            lines.append("**Next up:**")
            for n, i in enumerate(auto_pending[:8], 1):
                lines.append(f"{n}. `{i['id']}` — {i.get('title', '?')[:50]}")
            if len(auto_pending) > 8:
                lines.append(f"   _…and {len(auto_pending) - 8} more_")

        if locked_pending:
            lines.append("")
            ids_str = ", ".join(f"`{i['id']}`" for i in locked_pending[:5])
            more = f" + {len(locked_pending) - 5} more" if len(locked_pending) > 5 else ""
            lines.append(f"**🔒 Needs approval:** {ids_str}{more}")
            lines.append("Reply `approve all` to unlock.")

        if counts["failed"]:
            lines.append("")
            lines.append("**Failed:**")
            for i in counts["failed"][:5]:
                lines.append(f"  `{i['id']}` — {i.get('title', '?')[:45]}")
            lines.append("Reply `retry all` to requeue.")

        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Queue unavailable: {e}"


# ── Reprioritize ──────────────────────────────────────────────────────────────

def _handle_reprioritize(intent_id, params, raw) -> str:
    if not intent_id:
        return "Which intent should I focus on? Try `focus on <id>`."

    try:
        from planning_engine import load_intent_registry, update_intent_autonomous
        intents    = load_intent_registry()
        intent_map = {i["id"]: i for i in intents}
        if intent_id not in intent_map:
            return f"⚠️ Intent `{intent_id}` not found."
        update_intent_autonomous(intent_id, True)
        return f"📌 Noted — `{intent_id}` will be picked up as soon as it's unblocked."
    except Exception as e:
        return f"⚠️ Reprioritize failed: {e}"


# ── Add task ──────────────────────────────────────────────────────────────────

def _handle_add_task(intent_id, params, raw) -> str:
    title = params.get("title", raw).strip()
    if not title:
        return "What should the task be? Try `add task: <description>`."

    try:
        from planning_engine import load_intent_registry
        intents = load_intent_registry()

        # Generate next custom-NNN id
        existing_custom = [i["id"] for i in intents if i["id"].startswith("custom-")]
        nums = []
        for cid in existing_custom:
            m = re.search(r"custom-(\d+)", cid)
            if m:
                nums.append(int(m.group(1)))
        next_num = max(nums) + 1 if nums else 1
        new_id   = f"custom-{next_num:03d}"

        safe_title = title[:120].replace('"', '\\"')
        yaml_block = (
            f'\n  - id: "{new_id}"\n'
            f'    title: "{safe_title}"\n'
            f'    description: ""\n'
            f'    category: next_step\n'
            f'    status: pending\n'
            f'    risk: low\n'
            f'    complexity: low\n'
            f'    autonomous: true\n'
            f'    depends_on: []\n'
            f'    acceptance_criteria: []\n'
            f'    affected_files: []\n'
        )

        with open(REGISTRY_PATH) as f:
            content = f.read()
        with open(REGISTRY_PATH, "w") as f:
            f.write(content.rstrip() + yaml_block)

        return (
            f"✅ Added `{new_id}`: {title[:80]}\n"
            "I'll pick it up when the queue is clear."
        )
    except Exception as e:
        log.error("_handle_add_task: %s", e)
        return f"⚠️ Add task failed: {e}"


# ── Misc ──────────────────────────────────────────────────────────────────────

def _handle_direction(intent_id, params, raw) -> str:
    """Store a direction/preference note — acknowledged but not acted on autonomously."""
    return f"Got it — noted: _{raw}_"


def _handle_ack(intent_id, params, raw) -> str:
    """Acknowledgements need no visible reply."""
    return ""


def _handle_help(intent_id, params, raw) -> str:
    return (
        "**Commands:**\n"
        "`status` — queue health + what's running\n"
        "`queue` — pending/failed intent list\n"
        "`start working` — approve all pending and kick off immediately\n"
        "`approve <id>` / `approve all` — approve pending intents\n"
        "`retry <id>` / `retry all` — retry failed intents\n"
        "`skip <id>` — skip + unblock dependents\n"
        "`block <id>` — pause an intent\n"
        "`add task: <title>` — queue a custom task\n"
        "`focus on <id>` — bump an intent to the front\n"
        "`stop` / `resume` — pause or resume the orchestrator\n"
        "`reindex` — trigger a code reindex\n"
        "\nOr just ask me anything in plain English."
    )


def _handle_pause(intent_id, params, raw) -> str:
    try:
        from discord_comms import set_idle_mode
        set_idle_mode(True)
        return "⏸️ Paused — send `resume` when you're ready."
    except Exception as e:
        return f"⚠️ Pause failed: {e}"


def _handle_resume(intent_id, params, raw) -> str:
    try:
        from discord_comms import set_idle_mode
        set_idle_mode(False)
        return "▶️ Resuming."
    except Exception as e:
        return f"⚠️ Resume failed: {e}"


def _handle_reindex(intent_id, params, raw) -> str:
    try:
        subprocess.Popen(
            ["python3", "/opt/nexus/automation/indexer.py", "--collection", "all"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return "🔄 Re-index started."
    except Exception as e:
        log.error("_handle_reindex: %s", e)
        return f"⚠️ Reindex failed: {e}"


def _handle_question(intent_id, params, raw) -> str:
    """Route a free-form question to the LLM with persona context."""
    try:
        from llm_router import route_llm_call
        from context_builder import build_context_packet
        from persona import PERSONA_SYSTEM, humanize_response

        context = build_context_packet(raw)
        result  = route_llm_call(
            "ask_human",
            PERSONA_SYSTEM,
            f"Question: {raw}\n\nContext:\n{context[:2000]}\n\n"
            "Answer directly and concisely. No reasoning steps.",
        )
        raw_resp = result.get("response") or "*(LLM unavailable)*"
        return humanize_response(raw_resp)
    except Exception as e:
        log.error("_handle_question: %s", e)
        return "*(Error generating response — check logs)*"


def _handle_unknown(intent_id, params, raw) -> str:
    """Treat unknown messages as questions."""
    return _handle_question(intent_id=None, params=params, raw=raw)
