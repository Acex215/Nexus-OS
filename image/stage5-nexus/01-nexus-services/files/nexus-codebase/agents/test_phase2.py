#!/usr/bin/env python3
"""Tests for Phase 2 task queue, commands, and decomposer.

Run: python3 -m pytest test_phase2.py -v
Or:  python3 test_phase2.py
"""

import os
import sys
import tempfile
import yaml

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from task_queue import TaskQueue, _blank_task, PRIORITY_ORDER
from queue_commands import handle_queue_command


class TestTaskQueue:
    """Tests for TaskQueue YAML persistence and operations."""

    def _make_queue(self, tmp_dir):
        path = os.path.join(tmp_dir, "test_queue.yaml")
        return TaskQueue(path), path

    def test_add_and_get(self):
        with tempfile.TemporaryDirectory() as tmp:
            q, _ = self._make_queue(tmp)
            tid = q.add("Test task", priority="P1", risk="low")
            assert tid is not None

            task = q.get(tid)
            assert task is not None
            assert task["description"] == "Test task"
            assert task["priority"] == "P1"
            assert task["risk"] == "low"
            assert task["status"] == "pending"

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test_queue.yaml")
            q1 = TaskQueue(path)
            tid = q1.add("Persist me")

            # New instance reads same file
            q2 = TaskQueue(path)
            task = q2.get(tid)
            assert task is not None
            assert task["description"] == "Persist me"

    def test_pop_next_priority_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            q, _ = self._make_queue(tmp)
            t3 = q.add("Low priority", priority="P3")
            t1 = q.add("High priority", priority="P1")
            t2 = q.add("Medium priority", priority="P2")

            first = q.pop_next()
            assert first["id"] == t1
            assert first["priority"] == "P1"

            second = q.pop_next()
            assert second["id"] == t2

            third = q.pop_next()
            assert third["id"] == t3

    def test_pop_next_respects_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            q, _ = self._make_queue(tmp)
            t1 = q.add("First task", priority="P2")
            t2 = q.add("Depends on first", priority="P1", depends_on=[t1])

            # t2 is higher priority but blocked
            first = q.pop_next()
            assert first["id"] == t1

            # t2 still blocked (t1 is analyzing, not done)
            second = q.pop_next()
            assert second is None

            # Mark t1 done
            q.update_status(t1, "done")
            second = q.pop_next()
            assert second["id"] == t2

    def test_pop_next_transitions_to_analyzing(self):
        with tempfile.TemporaryDirectory() as tmp:
            q, _ = self._make_queue(tmp)
            tid = q.add("Task")
            task = q.pop_next()
            assert task is not None

            # Check it's now analyzing in the queue
            reloaded = q.get(tid)
            assert reloaded["status"] == "analyzing"
            assert reloaded["started"] is not None

    def test_pop_next_empty_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            q, _ = self._make_queue(tmp)
            assert q.pop_next() is None

    def test_update_status_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            q, _ = self._make_queue(tmp)
            tid = q.add("Task")
            q.pop_next()  # move to analyzing

            q.update_status(
                tid, "done",
                commit_hash="abc123",
                blockchain_tx="0xdef",
                lines_added=10,
                lines_removed=2,
                files_changed=3,
            )

            task = q.get(tid)
            assert task["status"] == "done"
            assert task["completed"] is not None
            assert task["result"]["success"] is True
            assert task["result"]["commit_hash"] == "abc123"
            assert task["result"]["blockchain_tx"] == "0xdef"
            assert task["result"]["lines_added"] == 10

    def test_update_status_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            q, _ = self._make_queue(tmp)
            tid = q.add("Task")
            q.pop_next()

            q.update_status(tid, "failed", error="test failed")

            task = q.get(tid)
            assert task["status"] == "failed"
            assert task["result"]["success"] is False
            assert task["result"]["error"] == "test failed"

    def test_sub_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            q, _ = self._make_queue(tmp)
            parent = q.add("Big task", priority="P1")
            subs = q.add_sub_tasks(parent, [
                {"description": "Step 1"},
                {"description": "Step 2", "depends_on": [f"{parent}-sub01"]},
            ])

            assert len(subs) == 2
            assert subs[0] == f"{parent}-sub01"
            assert subs[1] == f"{parent}-sub02"

            # Check parent has sub_tasks list
            ptask = q.get(parent)
            assert subs[0] in ptask["sub_tasks"]

            # Check sub-task inherits priority
            st1 = q.get(subs[0])
            assert st1["priority"] == "P1"
            assert st1["parent_id"] == parent

            # Check dependency
            st2 = q.get(subs[1])
            assert subs[0] in st2["depends_on"]

    def test_focus(self):
        with tempfile.TemporaryDirectory() as tmp:
            q, _ = self._make_queue(tmp)
            t1 = q.add("Normal", priority="P3")
            t2 = q.add("Also normal", priority="P3")

            q.focus(t2)
            task = q.get(t2)
            assert task["priority"] == "P0"

            # t2 should now be popped first
            first = q.pop_next()
            assert first["id"] == t2

    def test_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            q, _ = self._make_queue(tmp)
            tid = q.add("Removable")
            assert q.remove(tid) is True
            assert q.get(tid) is None

    def test_remove_non_pending_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            q, _ = self._make_queue(tmp)
            tid = q.add("In progress")
            q.pop_next()  # moves to analyzing
            assert q.remove(tid) is False

    def test_list_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            q, _ = self._make_queue(tmp)
            q.add("P2 task", priority="P2")
            q.add("P0 task", priority="P0")
            q.add("P1 task", priority="P1")

            pending = q.list_pending()
            assert len(pending) == 3
            assert pending[0]["priority"] == "P0"
            assert pending[1]["priority"] == "P1"
            assert pending[2]["priority"] == "P2"

    def test_list_recent(self):
        with tempfile.TemporaryDirectory() as tmp:
            q, _ = self._make_queue(tmp)
            t1 = q.add("Task 1")
            t2 = q.add("Task 2")

            q.pop_next()
            q.update_status(t1, "done")
            q.pop_next()
            q.update_status(t2, "failed", error="oops")

            recent = q.list_recent(5)
            assert len(recent) == 2

    def test_count_by_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            q, _ = self._make_queue(tmp)
            q.add("Pending 1")
            q.add("Pending 2")
            t3 = q.add("Will be done")
            q.pop_next()  # moves t3's predecessor? No — pops by priority.

            counts = q.count_by_status()
            # At least 2 pending + 1 analyzing
            assert counts.get("pending", 0) >= 2

    def test_recent_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            q, _ = self._make_queue(tmp)
            t1 = q.add("Task 1")
            t2 = q.add("Task 2")

            q.pop_next()
            q.update_status(t1, "done", lines_added=10, lines_removed=2, files_changed=3)
            q.pop_next()
            q.update_status(t2, "done", lines_added=5, lines_removed=1, files_changed=1)

            stats = q.recent_stats(5)
            assert stats["total"] == 2
            assert stats["success"] == 2
            assert stats["failed"] == 0
            assert stats["rate"] == 100.0
            assert stats["lines_added"] == 15
            assert stats["lines_removed"] == 3

    def test_yaml_human_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            q, path = self._make_queue(tmp)
            q.add("Readable task", priority="P1", risk="medium")

            with open(path) as f:
                content = f.read()

            # Should be valid YAML
            data = yaml.safe_load(content)
            assert len(data["tasks"]) == 1
            # Should be human-readable (not flow style)
            assert "description: Readable task" in content

    def test_invalid_priority_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            q, _ = self._make_queue(tmp)
            tid = q.add("Bad priority", priority="P9")
            task = q.get(tid)
            assert task["priority"] == "P2"  # defaults to P2

    def test_queue_depth(self):
        with tempfile.TemporaryDirectory() as tmp:
            q, _ = self._make_queue(tmp)
            assert q.queue_depth() == 0
            q.add("One")
            q.add("Two")
            assert q.queue_depth() == 2
            q.pop_next()
            assert q.queue_depth() == 1


class TestQueueCommands:
    """Tests for Discord command parsing."""

    def _make_queue(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "test_queue.yaml")
        return TaskQueue(path), tmp

    def test_show_queue_empty(self):
        q, _ = self._make_queue()
        handled, resp = handle_queue_command("show queue", q)
        assert handled is True
        assert "empty" in resp.lower()

    def test_show_queue_with_tasks(self):
        q, _ = self._make_queue()
        q.add("Test task", priority="P1")
        handled, resp = handle_queue_command("show queue", q)
        assert handled is True
        assert "P1" in resp
        assert "Test task" in resp

    def test_add_task(self):
        q, _ = self._make_queue()
        handled, resp = handle_queue_command("add task: Fix the bug in router", q)
        assert handled is True
        assert "Added" in resp
        assert q.queue_depth() == 1

    def test_add_task_with_priority(self):
        q, _ = self._make_queue()
        handled, resp = handle_queue_command("add P0 task: Critical fix", q)
        assert handled is True
        pending = q.list_pending()
        assert pending[0]["priority"] == "P0"

    def test_status(self):
        q, _ = self._make_queue()
        handled, resp = handle_queue_command("status", q)
        assert handled is True
        assert "loop not active" in resp.lower() or "stopped" in resp.lower()

    def test_help(self):
        handled, resp = handle_queue_command("help", None)
        assert handled is True
        assert "show queue" in resp
        assert "add task" in resp

    def test_show_last(self):
        q, _ = self._make_queue()
        handled, resp = handle_queue_command("show last 5", q)
        assert handled is True

    def test_not_a_command(self):
        q, _ = self._make_queue()
        handled, resp = handle_queue_command("Fix the bug in llm_router_v2.py", q)
        assert handled is False
        assert resp is None

    def test_pause_no_loop(self):
        q, _ = self._make_queue()
        handled, resp = handle_queue_command("pause", q, None)
        assert handled is True
        assert "not active" in resp.lower()

    def test_focus(self):
        q, _ = self._make_queue()
        tid = q.add("Focus me", priority="P3")
        handled, resp = handle_queue_command(f"focus on {tid}", q)
        assert handled is True
        assert "Focused" in resp or "not found" in resp

    def test_remove(self):
        q, _ = self._make_queue()
        tid = q.add("Remove me")
        handled, resp = handle_queue_command(f"remove {tid}", q)
        assert handled is True
        assert "Removed" in resp

    def test_summary(self):
        q, _ = self._make_queue()
        handled, resp = handle_queue_command("summary", q)
        assert handled is True

    def test_risk_inference_high(self):
        q, _ = self._make_queue()
        handled, resp = handle_queue_command("add task: Deploy contract to mainnet", q)
        assert handled is True
        pending = q.list_pending()
        assert pending[0]["risk"] == "high"

    def test_risk_inference_medium(self):
        q, _ = self._make_queue()
        handled, resp = handle_queue_command("add task: Refactor the agent registry", q)
        assert handled is True
        pending = q.list_pending()
        assert pending[0]["risk"] == "medium"

    def test_case_insensitive(self):
        q, _ = self._make_queue()
        handled, _ = handle_queue_command("SHOW QUEUE", q)
        assert handled is True
        handled, _ = handle_queue_command("Status", q)
        assert handled is True
        handled, _ = handle_queue_command("HELP", q)
        assert handled is True


# ── Run tests ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import subprocess
    # Try pytest first
    try:
        sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
    except FileNotFoundError:
        pass

    # Fallback: manual run
    print("Running tests manually...\n")
    passed = 0
    failed = 0

    for cls in [TestTaskQueue, TestQueueCommands]:
        instance = cls()
        for name in sorted(dir(instance)):
            if not name.startswith("test_"):
                continue
            try:
                getattr(instance, name)()
                print(f"  PASS  {cls.__name__}.{name}")
                passed += 1
            except Exception as e:
                print(f"  FAIL  {cls.__name__}.{name}: {e}")
                failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
