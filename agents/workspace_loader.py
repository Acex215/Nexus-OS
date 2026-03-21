import pathlib
import logging
import re
from typing import List, Dict

WORKSPACE_ROOT = pathlib.Path("/opt/nexus/workspace")
MAX_WORKSPACE_CHARS = 6000  # total workspace context budget
MAX_SKILL_CHARS = 1500      # per-skill budget


class WorkspaceLoader:
    def __init__(self, workspace_root: str = "/opt/nexus/workspace"):
        self.root = pathlib.Path(workspace_root)
        self.log = logging.getLogger("workspace_loader")
        self._cache: dict[str, str] = {}  # path → content cache
        self._cache_mtime: dict[str, float] = {}  # path → last modified time

    def _read_file(self, path: pathlib.Path) -> str:
        """Read a workspace file with caching. Re-reads if file modified."""
        key = str(path)
        try:
            mtime = path.stat().st_mtime
            if key in self._cache and self._cache_mtime.get(key) == mtime:
                return self._cache[key]
            content = path.read_text(errors="replace")
            self._cache[key] = content
            self._cache_mtime[key] = mtime
            return content
        except Exception as e:
            self.log.warning("Cannot read workspace file %s: %s", path, e)
            return ""

    def _truncate(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n\n[... truncated ...]"

    def get_core_context(self) -> str:
        """Load AGENTS.md + TOOLS.md + SOUL.md into a single context string."""
        parts = []
        for name in ["AGENTS.md", "TOOLS.md", "SOUL.md"]:
            path = self.root / name
            if path.exists():
                content = self._read_file(path)
                if content:
                    parts.append(f"## {name}\n{content}")
        combined = "\n\n".join(parts)
        return self._truncate(combined, MAX_WORKSPACE_CHARS)

    def get_identity(self) -> dict:
        """Load IDENTITY.md and parse key fields."""
        path = self.root / "IDENTITY.md"
        content = self._read_file(path) if path.exists() else ""
        identity = {"name": "Dev Assistant", "emoji": "🔧", "role": "development assistant"}
        for line in content.split("\n"):
            if line.startswith("**Name:**"):
                identity["name"] = line.split(":**", 1)[1].strip()
            elif line.startswith("**Emoji:**"):
                identity["emoji"] = line.split(":**", 1)[1].strip()
            elif line.startswith("**Role:**"):
                identity["role"] = line.split(":**", 1)[1].strip()
        return identity

    def get_user_context(self) -> str:
        """Load USER.md for operator preferences."""
        path = self.root / "USER.md"
        if path.exists():
            return self._read_file(path)
        return ""

    def find_skills(self, task_description: str) -> list[str]:
        """Find skills whose activation keywords match the task description.
        Returns list of skill directory names."""
        skills_dir = self.root / "skills"
        if not skills_dir.exists():
            return []

        desc_lower = task_description.lower()
        matched = []

        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            content = self._read_file(skill_file)
            # Parse "When to activate" section for keywords
            activate_match = re.search(
                r"(?:When to activate|Trigger|Keywords).*?:(.+?)(?:\n#|\n\n|\Z)",
                content, re.IGNORECASE | re.DOTALL
            )
            if activate_match:
                keywords_text = activate_match.group(1).lower()
                # Extract quoted keywords or comma-separated words
                keywords = re.findall(r'"([^"]+)"', keywords_text)
                if not keywords:
                    keywords = [k.strip().strip('"\'') for k in keywords_text.split(",")]
                if any(kw.strip() in desc_lower for kw in keywords if kw.strip()):
                    matched.append(skill_dir.name)

        return matched

    def get_skill_context(self, skill_names: list[str]) -> str:
        """Load and concatenate skill files for matched skills."""
        parts = []
        for name in skill_names:
            skill_file = self.root / "skills" / name / "SKILL.md"
            if skill_file.exists():
                content = self._read_file(skill_file)
                parts.append(self._truncate(content, MAX_SKILL_CHARS))
        return "\n\n".join(parts)

    def build_system_prompt(self, task_description: str = "") -> str:
        """Build the full system prompt from workspace files + matched skills.
        This is the main entry point used by dev_assistant.py."""
        sections = []

        # Core context (AGENTS.md + TOOLS.md + SOUL.md)
        core = self.get_core_context()
        if core:
            sections.append(core)

        # Matched skills
        if task_description:
            matched_skills = self.find_skills(task_description)
            if matched_skills:
                skill_ctx = self.get_skill_context(matched_skills)
                if skill_ctx:
                    sections.append(f"## Active Skills: {', '.join(matched_skills)}\n{skill_ctx}")

        # User preferences
        user_ctx = self.get_user_context()
        if user_ctx:
            sections.append(f"## Operator\n{user_ctx}")

        return "\n\n---\n\n".join(sections)
