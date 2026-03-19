"""task_logger.py — Phase 4 Knowledge & Learning task audit log."""

import asyncio
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_LOG_FILE = Path(__file__).parent / "logs" / "task_log.jsonl"

try:
    import aiofiles
    _HAS_AIOFILES = True
except ImportError:
    _HAS_AIOFILES = False


def _resolve_log_file(override) -> Path:
    return Path(override) if override is not None else _DEFAULT_LOG_FILE


def _build_entry(task: dict, result: dict, plan=None, duration_seconds=0) -> tuple[str, dict]:
    ts = int(time.time())
    random_hex = secrets.token_hex(3)
    entry_id = f"log-{ts}-{random_hex}"

    success = bool(result.get("success", False))
    status = "done" if success else "failed"

    plan_str = None
    if plan is not None:
        plan_str = str(plan)[:500]

    entry = {
        "id": entry_id,
        "task_id": task.get("id"),
        "description": task.get("description"),
        "priority": task.get("priority"),
        "risk": task.get("risk"),
        "affected_files": task.get("affected_files"),
        "status": status,
        "success": success,
        "error": result.get("error"),
        "commit_hash": result.get("commit_hash"),
        "blockchain_tx": result.get("blockchain_tx"),
        "branch": result.get("branch"),
        "diffs": result.get("diffs"),
        "lines_added": result.get("lines_added"),
        "lines_removed": result.get("lines_removed"),
        "files_changed": result.get("files_changed"),
        "plan_summary": plan_str,
        "duration_seconds": duration_seconds,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sub_task_of": task.get("sub_task_of"),
    }
    return entry_id, entry


async def log_task(task: dict, result: dict, plan=None, duration_seconds=0, _log_file=None) -> str:
    """Append one JSON log entry and return its ID. Never raises."""
    try:
        log_file = _resolve_log_file(_log_file)
        entry_id, entry = _build_entry(task, result, plan, duration_seconds)
        line = json.dumps(entry, default=str) + "\n"

        log_file.parent.mkdir(parents=True, exist_ok=True)

        if _HAS_AIOFILES:
            async with aiofiles.open(log_file, "a", encoding="utf-8") as f:
                await f.write(line)
        else:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _sync_append, log_file, line)

        return entry_id
    except Exception:
        return f"log-error-{secrets.token_hex(3)}"


def _sync_append(log_file: Path, line: str):
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line)


def _read_entries(log_file: Path) -> list[dict]:
    if not log_file.exists():
        return []
    entries = []
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except (json.JSONDecodeError, ValueError):
                    pass
    except Exception:
        pass
    return entries


def read_recent_logs(n: int = 20, _log_file=None) -> list[dict]:
    """Return last n entries, newest first."""
    try:
        entries = _read_entries(_resolve_log_file(_log_file))
        return list(reversed(entries[-n:])) if entries else []
    except Exception:
        return []


def read_failed_logs(n: int = 20, _log_file=None) -> list[dict]:
    """Return last n failed entries (success=False), newest first."""
    try:
        entries = _read_entries(_resolve_log_file(_log_file))
        failed = [e for e in entries if not e.get("success", True)]
        return list(reversed(failed[-n:])) if failed else []
    except Exception:
        return []
