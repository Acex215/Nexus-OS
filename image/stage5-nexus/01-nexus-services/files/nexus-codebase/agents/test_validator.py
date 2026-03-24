"""
test_validator.py — Post-execution test validation gate for the NEXUS OS dev assistant.

After a task completes successfully, finds relevant test files and runs them via pytest.
If tests fail, the caller should trigger rollback.

Integration point (implemented in autonomous_loop.py):
    # After a successful execute_fn call:
    # validator = TestValidator()
    # test_result = await validator.validate(modified_files)
    # if not test_result["passed"]:
    #     # trigger rollback
    #     queue.update_status(task_id, "failed", error=f"Tests failed: {test_result['output'][:200]}")

This module is stateless — create a fresh instance per use.
"""

import asyncio
import logging
import os
import sys
import time

log = logging.getLogger("test_validator")

_MAX_OUTPUT = 2000  # chars to retain from pytest stdout+stderr


class TestValidator:
    """Discover and run tests for a set of modified files."""

    # -------------------------------------------------------------------------
    # Discovery
    # -------------------------------------------------------------------------

    def find_tests(self, modified_files: list[str]) -> list[str]:
        """Return existing test file paths relevant to *modified_files*.

        Discovery rules (checked in order for each file):
        1. If the file is itself a test file (basename matches ``test_*.py``),
           include it directly.
        2. For ``/some/dir/foo.py`` look for ``/some/dir/test_foo.py``.
        3. For ``/some/dir/foo.py`` look for ``/some/dir/tests/test_foo.py``.

        Only paths that exist on disk are returned. Duplicates are removed
        while preserving first-seen order.

        Args:
            modified_files: List of absolute (or relative) file paths that
                            were modified by the task.

        Returns:
            Deduplicated list of existing test file paths.
        """
        seen: set[str] = set()
        result: list[str] = []

        for fpath in modified_files:
            dirname = os.path.dirname(fpath)
            basename = os.path.basename(fpath)

            candidates: list[str] = []

            # Rule 1: file is itself a test file
            if basename.startswith("test_") and basename.endswith(".py"):
                candidates.append(fpath)

            # Rule 2 & 3 only apply to non-test source files
            if basename.endswith(".py") and not basename.startswith("test_"):
                stem = basename[:-3]  # strip .py
                candidates.append(os.path.join(dirname, f"test_{stem}.py"))
                candidates.append(os.path.join(dirname, "tests", f"test_{stem}.py"))

            for candidate in candidates:
                norm = os.path.normpath(candidate)
                if norm in seen:
                    continue
                if os.path.isfile(norm):
                    seen.add(norm)
                    result.append(norm)
                    log.debug("find_tests: found %s for %s", norm, fpath)
                else:
                    log.debug("find_tests: no test at %s", norm)

        log.info(
            "find_tests: %d modified file(s) → %d test file(s) found",
            len(modified_files),
            len(result),
        )
        return result

    # -------------------------------------------------------------------------
    # Execution
    # -------------------------------------------------------------------------

    async def run_tests(self, test_files: list[str], timeout: int = 120) -> dict:
        """Run *test_files* under pytest and return a result dict.

        Args:
            test_files: Paths returned by :meth:`find_tests`.
            timeout:    Seconds before the subprocess is killed (default 120).

        Returns:
            {
                "passed":           bool,
                "test_files":       list[str],
                "output":           str,   # stdout+stderr, truncated to 2000 chars
                "duration_seconds": float,
                "error":            str|None,
            }
        """
        if not test_files:
            log.info("run_tests: no test files — skipping")
            return {
                "passed": True,
                "test_files": [],
                "output": "no tests found",
                "duration_seconds": 0.0,
                "error": None,
            }

        cmd = [sys.executable, "-m", "pytest"] + test_files + ["-v", "--tb=short"]
        log.info("run_tests: %s", " ".join(cmd))

        start = time.monotonic()
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                stdout_bytes, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                duration = round(time.monotonic() - start, 2)
                log.warning("run_tests: timed out after %ds", timeout)
                return {
                    "passed": False,
                    "test_files": test_files,
                    "output": f"[pytest killed after {timeout}s timeout]",
                    "duration_seconds": duration,
                    "error": "test timeout",
                }

            duration = round(time.monotonic() - start, 2)
            output = stdout_bytes.decode(errors="replace")
            output_truncated = output[-_MAX_OUTPUT:] if len(output) > _MAX_OUTPUT else output
            passed = proc.returncode == 0

            log.info(
                "run_tests: returncode=%d duration=%.1fs files=%s",
                proc.returncode,
                duration,
                test_files,
            )
            return {
                "passed": passed,
                "test_files": test_files,
                "output": output_truncated,
                "duration_seconds": duration,
                "error": None,
            }

        except Exception as exc:
            duration = round(time.monotonic() - start, 2)
            msg = str(exc)
            log.error("run_tests: pytest crashed: %s", msg)
            if proc is not None:
                try:
                    proc.kill()
                    await proc.communicate()
                except Exception:
                    pass
            return {
                "passed": False,
                "test_files": test_files,
                "output": "",
                "duration_seconds": duration,
                "error": msg,
            }

    # -------------------------------------------------------------------------
    # Convenience
    # -------------------------------------------------------------------------

    async def validate(self, modified_files: list[str]) -> dict:
        """Discover and run tests for *modified_files* in one call.

        Args:
            modified_files: List of file paths modified by the completed task.

        Returns:
            The result dict from :meth:`run_tests`.
        """
        test_files = self.find_tests(modified_files)
        return await self.run_tests(test_files)
