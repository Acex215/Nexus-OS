#!/usr/bin/env python3
"""Unit tests for safety_gates.py — Phase 3, Batch 1.

Tests run WITHOUT discord installed; all discord-dependent paths are mocked.

Run: python3 -m pytest test_phase3_batch1.py -v
Or:  python3 test_phase3_batch1.py
"""

import asyncio
import sys
import os
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, call

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(__file__))

# ---------------------------------------------------------------------------
# Stub out discord before importing safety_gates so the TYPE_CHECKING guard
# doesn't matter and any accidental runtime import also won't explode.
# ---------------------------------------------------------------------------
if "discord" not in sys.modules:
    sys.modules["discord"] = types.ModuleType("discord")

# Provide a minimal safety_config stub so safety_gates imports cleanly even
# if the file isn't on the path (tests are run from arbitrary directories).
import importlib
try:
    import safety_config  # noqa: F401
except ModuleNotFoundError:
    _stub = types.ModuleType("safety_config")
    _stub.MEDIUM_RISK_TIMEOUT = 60
    _stub.HIGH_RISK_TIMEOUT = 0
    _stub.AUTO_APPROVE_LOW = True
    _stub.MAX_RETRIES = 2
    _stub.DISK_MIN_FREE_GB = 2.0
    _stub.LLM_HEALTH_TIMEOUT = 10
    sys.modules["safety_config"] = _stub

from safety_gates import SafetyGate, ScopeEnforcer, RetryPolicy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    """Run a coroutine in a fresh event loop (works on Python 3.9+)."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# TestSafetyGateClassifyRisk
# ---------------------------------------------------------------------------

class TestSafetyGateClassifyRisk(unittest.TestCase):

    def setUp(self):
        self.gate = SafetyGate()

    def test_existing_risk_preserved(self):
        task = {"risk": "high", "description": "add a comment"}
        self.assertEqual(self.gate.classify_risk(task), "high")

    def test_infer_high_from_deploy(self):
        task = {"description": "deploy contract to mainnet"}
        self.assertEqual(self.gate.classify_risk(task), "high")

    def test_infer_high_from_delete(self):
        task = {"description": "delete old migrations from the database"}
        self.assertEqual(self.gate.classify_risk(task), "high")

    def test_infer_medium_from_refactor(self):
        task = {"description": "refactor agent registry into separate module"}
        self.assertEqual(self.gate.classify_risk(task), "medium")

    def test_infer_medium_from_rewrite(self):
        task = {"description": "rewrite the LLM router to support streaming"}
        self.assertEqual(self.gate.classify_risk(task), "medium")

    def test_infer_low_default(self):
        task = {"description": "add health check endpoint to the API"}
        self.assertEqual(self.gate.classify_risk(task), "low")

    def test_empty_risk_field(self):
        task = {"risk": "", "description": "refactor agent registry"}
        self.assertEqual(self.gate.classify_risk(task), "medium")

    def test_none_risk_field(self):
        task = {"risk": None, "description": "deploy contract"}
        self.assertEqual(self.gate.classify_risk(task), "high")


# ---------------------------------------------------------------------------
# TestScopeEnforcer
# ---------------------------------------------------------------------------

class TestScopeEnforcer(unittest.TestCase):

    def setUp(self):
        self.enforcer = ScopeEnforcer()

    def test_empty_affected_files_passes(self):
        task = {"affected_files": []}
        ok, reason = self.enforcer.check_scope(task, "/opt/nexus/agents/foo.py")
        self.assertTrue(ok)
        self.assertIn("no scope declared", reason)

    def test_no_affected_files_key_passes(self):
        task = {}
        ok, reason = self.enforcer.check_scope(task, "/opt/nexus/agents/foo.py")
        self.assertTrue(ok)
        self.assertIn("no scope declared", reason)

    def test_exact_match_passes(self):
        task = {"affected_files": ["/opt/nexus/agents/foo.py"]}
        ok, reason = self.enforcer.check_scope(task, "/opt/nexus/agents/foo.py")
        self.assertTrue(ok)
        self.assertIn("in scope", reason)

    def test_exact_match_fails(self):
        task = {"affected_files": ["/opt/nexus/agents/foo.py"]}
        ok, reason = self.enforcer.check_scope(task, "/opt/nexus/agents/bar.py")
        self.assertFalse(ok)
        self.assertIn("out of scope", reason)

    def test_directory_match_passes(self):
        task = {"affected_files": ["/opt/nexus/agents/"]}
        ok, reason = self.enforcer.check_scope(task, "/opt/nexus/agents/foo.py")
        self.assertTrue(ok)
        self.assertIn("in scope", reason)

    def test_directory_match_fails(self):
        task = {"affected_files": ["/opt/nexus/agents/"]}
        ok, reason = self.enforcer.check_scope(task, "/opt/nexus/contracts/foo.sol")
        self.assertFalse(ok)
        self.assertIn("out of scope", reason)

    def test_multiple_scopes(self):
        task = {"affected_files": ["/opt/nexus/agents/foo.py", "/opt/nexus/docs/"]}
        ok, reason = self.enforcer.check_scope(task, "/opt/nexus/docs/README.md")
        self.assertTrue(ok)
        self.assertIn("in scope", reason)


# ---------------------------------------------------------------------------
# TestRetryPolicy
# ---------------------------------------------------------------------------

class TestRetryPolicy(unittest.TestCase):

    def setUp(self):
        self.policy = RetryPolicy()

    def test_success_no_retry(self):
        execute_fn = AsyncMock(return_value={"success": True, "error": None})
        task = {"description": "do something"}
        result = run(self.policy.execute_with_retry(execute_fn, task))
        self.assertTrue(result["success"])
        execute_fn.assert_awaited_once()

    def test_retry_on_failure(self):
        execute_fn = AsyncMock(side_effect=[
            {"success": False, "error": "oops"},
            {"success": False, "error": "still bad"},
            {"success": True,  "error": None},
        ])
        task = {"description": "do something"}
        result = run(self.policy.execute_with_retry(execute_fn, task, max_retries=2))
        self.assertTrue(result["success"])
        self.assertEqual(execute_fn.await_count, 3)

    def test_max_retries_exhausted(self):
        execute_fn = AsyncMock(return_value={"success": False, "error": "always fails"})
        task = {"description": "do something"}
        result = run(self.policy.execute_with_retry(execute_fn, task, max_retries=2))
        self.assertFalse(result["success"])
        self.assertEqual(execute_fn.await_count, 3)  # 1 original + 2 retries

    def test_retry_appends_error_context(self):
        received_descriptions = []

        async def capture_fn(t):
            received_descriptions.append(t["description"])
            if len(received_descriptions) == 1:
                return {"success": False, "error": "syntax error"}
            return {"success": True, "error": None}

        task = {"description": "original task description"}
        run(self.policy.execute_with_retry(capture_fn, task, max_retries=2))

        self.assertEqual(len(received_descriptions), 2)
        self.assertEqual(received_descriptions[0], "original task description")
        self.assertIn("[RETRY 1/2]", received_descriptions[1])
        self.assertIn("syntax error", received_descriptions[1])

    def test_original_description_restored(self):
        original = "original task description"
        task = {"description": original}

        execute_fn = AsyncMock(side_effect=[
            {"success": False, "error": "whoops"},
            {"success": True,  "error": None},
        ])
        run(self.policy.execute_with_retry(execute_fn, task, max_retries=2))

        self.assertEqual(task["description"], original)

    def test_custom_max_retries(self):
        execute_fn = AsyncMock(return_value={"success": False, "error": "nope"})
        task = {"description": "do something"}
        run(self.policy.execute_with_retry(execute_fn, task, max_retries=1))
        self.assertEqual(execute_fn.await_count, 2)  # 1 original + 1 retry


# ---------------------------------------------------------------------------
# Manual runner (fallback when pytest is unavailable)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import subprocess

    try:
        sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
    except FileNotFoundError:
        pass

    print("Running tests manually...\n")
    passed = 0
    failed = 0

    test_classes = [
        TestSafetyGateClassifyRisk,
        TestScopeEnforcer,
        TestRetryPolicy,
    ]

    for cls in test_classes:
        instance = cls()
        if hasattr(instance, "setUp"):
            instance.setUp()
        for name in sorted(dir(instance)):
            if not name.startswith("test_"):
                continue
            # Re-create instance so setUp is fresh for each test
            fresh = cls()
            if hasattr(fresh, "setUp"):
                fresh.setUp()
            try:
                getattr(fresh, name)()
                print(f"  PASS  {cls.__name__}.{name}")
                passed += 1
            except Exception as e:
                print(f"  FAIL  {cls.__name__}.{name}: {e}")
                failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
