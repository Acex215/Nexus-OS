#!/usr/bin/env python3
"""Unit tests for health_monitor.py, test_validator.py, and the git pre-commit hook.
Phase 3, Batch 2.

Run: python3 -m pytest test_phase3_batch2.py -v
Or:  python3 test_phase3_batch2.py
"""

import asyncio
import os
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Path / stub setup
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(__file__))

# Stub safety_config if not importable
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

from health_monitor import HealthMonitor
from test_validator import TestValidator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_mock_session(status=200, json_data=None, side_effect=None):
    """Return a mock aiohttp.ClientSession context manager.

    The mock supports both GET and POST via session.get() / session.post(),
    which each return an async context manager whose __aenter__ yields a
    response object.
    """
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_data or {})

    # Async context manager for the response
    resp_ctx = MagicMock()
    resp_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    resp_ctx.__aexit__ = AsyncMock(return_value=False)

    # Async context manager for the session
    mock_session = MagicMock()
    if side_effect:
        mock_session.get = MagicMock(side_effect=side_effect)
        mock_session.post = MagicMock(side_effect=side_effect)
    else:
        mock_session.get = MagicMock(return_value=resp_ctx)
        mock_session.post = MagicMock(return_value=resp_ctx)

    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)

    return session_ctx


# ---------------------------------------------------------------------------
# TestHealthMonitor
# ---------------------------------------------------------------------------

class TestHealthMonitor(unittest.TestCase):

    def _monitor(self):
        return HealthMonitor(
            llm_endpoints={
                "coordinator": "http://10.0.30.3:1234/v1/models",
                "coder": "http://10.0.30.2:1234/v1/models",
            }
        )

    # ── Disk ──────────────────────────────────────────────────────────────────

    def test_check_disk_sufficient(self):
        usage = MagicMock()
        usage.free = 50 * (1024 ** 3)  # 50 GB
        with patch("shutil.disk_usage", return_value=usage):
            result = run(self._monitor().check_disk())
        self.assertTrue(result["ok"])
        self.assertGreater(result["free_gb"], 2.0)

    def test_check_disk_insufficient(self):
        usage = MagicMock()
        usage.free = int(0.5 * (1024 ** 3))  # 0.5 GB
        with patch("shutil.disk_usage", return_value=usage):
            result = run(self._monitor().check_disk())
        self.assertFalse(result["ok"])
        self.assertLess(result["free_gb"], 2.0)

    # ── LLM ───────────────────────────────────────────────────────────────────

    def test_check_llm_success(self):
        session_ctx = _make_mock_session(status=200)
        with patch("aiohttp.ClientSession", return_value=session_ctx):
            result = run(self._monitor().check_llm("coordinator", "http://fake/v1/models"))
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["latency_ms"], 0)

    def test_check_llm_timeout(self):
        import aiohttp as _aiohttp
        session_ctx = _make_mock_session(side_effect=asyncio.TimeoutError())
        with patch("aiohttp.ClientSession", return_value=session_ctx):
            result = run(self._monitor().check_llm("coordinator", "http://fake/v1/models"))
        self.assertFalse(result["ok"])
        self.assertIn("imed out", result["message"])

    def test_check_llm_connection_refused(self):
        import aiohttp as _aiohttp
        session_ctx = _make_mock_session(
            side_effect=_aiohttp.ClientConnectionError("Connection refused")
        )
        with patch("aiohttp.ClientSession", return_value=session_ctx):
            result = run(self._monitor().check_llm("coordinator", "http://fake/v1/models"))
        self.assertFalse(result["ok"])
        self.assertIn("Connection refused", result["message"])

    # ── Blockchain ────────────────────────────────────────────────────────────

    def test_check_blockchain_success(self):
        session_ctx = _make_mock_session(
            status=200,
            json_data={"jsonrpc": "2.0", "id": 1, "result": "0x1F5A1"},
        )
        with patch("aiohttp.ClientSession", return_value=session_ctx):
            result = run(self._monitor().check_blockchain())
        self.assertTrue(result["ok"])
        self.assertEqual(result["block_number"], 128417)

    def test_check_blockchain_unreachable(self):
        import aiohttp as _aiohttp
        session_ctx = _make_mock_session(
            side_effect=_aiohttp.ClientConnectionError("Connection refused")
        )
        with patch("aiohttp.ClientSession", return_value=session_ctx):
            result = run(self._monitor().check_blockchain())
        self.assertFalse(result["ok"])

    # ── check_all ─────────────────────────────────────────────────────────────

    def test_check_all_healthy(self):
        monitor = self._monitor()
        ok_disk = {"ok": True, "free_gb": 50.0, "message": "50.0 GB free"}
        ok_llm = {"ok": True, "latency_ms": 100, "message": "100ms"}
        ok_chain = {"ok": True, "block_number": 999, "message": "block #999"}

        monitor.check_disk = AsyncMock(return_value=ok_disk)
        monitor.check_llm = AsyncMock(return_value=ok_llm)
        monitor.check_blockchain = AsyncMock(return_value=ok_chain)

        result = run(monitor.check_all())
        self.assertTrue(result["healthy"])
        self.assertIn("timestamp", result)

    def test_check_all_unhealthy(self):
        monitor = self._monitor()
        ok_disk = {"ok": True, "free_gb": 50.0, "message": "50.0 GB free"}
        fail_llm = {"ok": False, "latency_ms": 0, "message": "Connection refused"}
        ok_chain = {"ok": True, "block_number": 999, "message": "block #999"}

        monitor.check_disk = AsyncMock(return_value=ok_disk)
        monitor.check_llm = AsyncMock(return_value=fail_llm)
        monitor.check_blockchain = AsyncMock(return_value=ok_chain)

        result = run(monitor.check_all())
        self.assertFalse(result["healthy"])

    # ── format_report ─────────────────────────────────────────────────────────

    def test_format_report_contains_emojis(self):
        result = {
            "healthy": False,
            "checks": {
                "disk": {"ok": True, "free_gb": 45.2, "message": "45.2 GB free"},
                "llm_coordinator": {"ok": True, "latency_ms": 234, "message": "234ms"},
                "llm_coder": {"ok": False, "latency_ms": 0, "message": "Connection refused"},
                "blockchain": {"ok": True, "block_number": 128445, "message": "block #128,445"},
            },
            "timestamp": "2026-03-18T00:00:00+00:00",
        }
        report = self._monitor().format_report(result)
        self.assertIn("✅", report)
        self.assertIn("❌", report)
        self.assertIn("Disk", report)
        self.assertIn("Blockchain", report)
        self.assertIn("unhealthy", report)


# ---------------------------------------------------------------------------
# TestTestValidator
# ---------------------------------------------------------------------------

class TestTestValidator(unittest.TestCase):

    def setUp(self):
        self.validator = TestValidator()

    def test_find_tests_standard_pattern(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Create test_foo.py next to foo.py
            test_path = os.path.join(tmp, "test_foo.py")
            open(test_path, "w").close()

            result = self.validator.find_tests([os.path.join(tmp, "foo.py")])
            self.assertIn(test_path, result)

    def test_find_tests_no_tests_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.validator.find_tests([os.path.join(tmp, "bar.py")])
            self.assertEqual(result, [])

    def test_find_tests_test_file_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            test_path = os.path.join(tmp, "test_foo.py")
            open(test_path, "w").close()

            result = self.validator.find_tests([test_path])
            self.assertIn(test_path, result)

    def test_find_tests_nested_tests_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = os.path.join(tmp, "tests")
            os.makedirs(tests_dir)
            nested_test = os.path.join(tests_dir, "test_baz.py")
            open(nested_test, "w").close()

            result = self.validator.find_tests([os.path.join(tmp, "baz.py")])
            self.assertIn(nested_test, result)

    def test_run_tests_no_files(self):
        result = run(self.validator.run_tests([]))
        self.assertTrue(result["passed"])
        self.assertEqual(result["output"], "no tests found")
        self.assertEqual(result["test_files"], [])

    def test_validate_integration(self):
        """validate() calls find_tests then run_tests and returns the result."""
        with tempfile.TemporaryDirectory() as tmp:
            # Write a trivial passing test
            test_path = os.path.join(tmp, "test_dummy.py")
            with open(test_path, "w") as f:
                f.write("def test_pass(): assert True\n")

            source_path = os.path.join(tmp, "dummy.py")
            open(source_path, "w").close()

            # Patch find_tests so it returns our known test file
            original_find = self.validator.find_tests
            self.validator.find_tests = lambda files: [test_path]

            result = run(self.validator.validate([source_path]))

            self.validator.find_tests = original_find

        self.assertIn("passed", result)
        self.assertIn("test_files", result)
        self.assertIn(test_path, result["test_files"])


# ---------------------------------------------------------------------------
# TestPreCommitHook
# ---------------------------------------------------------------------------

HOOK_PATH = "/opt/nexus/.git-hooks/pre-commit"


class TestPreCommitHook(unittest.TestCase):

    def _run_hook(self, staged_files: list[str]) -> tuple[int, str]:
        """Run the pre-commit hook in a temp git repo with the given staged files.

        We use a real git repo so ``git diff --cached --name-only`` returns the
        expected output, but we also directly set GIT_DIR so the hook sees our
        fake staging area.  The simplest approach: patch the hook's git call by
        running it via bash with a git wrapper on PATH that echoes our file list.
        """
        with tempfile.TemporaryDirectory() as tmp:
            # Create a tiny wrapper that replaces "git diff --cached ..." output
            fake_git = os.path.join(tmp, "git")
            staged_output = "\n".join(staged_files)
            with open(fake_git, "w") as f:
                f.write("#!/bin/bash\n")
                f.write(f'echo "{staged_output}"\n')
            os.chmod(fake_git, 0o755)

            env = os.environ.copy()
            env["PATH"] = tmp + ":" + env["PATH"]

            proc = subprocess.run(
                ["bash", HOOK_PATH],
                capture_output=True,
                text=True,
                env=env,
            )
            return proc.returncode, proc.stdout + proc.stderr

    def test_hook_exists_and_executable(self):
        self.assertTrue(os.path.isfile(HOOK_PATH), f"Hook not found: {HOOK_PATH}")
        mode = os.stat(HOOK_PATH).st_mode
        self.assertTrue(
            mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH),
            "Hook is not executable",
        )

    def test_hook_blocks_env_file(self):
        rc, output = self._run_hook(["config/.env"])
        self.assertEqual(rc, 1, f"Expected exit 1 for .env file, got {rc}\n{output}")
        self.assertIn("Protected path violation", output)

    def test_hook_allows_normal_file(self):
        rc, output = self._run_hook(["agents/foo.py"])
        self.assertEqual(rc, 0, f"Expected exit 0 for normal file, got {rc}\n{output}")


# ---------------------------------------------------------------------------
# Manual runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import subprocess as _sp

    try:
        sys.exit(_sp.call([sys.executable, "-m", "pytest", __file__, "-v"]))
    except FileNotFoundError:
        pass

    print("Running tests manually...\n")
    passed = 0
    failed = 0

    for cls in [TestHealthMonitor, TestTestValidator, TestPreCommitHook]:
        for name in sorted(dir(cls)):
            if not name.startswith("test_"):
                continue
            instance = cls()
            if hasattr(instance, "setUp"):
                instance.setUp()
            try:
                getattr(instance, name)()
                print(f"  PASS  {cls.__name__}.{name}")
                passed += 1
            except Exception as exc:
                print(f"  FAIL  {cls.__name__}.{name}: {exc}")
                failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
