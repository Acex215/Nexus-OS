#!/usr/bin/env python3
"""NEXUS OS CAF — Audit Logger

Standardized audit.jsonl writer with secret redaction, sequential IDs,
and structured schema.

Public API:
    log_action(action_data)            -> None
    get_next_audit_id()                -> int
    get_audit_entry(entry_id)          -> dict | None
    get_recent_audits(n)               -> list[dict]
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from guardrails import sanitize_for_log

AUDIT_PATH = Path("/opt/nexus/automation/audit.jsonl")


def get_next_audit_id() -> int:
    """Return the next sequential audit entry ID (last id + 1, or 1 if empty)."""
    if not AUDIT_PATH.exists() or AUDIT_PATH.stat().st_size == 0:
        return 1
    # Scan backwards to find the last non-empty line
    try:
        with open(AUDIT_PATH, "rb") as f:
            # Seek near end and read a generous chunk
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, 4096)
            f.seek(-chunk, 2)
            tail = f.read().decode("utf-8", errors="replace")
        # Last non-empty line
        for line in reversed(tail.splitlines()):
            line = line.strip()
            if line:
                entry = json.loads(line)
                return int(entry.get("id", 0)) + 1
    except Exception:
        pass
    return 1


def log_action(action_data: dict) -> None:
    """Write a standardized audit entry to audit.jsonl.

    All secret-like values in the 'error' field are redacted before writing.
    Other fields are written as-is; callers should not pass raw secrets.
    """
    entry = {
        "id":                     get_next_audit_id(),
        "timestamp":              datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "action":                 action_data.get("action", "unknown"),
        "intent_id":              action_data.get("intent_id"),
        "tier_used":              action_data.get("tier_used"),
        "steps_planned":          action_data.get("steps_planned", 0),
        "steps_completed":        action_data.get("steps_completed", 0),
        "files_modified":         action_data.get("files_modified", []),
        "files_created":          action_data.get("files_created", []),
        "branch":                 action_data.get("branch"),
        "success":                action_data.get("success"),
        "discord_notified":       action_data.get("discord_notified", False),
        "execution_time_seconds": action_data.get("execution_time_seconds"),
        "context_tokens_used":    action_data.get("context_tokens_used"),
        "llm_calls":              action_data.get("llm_calls", 0),
        "error":                  sanitize_for_log(action_data.get("error") or ""),
    }
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def get_audit_entry(entry_id: int) -> dict | None:
    """Retrieve a specific audit entry by its sequential ID."""
    if not AUDIT_PATH.exists():
        return None
    with open(AUDIT_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("id") == entry_id:
                    return entry
            except json.JSONDecodeError:
                continue
    return None


def get_recent_audits(n: int = 10) -> list[dict]:
    """Return the last n audit entries (most recent last)."""
    if not AUDIT_PATH.exists():
        return []
    entries: list[dict] = []
    with open(AUDIT_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries[-n:]
