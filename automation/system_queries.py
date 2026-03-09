#!/usr/bin/env python3
"""NEXUS OS — Data-driven system state queries.

Answers questions about system state from ACTUAL DATA (registry, audit log,
orchestrator log). NEVER uses the LLM for state questions — that causes
hallucinations. The LLM doesn't have access to these files.
"""
import json
import logging
import subprocess

import yaml

log = logging.getLogger("system_queries")

REGISTRY_PATH = "/opt/nexus/automation/intent_registry.yaml"
AUDIT_PATH    = "/opt/nexus/automation/audit.jsonl"
LOG_PATH      = "/opt/nexus/automation/orchestrator.log"
LEDGER_PATH   = "/opt/nexus/automation/change_ledger.md"


def _load_registry() -> dict:
    with open(REGISTRY_PATH) as f:
        return yaml.safe_load(f)


# ── Status ─────────────────────────────────────────────────────────────────────

def get_status() -> str:
    """Actual system status from registry data."""
    try:
        data    = _load_registry()
        intents = data.get("intents", [])

        in_progress = [i for i in intents if i["status"] == "in_progress"]
        pending     = [i for i in intents if i["status"] == "pending"]
        completed   = [i for i in intents if i["status"] in ("completed", "decomposed")]
        failed      = [i for i in intents if i["status"] == "failed"]
        blocked     = [i for i in intents if i["status"] == "blocked"]

        lines = []

        if in_progress:
            lines.append("**Working on:**")
            for i in in_progress:
                lines.append("  ⚙️ **%s** — %s" % (i["id"], i.get("title", "")[:50]))
        else:
            lines.append("**Working on:** Nothing right now")

        lines.append("")
        lines.append("✅ %d done · ⚙️ %d running · ⏳ %d pending · ❌ %d failed" % (
            len(completed), len(in_progress), len(pending), len(failed)))

        if failed:
            lines.append("")
            lines.append("**Failed:**")
            for i in failed:
                lines.append("  ❌ **%s** — %s" % (i["id"], i.get("title", "")[:50]))
            lines.append("  Reply `retry all` to requeue.")

        if blocked:
            lines.append("")
            lines.append("**Blocked:** %d intents" % len(blocked))

        # Show pending that need approval
        needs_approval = [i for i in pending if not i.get("autonomous", False)]
        if needs_approval:
            lines.append("")
            lines.append("**Needs approval (%d):** %s" % (
                len(needs_approval),
                ", ".join("`%s`" % i["id"] for i in needs_approval[:5]),
            ))
            lines.append("  Reply `approve all` to unlock.")

        return "\n".join(lines)
    except Exception as e:
        log.error("get_status failed: %s", e)
        return "⚠️ Could not read registry: %s" % e


# ── Queue ──────────────────────────────────────────────────────────────────────

def get_queue() -> str:
    """Show actionable intents from the actual registry."""
    try:
        data      = _load_registry()
        intents   = data.get("intents", [])
        completed = set(i["id"] for i in intents
                        if i["status"] in ("completed", "decomposed"))

        actionable       = []
        needs_approval   = []
        blocked_by_deps  = []

        for i in intents:
            if i["status"] != "pending":
                continue
            deps     = i.get("depends_on", []) or []
            deps_met = all(d in completed for d in deps)

            if deps_met and i.get("autonomous", False):
                actionable.append(i)
            elif deps_met and not i.get("autonomous", False):
                needs_approval.append(i)
            else:
                missing = [d for d in deps if d not in completed]
                blocked_by_deps.append((i, missing))

        lines = []

        if actionable:
            lines.append("**Ready to run (%d):**" % len(actionable))
            for idx, i in enumerate(actionable[:10], 1):
                lines.append("%d. 🤖 **%s** — %s" % (idx, i["id"], i.get("title", "")[:50]))

        if needs_approval:
            lines.append("")
            lines.append("**Needs your approval (%d):**" % len(needs_approval))
            for i in needs_approval[:8]:
                lines.append("  🔒 **%s** — %s" % (i["id"], i.get("title", "")[:50]))

        if blocked_by_deps:
            lines.append("")
            lines.append("**Blocked by dependencies (%d):**" % len(blocked_by_deps))
            for i, missing in blocked_by_deps[:3]:
                lines.append("  ⏸️ **%s** — waiting on %s" % (
                    i["id"], ", ".join(missing[:3])))

        if not actionable and not needs_approval and not blocked_by_deps:
            lines.append("Nothing pending right now.")
        else:
            lines.append("")
            if needs_approval:
                lines.append("Say `approve all` to greenlight everything, or `approve <id>`.")
            elif actionable:
                lines.append("Say `start working` to kick off all autonomous tasks.")

        return "\n".join(lines)
    except Exception as e:
        log.error("get_queue failed: %s", e)
        return "⚠️ Could not read registry: %s" % e


# ── Diagnose ───────────────────────────────────────────────────────────────────

def diagnose_failure(intent_id: str = None) -> str:
    """Explain WHY an intent failed using ACTUAL audit/log data, not LLM."""
    try:
        data = _load_registry()

        if not intent_id:
            failed = [i for i in data["intents"] if i["status"] == "failed"]
            if not failed:
                # Also check for blocked intents as a possible source of confusion
                blocked = [i for i in data["intents"] if i["status"] == "blocked"]
                if blocked:
                    i = blocked[0]
                    deps  = i.get("depends_on", []) or []
                    completed = set(x["id"] for x in data["intents"]
                                    if x["status"] in ("completed", "decomposed"))
                    unmet = [d for d in deps if d not in completed]
                    if unmet:
                        return "**%s** is blocked waiting on: %s" % (
                            i["id"], ", ".join("`%s`" % d for d in unmet))
                    return "**%s** is blocked (manual hold). Say `approve %s` to unblock." % (
                        i["id"], i["id"])
                return "No failed or blocked intents right now."
            intent_id = failed[0]["id"]

        # Find this intent in registry
        intent_data = next((i for i in data["intents"] if i["id"] == intent_id), None)

        # Search audit log for the actual error
        error_info = None
        try:
            with open(AUDIT_PATH) as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get("intent_id") == intent_id and not entry.get("success"):
                            error_info = entry  # keep last failure
                    except Exception:
                        pass
        except FileNotFoundError:
            pass

        if error_info:
            error_msg   = error_info.get("error", "Unknown error")
            steps_done  = error_info.get("steps_completed", 0)
            steps_total = error_info.get("steps_planned", 0)

            lines = [
                "**%s** failed at step %d/%d." % (intent_id, steps_done, steps_total),
                "",
                "**Error:** %s" % error_msg[:300],
            ]

            if "all_tiers_down" in error_msg or "tiers_down" in error_msg:
                lines.append("")
                lines.append("The LLM (ThinkPad + nexus-ai2) was offline when planning started. "
                             "It will retry automatically when a tier comes back online.")
            elif "Permission denied" in error_msg:
                lines.append("")
                lines.append("File permission issue. Reply `retry %s` after fixing." % intent_id)
            elif "timed out" in error_msg.lower():
                lines.append("")
                lines.append("LLM timed out during planning — will retry automatically.")
            elif "log" in error_msg and "not defined" in error_msg:
                lines.append("")
                lines.append("Code bug in the orchestrator (now fixed). "
                             "Reply `retry %s` to requeue." % intent_id)

            return "\n".join(lines)

        # Fallback: search orchestrator log for ERROR/FAIL lines mentioning this intent
        try:
            result = subprocess.run(
                ["grep", "-i", intent_id, LOG_PATH],
                capture_output=True, text=True, timeout=5,
            )
            # Only keep lines that are actual errors (not info lines like Discord messages)
            error_lines = [
                l for l in result.stdout.split("\n")
                if l.strip() and (
                    "error" in l.lower() or "fail" in l.lower()
                ) and "discord" not in l.lower()
            ]
            if error_lines:
                last_error = error_lines[-1].strip()
                return "**%s** — last error from log:\n`%s`" % (intent_id, last_error[:300])
        except Exception:
            pass

        if intent_data:
            status = intent_data.get("status", "?")
            return ("**%s** has status `%s` but no error detail in the audit log. "
                    "Check orchestrator.log for more info." % (intent_id, status))

        return "Intent `%s` not found in registry." % intent_id

    except Exception as e:
        log.error("diagnose_failure failed: %s", e)
        return "⚠️ Could not read audit data: %s" % e


# ── Completed summary ──────────────────────────────────────────────────────────

def get_completed_summary() -> str:
    """What was actually completed, from actual registry data."""
    try:
        data      = _load_registry()
        completed = [i for i in data["intents"]
                     if i["status"] in ("completed", "decomposed")]

        if not completed:
            return "Nothing completed yet."

        lines = ["**Completed (%d):**" % len(completed)]
        for i in completed:
            mark = "✅" if i["status"] == "completed" else "📋"
            lines.append("  %s **%s** — %s" % (mark, i["id"], i.get("title", "")[:50]))

        return "\n".join(lines)
    except Exception as e:
        return "⚠️ Could not read registry: %s" % e


# ── Recent errors ──────────────────────────────────────────────────────────────

def get_recent_errors() -> str:
    """Last few errors from the audit log."""
    errors = []
    try:
        with open(AUDIT_PATH) as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if not entry.get("success"):
                        errors.append(entry)
                except Exception:
                    pass
    except FileNotFoundError:
        return "No audit log found at %s" % AUDIT_PATH

    if not errors:
        return "No errors recorded in the audit log."

    lines = ["**Recent errors (%d total):**" % len(errors)]
    for e in errors[-5:]:
        lines.append("  ❌ **%s** — %s" % (
            e.get("intent_id", "?"), e.get("error", "?")[:120]))

    return "\n".join(lines)
