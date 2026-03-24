import pathlib
import shutil
import tempfile
import time
import unittest

from workspace_loader import WorkspaceLoader, MAX_WORKSPACE_CHARS


class TestWorkspaceLoader(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.wl = WorkspaceLoader(workspace_root=self.tmpdir)
        self.root = pathlib.Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, rel_path: str, content: str) -> pathlib.Path:
        path = self.root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    # ------------------------------------------------------------------ #

    def test_get_core_context(self):
        self._write("AGENTS.md", "# Agents\nagent content")
        self._write("TOOLS.md", "# Tools\ntool content")
        self._write("SOUL.md", "# Soul\nsoul content")
        ctx = self.wl.get_core_context()
        self.assertIn("agent content", ctx)
        self.assertIn("tool content", ctx)
        self.assertIn("soul content", ctx)

    def test_get_core_context_missing_file(self):
        self._write("AGENTS.md", "# Agents\nonly agents")
        # TOOLS.md and SOUL.md intentionally absent
        ctx = self.wl.get_core_context()
        self.assertIn("only agents", ctx)
        self.assertNotIn("TOOLS.md", ctx)

    def test_get_identity(self):
        self._write("IDENTITY.md", (
            "# NEXUS Dev Assistant\n"
            "**Name:** Test Bot\n"
            "**Emoji:** 🤖\n"
            "**Role:** Testing role\n"
        ))
        identity = self.wl.get_identity()
        self.assertEqual(identity["name"], "Test Bot")
        self.assertEqual(identity["emoji"], "🤖")
        self.assertEqual(identity["role"], "Testing role")

    def test_get_identity_missing(self):
        # No IDENTITY.md — defaults returned
        identity = self.wl.get_identity()
        self.assertEqual(identity["name"], "Dev Assistant")
        self.assertEqual(identity["emoji"], "🔧")
        self.assertIn("development assistant", identity["role"])

    def test_find_skills_match(self):
        self._write("skills/deploy/SKILL.md", (
            "# Skill: Deploy\n\n"
            "## When to activate\n"
            'Task contains: "deploy", "contract"\n\n'
            "## Instructions\n- Do the deploy\n"
        ))
        matched = self.wl.find_skills("deploy the new smart contract")
        self.assertIn("deploy", matched)

    def test_find_skills_no_match(self):
        self._write("skills/deploy/SKILL.md", (
            "# Skill: Deploy\n\n"
            "## When to activate\n"
            'Task contains: "deploy", "contract"\n\n'
            "## Instructions\n- Do the deploy\n"
        ))
        matched = self.wl.find_skills("fix a typo in the readme")
        self.assertEqual(matched, [])

    def test_get_skill_context(self):
        self._write("skills/code-review/SKILL.md", (
            "# Skill: Code Review\n\n"
            "## When to activate\n"
            'Task contains: "review"\n\n'
            "## Instructions\n- Read files carefully\n"
        ))
        ctx = self.wl.get_skill_context(["code-review"])
        self.assertIn("Read files carefully", ctx)

    def test_build_system_prompt(self):
        self._write("AGENTS.md", "# Agents\nagent rules")
        self._write("TOOLS.md", "# Tools\ntool list")
        self._write("SOUL.md", "# Soul\npersonality")
        self._write("USER.md", "# User\noperator prefs")
        self._write("skills/security-audit/SKILL.md", (
            "# Skill: Security Audit\n\n"
            "## When to activate\n"
            'Task contains: "security", "audit"\n\n'
            "## Instructions\n- Check for secrets\n"
        ))
        prompt = self.wl.build_system_prompt("security audit of blockchain_logger.py")
        self.assertIn("agent rules", prompt)
        self.assertIn("operator prefs", prompt)
        self.assertIn("Check for secrets", prompt)
        self.assertIn("Active Skills", prompt)

    def test_truncation(self):
        big_content = "x" * (MAX_WORKSPACE_CHARS + 500)
        self._write("AGENTS.md", big_content)
        ctx = self.wl.get_core_context()
        self.assertIn("[... truncated ...]", ctx)
        self.assertLessEqual(len(ctx), MAX_WORKSPACE_CHARS + 50)

    def test_cache_invalidation(self):
        path = self._write("AGENTS.md", "original content")
        _ = self.wl.get_core_context()  # populate cache

        # Ensure mtime changes (some filesystems have 1s resolution)
        time.sleep(0.01)
        path.write_text("updated content")
        # Force mtime to differ by touching with a future timestamp
        new_mtime = path.stat().st_mtime + 1
        import os
        os.utime(path, (new_mtime, new_mtime))

        ctx = self.wl.get_core_context()
        self.assertIn("updated content", ctx)
        self.assertNotIn("original content", ctx)


if __name__ == "__main__":
    unittest.main()
