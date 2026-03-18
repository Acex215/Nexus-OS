#!/usr/bin/env python3
"""NEXUS OS Dev Assistant — Persistent Task Queue (Phase 2)

YAML-persisted task queue with priority ordering, risk classification,
sub-task decomposition, and dependency tracking.

Usage:
    from task_queue import TaskQueue
    q = TaskQueue("/opt/nexus/agents/task_queue.yaml")
    tid = q.add("Add health check endpoint", priority="P1", risk="low")
    task = q.pop_next()        # returns highest-priority ready task
    q.update_status(tid, "done", commit_hash="abc123")

File format is human-editable YAML. The queue survives bot restarts.
"""

import hashlib
import logging
import os
import threading
from copy import deepcopy
from datetime import datetime, timezone
from typing import Optional

import yaml

log = logging.getLogger("task_queue")

# ── Constants ─────────────────────────────────────────────────────────────────

VALID_STATUSES = {
    "pending", "analyzing", "planning", "executing",
    "done", "failed", "blocked_human", "cancelled",
}
VALID_PRIORITIES = {"P0", "P1", "P2", "P3"}
VALID_RISKS = {"low", "medium", "high"}
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

DEFAULT_QUEUE_PATH = "/opt/nexus/agents/task_queue.yaml"


# ── Task helpers ──────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_task_id() -> str:
    """Generate a short, timestamped task ID."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    h = hashlib.sha256(ts.encode() + os.urandom(4)).hexdigest()[:6]
    return f"task-{ts}-{h}"


def _blank_task(task_id: str, description: str, **kwargs) -> dict:
    """Create a task dict with all required fields and sensible defaults."""
    return {
        "id": task_id,
        "description": description,
        "priority": kwargs.get("priority", "P2"),
        "status": "pending",
        "risk": kwargs.get("risk", "low"),
        "created": _now_iso(),
        "started": None,
        "completed": None,
        "branch": None,
        "parent_id": kwargs.get("parent_id", None),
        "sub_tasks": [],
        "depends_on": kwargs.get("depends_on", []),
        "affected_files": kwargs.get("affected_files", []),
        "result": {
            "success": None,
            "commit_hash": None,
            "blockchain_tx": None,
            "error": None,
            "diffs": [],
            "lines_added": 0,
            "lines_removed": 0,
            "files_changed": 0,
        },
    }


# ── TaskQueue ─────────────────────────────────────────────────────────────────

class TaskQueue:
    """Thread-safe, YAML-persisted task queue."""

    def __init__(self, path: str = DEFAULT_QUEUE_PATH):
        self._path = path
        self._lock = threading.Lock()
        # Ensure file exists
        if not os.path.exists(path):
            self._save({"tasks": []})

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> dict:
        try:
            with open(self._path, "r") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict) or "tasks" not in data:
                return {"tasks": []}
            return data
        except (yaml.YAMLError, OSError) as e:
            log.error("Failed to load task queue: %s", e)
            return {"tasks": []}

    def _save(self, data: dict) -> None:
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w") as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False, width=120)
            os.replace(tmp, self._path)
        except OSError as e:
            log.error("Failed to save task queue: %s", e)

    # ── Add / Remove ──────────────────────────────────────────────────────────

    def add(
        self,
        description: str,
        priority: str = "P2",
        risk: str = "low",
        depends_on: Optional[list[str]] = None,
        affected_files: Optional[list[str]] = None,
        parent_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> str:
        """Add a task to the queue. Returns the task ID."""
        priority = priority.upper() if priority else "P2"
        if priority not in VALID_PRIORITIES:
            priority = "P2"
        risk = (risk or "low").lower()
        if risk not in VALID_RISKS:
            risk = "low"

        tid = task_id or _make_task_id()
        task = _blank_task(
            tid, description,
            priority=priority,
            risk=risk,
            depends_on=depends_on or [],
            affected_files=affected_files or [],
            parent_id=parent_id,
        )

        with self._lock:
            data = self._load()
            data["tasks"].append(task)
            self._save(data)

        log.info("Enqueued %s [%s/%s]: %s", tid, priority, risk, description[:80])
        return tid

    def add_sub_tasks(self, parent_id: str, sub_descriptions: list[dict]) -> list[str]:
        """Add sub-tasks under a parent. Each item: {description, priority?, risk?, depends_on?}.
        Returns list of created sub-task IDs."""
        ids = []
        with self._lock:
            data = self._load()
            parent = self._find(data, parent_id)
            if not parent:
                log.error("Parent task %s not found", parent_id)
                return []

            for i, sub in enumerate(sub_descriptions):
                tid = f"{parent_id}-sub{i+1:02d}"
                task = _blank_task(
                    tid,
                    sub["description"],
                    priority=sub.get("priority", parent["priority"]),
                    risk=sub.get("risk", parent["risk"]),
                    depends_on=sub.get("depends_on", []),
                    affected_files=sub.get("affected_files", []),
                    parent_id=parent_id,
                )
                data["tasks"].append(task)
                parent.setdefault("sub_tasks", []).append(tid)
                ids.append(tid)

            self._save(data)
        return ids

    def remove(self, task_id: str) -> bool:
        """Remove a task (only if pending or cancelled)."""
        with self._lock:
            data = self._load()
            task = self._find(data, task_id)
            if not task:
                return False
            if task["status"] not in ("pending", "cancelled"):
                log.warning("Cannot remove %s in status %s", task_id, task["status"])
                return False
            data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]
            self._save(data)
        return True

    # ── Query ─────────────────────────────────────────────────────────────────

    def _find(self, data: dict, task_id: str) -> Optional[dict]:
        for t in data["tasks"]:
            if t["id"] == task_id:
                return t
        return None

    def get(self, task_id: str) -> Optional[dict]:
        with self._lock:
            data = self._load()
            t = self._find(data, task_id)
            return deepcopy(t) if t else None

    def list_pending(self) -> list[dict]:
        """Return all pending tasks sorted by priority."""
        with self._lock:
            data = self._load()
            pending = [t for t in data["tasks"] if t["status"] == "pending"]
        pending.sort(key=lambda t: PRIORITY_ORDER.get(t.get("priority", "P2"), 2))
        return deepcopy(pending)

    def list_recent(self, n: int = 5) -> list[dict]:
        """Return the N most recently completed/failed tasks."""
        with self._lock:
            data = self._load()
            finished = [t for t in data["tasks"] if t["status"] in ("done", "failed")]
        finished.sort(key=lambda t: t.get("completed") or "", reverse=True)
        return deepcopy(finished[:n])

    def list_all(self) -> list[dict]:
        with self._lock:
            data = self._load()
            return deepcopy(data["tasks"])

    def count_by_status(self) -> dict[str, int]:
        with self._lock:
            data = self._load()
            counts: dict[str, int] = {}
            for t in data["tasks"]:
                s = t.get("status", "pending")
                counts[s] = counts.get(s, 0) + 1
            return counts

    def queue_depth(self) -> int:
        with self._lock:
            data = self._load()
            return sum(1 for t in data["tasks"] if t["status"] == "pending")

    # ── Dependency resolution ─────────────────────────────────────────────────

    def _deps_satisfied(self, task: dict, all_tasks: list[dict]) -> bool:
        """Check if all depends_on tasks are in 'done' status."""
        deps = task.get("depends_on", [])
        if not deps:
            return True
        status_map = {t["id"]: t["status"] for t in all_tasks}
        return all(status_map.get(dep) == "done" for dep in deps)

    # ── Pop next ──────────────────────────────────────────────────────────────

    def pop_next(self) -> Optional[dict]:
        """Get the highest-priority pending task whose dependencies are satisfied.
        Atomically transitions it to 'analyzing'. Returns None if queue empty."""
        with self._lock:
            data = self._load()
            candidates = [
                t for t in data["tasks"]
                if t["status"] == "pending" and self._deps_satisfied(t, data["tasks"])
            ]
            if not candidates:
                return None

            # Sort: P0 first, then by created time (FIFO within same priority)
            candidates.sort(key=lambda t: (
                PRIORITY_ORDER.get(t.get("priority", "P2"), 2),
                t.get("created", ""),
            ))

            chosen = candidates[0]
            # Update in-place in data
            for t in data["tasks"]:
                if t["id"] == chosen["id"]:
                    t["status"] = "analyzing"
                    t["started"] = _now_iso()
                    break

            self._save(data)
            return deepcopy(chosen)

    # ── Status updates ────────────────────────────────────────────────────────

    def update_status(
        self,
        task_id: str,
        status: str,
        *,
        error: Optional[str] = None,
        commit_hash: Optional[str] = None,
        blockchain_tx: Optional[str] = None,
        branch: Optional[str] = None,
        diffs: Optional[list[str]] = None,
        lines_added: int = 0,
        lines_removed: int = 0,
        files_changed: int = 0,
    ) -> bool:
        """Update task status and result fields."""
        if status not in VALID_STATUSES:
            log.error("Invalid status: %s", status)
            return False

        with self._lock:
            data = self._load()
            task = self._find(data, task_id)
            if not task:
                log.error("Task %s not found", task_id)
                return False

            task["status"] = status
            if status in ("done", "failed", "cancelled"):
                task["completed"] = _now_iso()
            if branch:
                task["branch"] = branch

            result = task.setdefault("result", {})
            if status == "done":
                result["success"] = True
            elif status == "failed":
                result["success"] = False
            if error is not None:
                result["error"] = error
            if commit_hash:
                result["commit_hash"] = commit_hash
            if blockchain_tx:
                result["blockchain_tx"] = blockchain_tx
            if diffs:
                result["diffs"] = diffs
            if lines_added:
                result["lines_added"] = lines_added
            if lines_removed:
                result["lines_removed"] = lines_removed
            if files_changed:
                result["files_changed"] = files_changed

            self._save(data)
        return True

    def focus(self, task_id: str) -> bool:
        """Promote a task to P0 so it's picked next."""
        with self._lock:
            data = self._load()
            task = self._find(data, task_id)
            if not task or task["status"] != "pending":
                return False
            task["priority"] = "P0"
            self._save(data)
        return True

    # ── Stats for summary reports ─────────────────────────────────────────────

    def recent_stats(self, n: int = 5) -> dict:
        """Compute stats over the last N completed+failed tasks."""
        recent = self.list_recent(n)
        if not recent:
            return {
                "total": 0, "success": 0, "failed": 0, "rate": 0.0,
                "lines_added": 0, "lines_removed": 0, "files_changed": 0,
                "tasks": [],
            }

        success = sum(1 for t in recent if t["status"] == "done")
        failed = sum(1 for t in recent if t["status"] == "failed")
        total = success + failed
        lines_added = sum(t.get("result", {}).get("lines_added", 0) for t in recent)
        lines_removed = sum(t.get("result", {}).get("lines_removed", 0) for t in recent)
        files_changed = sum(t.get("result", {}).get("files_changed", 0) for t in recent)

        return {
            "total": total,
            "success": success,
            "failed": failed,
            "rate": (success / total * 100) if total else 0.0,
            "lines_added": lines_added,
            "lines_removed": lines_removed,
            "files_changed": files_changed,
            "tasks": recent,
        }

    # ── Migration helper ──────────────────────────────────────────────────────

    def migrate_from_intent_registry(self, registry_path: str) -> int:
        """Import pending intents from the old intent_registry.yaml.
        Returns count of tasks imported."""
        try:
            with open(registry_path, "r") as f:
                registry = yaml.safe_load(f)
        except (OSError, yaml.YAMLError) as e:
            log.error("Cannot read intent registry: %s", e)
            return 0

        if not isinstance(registry, list):
            # Some formats wrap in a top-level key
            if isinstance(registry, dict):
                registry = registry.get("intents", registry.get("tasks", []))
            if not isinstance(registry, list):
                return 0

        count = 0
        for intent in registry:
            status = intent.get("status", "pending")
            if status not in ("pending", "decomposed"):
                continue

            desc = intent.get("description", intent.get("title", ""))
            if not desc:
                continue

            priority_map = {"P0": "P0", "P1": "P1", "P2": "P2", "P3": "P3"}
            priority = priority_map.get(intent.get("priority", "P2"), "P2")
            risk = intent.get("risk", "low")
            if isinstance(risk, str):
                risk = risk.lower()
            depends = intent.get("depends_on", [])
            files = intent.get("affected_files", [])
            old_id = intent.get("id", "")

            self.add(
                desc,
                priority=priority,
                risk=risk,
                depends_on=depends if isinstance(depends, list) else [],
                affected_files=files if isinstance(files, list) else [],
                task_id=f"migrated-{old_id}" if old_id else None,
            )
            count += 1

        log.info("Migrated %d intents from %s", count, registry_path)
        return count
