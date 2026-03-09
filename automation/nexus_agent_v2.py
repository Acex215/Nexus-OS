"""
NEXUS OS Agent v2 — Autonomous 24/7 Development Agent
8-gate pipeline with rollback capability.
Replaces dev_orchestrator.py.
"""

import os
import sys
import yaml
import json
import subprocess
import hashlib
import shutil
import time
import logging
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum

# ── Configuration ──────────────────────────────────────────────────────────────

NEXUS_ROOT = Path("/opt/nexus")
COMPILED_DB = NEXUS_ROOT / "docs" / "compiled-db"
TASK_QUEUE = NEXUS_ROOT / "automation" / "task_queue.yaml"
AUDIT_LOG = NEXUS_ROOT / "automation" / "logs" / "agent_v2_audit.jsonl"
WORK_BRANCH_PREFIX = "agent/v2/"

# LLM endpoint configuration — tiered (strongest first)
LLM_TIERS = [
    {
        "name": "tier1-thinkpad",
        "url": "http://10.0.30.2:1234/v1/chat/completions",
        "model": "qwen3.5-35b",
        "timeout": 300,       # 5min: large file rewrites on 35B model can be slow
        "max_tokens": 8192,
    },
    {
        "name": "tier2-nexus-ai2",
        "url": "http://10.0.20.6:11434/v1/chat/completions",
        "model": "qwen2.5-coder:7b",
        "timeout": 120,
        "max_tokens": 4096,
    },
    {
        "name": "tier3-nexus-ai",
        "url": "http://10.0.20.4:8090/v1/chat/completions",
        "model": "local/SmolLM2-1.7B",
        "timeout": 30,
        "max_tokens": 1024,   # SmolLM2 context window limit
    },
]

# ── Logging setup ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(NEXUS_ROOT / "automation" / "logs" / "agent_v2.log"),
    ],
)

# ── Enums & Data Classes ───────────────────────────────────────────────────────


class TaskStatus(Enum):
    QUEUED = "queued"
    SCOPING = "scoping"
    CONTEXT_LOADING = "context_loading"
    PROBING = "probing"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    UPDATING_DB = "updating_db"
    COMMITTING = "committing"
    COMPLETED = "completed"
    HALTED = "halted"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


@dataclass
class TaskState:
    task_id: str
    description: str
    status: TaskStatus = TaskStatus.QUEUED
    gate_results: Dict[str, Any] = field(default_factory=dict)
    affected_components: List[str] = field(default_factory=list)
    affected_files: List[str] = field(default_factory=list)
    plan: Optional[Dict] = None
    branch_name: Optional[str] = None
    backup_stash: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    llm_tier_used: Optional[str] = None


# ── LLM Router ────────────────────────────────────────────────────────────────


class LLMRouter:
    """Try LLM tiers in order. Strongest available model wins."""

    def __init__(self):
        self.available_tiers: List[Dict] = []
        self._check_tiers()

    def _check_tiers(self):
        """Probe each tier's health endpoint."""
        import httpx

        self.available_tiers = []
        for tier in LLM_TIERS:
            health_url = tier["url"].rsplit("/v1/", 1)[0] + "/health"
            try:
                resp = httpx.get(health_url, timeout=5)
                if resp.status_code == 200:
                    self.available_tiers.append(tier)
                    continue
            except Exception:
                pass
            # Fallback: /v1/models
            try:
                models_url = tier["url"].rsplit("/chat/completions", 1)[0] + "/models"
                resp = httpx.get(models_url, timeout=5)
                if resp.status_code == 200:
                    self.available_tiers.append(tier)
            except Exception:
                pass

    async def complete(
        self,
        messages: List[Dict],
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> Tuple[str, str]:
        """Send completion to best available tier. Returns (response_text, tier_name)."""
        import httpx

        if not self.available_tiers:
            self._check_tiers()
        if not self.available_tiers:
            raise RuntimeError("No LLM tiers available")

        for tier in self.available_tiers:
            try:
                # Honour per-tier context window limits
                effective_max_tokens = min(max_tokens, tier.get("max_tokens", max_tokens))
                async with httpx.AsyncClient(timeout=tier["timeout"]) as client:
                    resp = await client.post(
                        tier["url"],
                        json={
                            "model": tier["model"],
                            "messages": messages,
                            "max_tokens": effective_max_tokens,
                            "temperature": temperature,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    text = data["choices"][0]["message"]["content"]
                    return text, tier["name"]
            except Exception as e:
                logging.getLogger("llm-router").warning("Tier %s failed: %s", tier["name"], e)
                continue

        raise RuntimeError("All LLM tiers exhausted")


# ── Compiled Database Reader ───────────────────────────────────────────────────


class CompiledDB:
    """Read-only interface to the 6-registry YAML database."""

    def __init__(self, db_path: Path = COMPILED_DB):
        self.db_path = db_path
        self._cache: Dict[str, Any] = {}

    def _load(self, name: str) -> Any:
        if name not in self._cache:
            path = self.db_path / f"{name}.yaml"
            if not path.exists():
                raise FileNotFoundError(f"Compiled DB missing: {path}")
            with open(path) as f:
                self._cache[name] = yaml.safe_load(f)
        return self._cache[name]

    def get_component(self, component_id: str) -> Optional[Dict]:
        for comp in self._load("components").get("components", []):
            if comp["id"] == component_id:
                return comp
        return None

    def get_files_for_component(self, component_id: str) -> List[str]:
        comp = self.get_component(component_id)
        return comp.get("files", []) if comp else []

    def get_gaps_for_component(self, component_id: str) -> List[Dict]:
        gaps = self._load("gaps").get("gaps", [])
        return [g for g in gaps if component_id in g.get("affected_components", [])]

    def get_interfaces_for_component(self, component_id: str) -> List[Dict]:
        interfaces = self._load("interfaces").get("interfaces", [])
        return [
            i
            for i in interfaces
            if component_id in (i.get("from", ""), i.get("to", ""))
        ]

    def get_dependencies(self, component_id: str) -> Optional[Dict]:
        for dep in self._load("dependencies").get("dependencies", []):
            if dep["component"] == component_id:
                return dep
        return None

    def get_file_entry(self, file_path: str) -> Optional[Dict]:
        for f in self._load("code_index").get("files", []):
            if f["path"] == file_path:
                return f
        return None

    def all_component_ids(self) -> List[str]:
        return [c["id"] for c in self._load("components").get("components", [])]

    def invalidate_cache(self):
        self._cache.clear()


# ── Git Manager ───────────────────────────────────────────────────────────────


class GitManager:
    """Handles branching, backup, rollback, and commits."""

    def __init__(self, repo_path: Path = NEXUS_ROOT):
        self.repo = repo_path

    def _run(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(self.repo)] + list(args),
            capture_output=True,
            text=True,
            timeout=30,
        )

    def current_branch(self) -> str:
        result = self._run("branch", "--show-current")
        return result.stdout.strip()

    def is_clean(self) -> bool:
        result = self._run("status", "--porcelain")
        lines = []
        for l in result.stdout.strip().split("\n"):
            if not l:
                continue
            if l.startswith("??"):
                continue  # untracked — ignore
            path = l[3:].strip()
            if "__pycache__" in path or path.endswith(".pyc"):
                continue  # ignore bytecode drift
            # Ignore submodules: git status shows them as directories
            abs_path = self.repo / path
            if abs_path.is_dir() and not abs_path.is_symlink():
                continue  # directory entry = submodule gitlink, skip
            lines.append(l)
        return len(lines) == 0

    def create_work_branch(self, task_id: str) -> str:
        branch = f"{WORK_BRANCH_PREFIX}{task_id}"
        self._run("checkout", "-b", branch)
        return branch

    def stash_backup(self, task_id: str) -> Optional[str]:
        """Create a stash backup before any modifications."""
        result = self._run("stash", "push", "-m", f"agent-v2-backup-{task_id}")
        if "No local changes" in result.stdout:
            return None
        return f"agent-v2-backup-{task_id}"

    def rollback(self, branch_name: str):
        """Hard rollback: delete the work branch and return to main."""
        self._run("checkout", "main")
        self._run("branch", "-D", branch_name)

    def commit(self, message: str, files: List[str]):
        for f in files:
            self._run("add", f)
        self._run("commit", "-m", message)

    def diff_stat(self) -> str:
        result = self._run("diff", "--cached", "--stat")
        return result.stdout.strip()

    def diff_full(self) -> str:
        result = self._run("diff", "--cached")
        return result.stdout.strip()

    def return_to_main(self):
        self._run("checkout", "main")


# ── Verification Engine ───────────────────────────────────────────────────────


class VerificationEngine:
    """Post-execution checks: syntax, imports, tests, diff review."""

    def syntax_check(self, file_path: str) -> Tuple[bool, str]:
        """Run py_compile on a Python file."""
        if not file_path.endswith(".py"):
            return True, "Not a Python file — skip"
        result = subprocess.run(
            ["python3", "-m", "py_compile", file_path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode == 0, result.stderr.strip()

    def import_check(self, file_path: str) -> Tuple[bool, str]:
        """Try importing a module to verify it loads."""
        if not file_path.endswith(".py"):
            return True, "Not a Python file — skip"

        rel = os.path.relpath(file_path, str(NEXUS_ROOT))
        module = rel.replace("/", ".").replace(".py", "")

        result = subprocess.run(
            [
                "python3",
                "-c",
                (
                    f"import sys; "
                    f"sys.path.insert(0, '{NEXUS_ROOT}'); "
                    f"sys.path.insert(0, '{NEXUS_ROOT}/agents'); "
                    f"import importlib; importlib.import_module('{module}')"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(NEXUS_ROOT),
        )
        return result.returncode == 0, result.stderr.strip()[:500]

    def run_tests(self, component_id: str) -> Tuple[bool, str]:
        """Run any tests associated with a component."""
        test_files = []
        for f in Path(NEXUS_ROOT).rglob("test_*.py"):
            stem = f.stem
            if (
                component_id.replace("-", "_") in stem
                or component_id.replace("-", "") in stem
            ):
                test_files.append(str(f))

        if not test_files:
            return True, "No tests found for component"

        results = []
        all_passed = True
        for tf in test_files:
            result = subprocess.run(
                ["python3", "-m", "pytest", tf, "-x", "--tb=short", "-q"],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(NEXUS_ROOT),
            )
            passed = result.returncode == 0
            if not passed:
                all_passed = False
            results.append(
                f"{tf}: {'PASS' if passed else 'FAIL'}\n{result.stdout[-500:]}"
            )

        return all_passed, "\n".join(results)

    def file_exists(self, path: str) -> bool:
        return os.path.exists(path)

    def file_matches_db(self, path: str, db: CompiledDB) -> Tuple[bool, str]:
        """Check if a file on disk matches its code_index entry."""
        entry = db.get_file_entry(path)
        if entry is None:
            return False, f"File {path} not in code_index.yaml"
        if not os.path.exists(path):
            return False, f"File {path} in code_index but missing from disk"
        actual_lines = sum(1 for _ in open(path))
        expected_lines = entry.get("lines", 0)
        if abs(actual_lines - expected_lines) > max(10, expected_lines * 0.2):
            return (
                False,
                f"Line count drift: expected ~{expected_lines}, got {actual_lines}",
            )
        return True, "OK"


# ── Helper ────────────────────────────────────────────────────────────────────


def _extract_json(text: str) -> str:
    """Extract the first JSON object or array from a text response."""
    # Try raw parse first
    stripped = text.strip()
    try:
        json.loads(stripped)
        return stripped
    except json.JSONDecodeError:
        pass

    # Try markdown code fences
    for fence in ("```json", "```"):
        if fence in stripped:
            start = stripped.find(fence) + len(fence)
            end = stripped.find("```", start)
            if end != -1:
                candidate = stripped[start:end].strip()
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    pass

    # Brace-scan fallback
    depth = 0
    start_idx = None
    for i, ch in enumerate(stripped):
        if ch in ("{", "[") and start_idx is None:
            start_idx = i
        if ch in ("{", "["):
            depth += 1
        elif ch in ("}", "]"):
            depth -= 1
            if depth == 0 and start_idx is not None:
                candidate = stripped[start_idx : i + 1]
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    break

    raise ValueError(f"No valid JSON found in response: {text[:200]}")


# ── The 8-Gate Pipeline ───────────────────────────────────────────────────────


class AgentPipeline:
    """The core 8-gate execution pipeline."""

    def __init__(self):
        self.db = CompiledDB()
        self.git = GitManager()
        self.verify = VerificationEngine()
        self.llm = LLMRouter()
        self.log = logging.getLogger("agent-v2")

    # ── Top-level runner ──────────────────────────────────────────

    async def execute_task(self, task: TaskState) -> TaskState:
        """Run a task through all 8 gates. Returns final task state."""
        task.started_at = datetime.now(timezone.utc).isoformat()

        gates = [
            ("G1:SCOPE", self._gate_scope),
            ("G2:CONTEXT", self._gate_context),
            ("G3:PROBE", self._gate_probe),
            ("G4:PLAN", self._gate_plan),
            ("G5:EXECUTE", self._gate_execute),
            ("G6:VERIFY", self._gate_verify),
            ("G7:UPDATE_DB", self._gate_update_db),
            ("G8:COMMIT", self._gate_commit),
        ]

        for gate_name, gate_fn in gates:
            self.log.info("=== %s === [%s]", gate_name, task.task_id)
            try:
                passed, result = await gate_fn(task)
                task.gate_results[gate_name] = {"passed": passed, "result": result}

                if not passed:
                    task.status = TaskStatus.HALTED
                    task.error = f"Halted at {gate_name}: {result}"
                    self.log.warning("HALT at %s: %s", gate_name, result)

                    # Rollback only if we already created a branch (G5+)
                    pre_branch_gates = {"G1:SCOPE", "G2:CONTEXT", "G3:PROBE", "G4:PLAN"}
                    if task.branch_name and gate_name not in pre_branch_gates:
                        self.git.rollback(task.branch_name)
                        task.status = TaskStatus.ROLLED_BACK
                        self.log.info("Rolled back branch %s", task.branch_name)

                    break
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error = f"Exception in {gate_name}: {str(e)}"
                self.log.error("Exception in %s: %s", gate_name, e, exc_info=True)

                if task.branch_name:
                    self.git.rollback(task.branch_name)
                    task.status = TaskStatus.ROLLED_BACK

                break
        else:
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now(timezone.utc).isoformat()

        self._audit(task)
        return task

    # ── Gate 1: SCOPE ─────────────────────────────────────────────

    async def _gate_scope(self, task: TaskState) -> Tuple[bool, str]:
        """Identify which components and files this task touches."""
        task.status = TaskStatus.SCOPING

        components_list = self.db.all_component_ids()

        prompt = f"""You are analyzing a development task for NEXUS OS.
Task: {task.description}

Available components: {json.dumps(components_list)}

Respond with ONLY valid JSON:
{{
    "affected_components": ["component-id-1", "component-id-2"],
    "affected_files": ["/opt/nexus/path/to/file.py"],
    "reasoning": "Why these components are affected"
}}

Rules:
- Only list components that will actually be READ or MODIFIED
- List specific file paths that will be changed
- If you're not sure which files, list the component and I'll resolve files from the database"""

        response, tier = await self.llm.complete(
            [
                {
                    "role": "system",
                    "content": "You are a code analysis assistant. Respond only with JSON.",
                },
                {"role": "user", "content": prompt},
            ]
        )
        task.llm_tier_used = tier

        try:
            scope = json.loads(_extract_json(response))
        except (json.JSONDecodeError, ValueError):
            return False, f"LLM returned invalid JSON for scope: {response[:200]}"

        task.affected_components = scope.get("affected_components", [])

        # Resolve files from DB
        affected_files = scope.get("affected_files", [])
        for comp_id in task.affected_components:
            comp = self.db.get_component(comp_id)
            if comp is None:
                return False, f"Component '{comp_id}' not found in compiled database"
            if comp.get("status") == "dead":
                return False, f"Component '{comp_id}' is marked DEAD — cannot modify dead code"
            for f in comp.get("files", []):
                if f not in affected_files:
                    affected_files.append(f)

        task.affected_files = affected_files
        return (
            True,
            f"Scope: {len(task.affected_components)} components, {len(task.affected_files)} files",
        )

    # ── Gate 2: CONTEXT ───────────────────────────────────────────

    async def _gate_context(self, task: TaskState) -> Tuple[bool, str]:
        """Load relevant decisions, interfaces, and gaps. Check for blockers."""
        task.status = TaskStatus.CONTEXT_LOADING

        context: Dict[str, List] = {
            "decisions": [],
            "interfaces": [],
            "gaps": [],
            "dependencies": [],
        }

        for comp_id in task.affected_components:
            gaps = self.db.get_gaps_for_component(comp_id)
            open_p0 = [g for g in gaps if g.get("severity") == "P0" and g.get("status") == "open"]
            if open_p0:
                # Only block if the gap's affected files overlap with what we're modifying.
                # Normalize gap file paths by stripping line-number suffixes (e.g. "foo.py:27" → "foo.py").
                blocking_gaps = []
                for g in open_p0:
                    gap_files = {
                        fp.split(":")[0] for fp in g.get("affected_files", [])
                    }
                    if not gap_files:
                        # No file list — block the whole component to be safe
                        blocking_gaps.append(g)
                    elif gap_files & set(task.affected_files):
                        blocking_gaps.append(g)
                if blocking_gaps:
                    gap_ids = [g["id"] for g in blocking_gaps]
                    return (
                        False,
                        f"P0 gaps block files being modified: {gap_ids}. Fix these first.",
                    )

            context["gaps"].extend(gaps)
            context["interfaces"].extend(
                self.db.get_interfaces_for_component(comp_id)
            )
            dep = self.db.get_dependencies(comp_id)
            if dep:
                context["dependencies"].append(dep)

        task.gate_results["context_data"] = {
            "gap_count": len(context["gaps"]),
            "interface_count": len(context["interfaces"]),
            "dependency_count": len(context["dependencies"]),
            "open_gaps": [g["id"] for g in context["gaps"] if g.get("status") == "open"],
        }

        return (
            True,
            f"Context: {len(context['gaps'])} gaps, {len(context['interfaces'])} interfaces",
        )

    # ── Gate 3: PROBE ─────────────────────────────────────────────

    async def _gate_probe(self, task: TaskState) -> Tuple[bool, str]:
        """Verify environment: git clean, files exist, DB matches disk."""
        task.status = TaskStatus.PROBING

        issues = []

        if not self.git.is_clean():
            issues.append("Git working tree is not clean — stash or commit first")
        if self.git.current_branch() != "main":
            issues.append(
                f"Not on main branch (on {self.git.current_branch()})"
            )

        for fp in task.affected_files:
            if not os.path.exists(fp):
                entry = self.db.get_file_entry(fp)
                if entry is not None:
                    issues.append(
                        f"DB says {fp} exists but it's missing from disk — DB stale?"
                    )
                # new file — OK
            else:
                ok, msg = self.verify.file_matches_db(fp, self.db)
                if not ok:
                    issues.append(msg)

        if issues:
            return False, "Probe failed:\n" + "\n".join(f"  - {i}" for i in issues)

        return True, "Environment OK: git clean, on main, all files match DB"

    # ── Gate 4: PLAN ──────────────────────────────────────────────

    async def _gate_plan(self, task: TaskState) -> Tuple[bool, str]:
        """LLM generates a specific plan. Plan is validated before execution."""
        task.status = TaskStatus.PLANNING

        file_contents: Dict[str, str] = {}
        for fp in task.affected_files[:10]:
            if os.path.exists(fp):
                try:
                    with open(fp) as f:
                        content = f.read()
                    if len(content) > 5000:
                        content = (
                            content[:2500]
                            + "\n... [TRUNCATED] ...\n"
                            + content[-2500:]
                        )
                    file_contents[fp] = content
                except Exception:
                    file_contents[fp] = "[UNREADABLE]"

        context_data = task.gate_results.get("context_data", {})

        plan_prompt = f"""You are planning a code modification for NEXUS OS.

TASK: {task.description}

AFFECTED COMPONENTS: {json.dumps(task.affected_components)}

OPEN GAPS FOR THESE COMPONENTS: {json.dumps(context_data.get('open_gaps', []))}

CURRENT FILE CONTENTS:
{json.dumps(file_contents, indent=2)[:8000]}

Generate a specific, line-level plan. Respond with ONLY valid JSON:
{{
    "changes": [
        {{
            "file": "/opt/nexus/path/to/file.py",
            "action": "modify",
            "description": "What changes to make and why",
            "adds_lines": 15,
            "removes_lines": 3
        }}
    ],
    "new_files": [
        {{
            "file": "/opt/nexus/path/to/new_file.py",
            "purpose": "What this file does",
            "estimated_lines": 50
        }}
    ],
    "test_strategy": "How to verify this change works",
    "rollback_impact": "What happens if we rollback — any data loss?"
}}

RULES:
- Do NOT create files that duplicate existing functionality
- Do NOT modify files outside the affected components
- Do NOT add dependencies not already in requirements
- Every change must have a clear justification
- If the task is too large, break it into subtasks and only plan the first one"""

        response, tier = await self.llm.complete(
            [
                {
                    "role": "system",
                    "content": "You are a senior software engineer. Plan carefully. Respond only with JSON.",
                },
                {"role": "user", "content": plan_prompt},
            ],
            max_tokens=4096,
            temperature=0.2,
        )

        try:
            plan = json.loads(_extract_json(response))
        except (json.JSONDecodeError, ValueError):
            return False, f"LLM returned invalid plan JSON: {response[:300]}"

        # Validate: no files outside scoped set
        planned_files = [c["file"] for c in plan.get("changes", [])]
        for pf in planned_files:
            if pf not in task.affected_files:
                return (
                    False,
                    f"Plan modifies {pf} which is outside the scoped files. Re-scope or reject.",
                )

        task.plan = plan
        return (
            True,
            f"Plan: {len(plan.get('changes', []))} modifications, {len(plan.get('new_files', []))} new files",
        )

    # ── Gate 5: EXECUTE ───────────────────────────────────────────

    async def _gate_execute(self, task: TaskState) -> Tuple[bool, str]:
        """Create work branch and execute the plan via LLM code generation."""
        task.status = TaskStatus.EXECUTING

        task.branch_name = self.git.create_work_branch(task.task_id)
        self.log.info("Created branch: %s", task.branch_name)

        changes_made = []

        # Apply modifications — patch-based approach (fast, low token count)
        for change in task.plan.get("changes", []):
            file_path = change["file"]
            if not os.path.exists(file_path):
                return False, f"File to modify doesn't exist: {file_path}"

            with open(file_path) as f:
                current_content = f.read()

            # Show only the relevant context window around the change (first 60 lines
            # for insertions at top; last 40 lines for insertions at end; full for short files).
            lines = current_content.splitlines(keepends=True)
            if len(lines) <= 80:
                context_snippet = current_content
            else:
                # Show first 40 + last 20 lines as context
                context_snippet = (
                    "".join(lines[:40])
                    + f"\n... [{len(lines) - 60} lines omitted] ...\n"
                    + "".join(lines[-20:])
                )

            patch_prompt = f"""You are applying a precise code change.

FILE: {file_path}
CHANGE: {change['description']}

FILE CONTEXT (may be truncated):
```
{context_snippet}
```

Respond with ONLY valid JSON — no other text:
{{
    "action": "replace" | "insert_before" | "insert_after" | "prepend" | "append",
    "search": "exact string to find in the file (for replace/insert_before/insert_after)",
    "new_code": "the new code to insert or use as replacement"
}}

RULES:
- "replace": replaces search string with new_code
- "insert_before": inserts new_code immediately before search string
- "insert_after": inserts new_code immediately after search string
- "prepend": adds new_code at the very start of the file
- "append": adds new_code at the very end of the file
- search must be an EXACT substring of the file (for replace/insert_before/insert_after)
- For a docstring at file top: use "insert_after" with search = the shebang/first import line,
  OR use "replace" on the existing short docstring if one exists"""

            response, tier = await self.llm.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "You are a surgical code patcher. "
                            "Output ONLY a JSON patch object. No explanation."
                        ),
                    },
                    {"role": "user", "content": patch_prompt},
                ],
                max_tokens=1024,
                temperature=0.1,
            )

            try:
                patch = json.loads(_extract_json(response))
            except (json.JSONDecodeError, ValueError):
                return False, f"LLM returned invalid patch JSON for {file_path}: {response[:200]}"

            action = patch.get("action", "")
            search = patch.get("search", "")
            new_code = patch.get("new_code", "")

            # Backup original
            backup_path = file_path + f".agent_v2_backup.{task.task_id}"
            shutil.copy2(file_path, backup_path)

            updated = current_content
            if action == "replace":
                if search not in current_content:
                    return False, f"Patch search string not found in {file_path}: {search[:80]!r}"
                updated = current_content.replace(search, new_code, 1)
            elif action == "insert_before":
                if search not in current_content:
                    return False, f"Patch search string not found in {file_path}: {search[:80]!r}"
                updated = current_content.replace(search, new_code + search, 1)
            elif action == "insert_after":
                if search not in current_content:
                    return False, f"Patch search string not found in {file_path}: {search[:80]!r}"
                updated = current_content.replace(search, search + new_code, 1)
            elif action == "prepend":
                updated = new_code + current_content
            elif action == "append":
                updated = current_content + new_code
            else:
                return False, f"Unknown patch action: {action!r}"

            if updated == current_content and action not in ("replace",):
                self.log.warning("Patch produced no change in %s (action=%s)", file_path, action)

            with open(file_path, "w") as f:
                f.write(updated)

            changes_made.append(file_path)
            self.log.info("Patched (%s): %s", action, file_path)

        # Create new files
        for new_file in task.plan.get("new_files", []):
            file_path = new_file["file"]

            create_prompt = f"""Create a new Python file for NEXUS OS.

FILE: {file_path}
PURPOSE: {new_file['purpose']}
ESTIMATED LINES: {new_file.get('estimated_lines', 50)}

CONTEXT — this is part of the task: {task.description}
RELATED COMPONENTS: {json.dumps(task.affected_components)}

Output ONLY the complete file content. No markdown fences. Raw code only."""

            response, tier = await self.llm.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "You are a code generator. Output only the complete file content. "
                            "No explanation. No markdown fences. Raw code only."
                        ),
                    },
                    {"role": "user", "content": create_prompt},
                ],
                max_tokens=8192,
                temperature=0.1,
            )

            new_content = response.strip()
            for fence in ("```python", "```"):
                if new_content.startswith(fence):
                    new_content = new_content[len(fence):]
                if new_content.endswith("```"):
                    new_content = new_content[:-3]
            new_content = new_content.strip()

            if not new_content:
                return False, f"LLM returned empty content for new file {file_path}"

            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w") as f:
                f.write(new_content)

            changes_made.append(file_path)
            task.affected_files.append(file_path)
            self.log.info("Created: %s", file_path)

        task.gate_results["execute_data"] = {"files_changed": changes_made}
        return True, f"Executed: {len(changes_made)} files written"

    # ── Gate 6: VERIFY ────────────────────────────────────────────

    async def _gate_verify(self, task: TaskState) -> Tuple[bool, str]:
        """Post-execution checks: syntax, imports, tests."""
        task.status = TaskStatus.VERIFYING

        issues = []
        results_log = []

        changed_files = task.gate_results.get("execute_data", {}).get("files_changed", [])

        for fp in changed_files:
            # Syntax check
            ok, msg = self.verify.syntax_check(fp)
            results_log.append(f"syntax({fp}): {'OK' if ok else msg}")
            if not ok:
                issues.append(f"Syntax error in {fp}: {msg}")
                continue

            # Import check
            ok, msg = self.verify.import_check(fp)
            results_log.append(f"import({fp}): {'OK' if ok else msg}")
            if not ok:
                # Import failures are warnings, not blockers (side-effect imports)
                self.log.warning("Import check warning for %s: %s", fp, msg)

        # Run component tests
        for comp_id in task.affected_components:
            ok, msg = self.verify.run_tests(comp_id)
            results_log.append(f"tests({comp_id}): {'PASS' if ok else 'FAIL'}\n{msg}")
            if not ok:
                issues.append(f"Tests failed for {comp_id}: {msg[:300]}")

        # LLM diff review
        diff = self.git.diff_full()
        if diff:
            review_prompt = f"""Review this git diff for NEXUS OS and identify any critical issues.

TASK: {task.description}

DIFF:
{diff[:4000]}

Respond with ONLY valid JSON:
{{
    "approved": true,
    "critical_issues": [],
    "warnings": ["optional warnings here"]
}}

A critical issue is something that would break the system (logic error, missing import,
wrong variable name, broken interface). Minor style issues are NOT critical."""

            try:
                response, _ = await self.llm.complete(
                    [
                        {
                            "role": "system",
                            "content": "You are a code reviewer. Be strict. Respond only with JSON.",
                        },
                        {"role": "user", "content": review_prompt},
                    ],
                    max_tokens=1024,
                    temperature=0.2,
                )
                review = json.loads(_extract_json(response))
                if not review.get("approved", True):
                    for issue in review.get("critical_issues", []):
                        issues.append(f"LLM review: {issue}")
                for warn in review.get("warnings", []):
                    self.log.warning("Review warning: %s", warn)
            except Exception as e:
                self.log.warning("LLM diff review failed (non-fatal): %s", e)

        task.gate_results["verify_data"] = {
            "checks": results_log,
            "issues": issues,
        }

        if issues:
            return False, "Verification failed:\n" + "\n".join(f"  - {i}" for i in issues)

        return True, f"Verification passed: {len(results_log)} checks OK"

    # ── Gate 7: UPDATE_DB ─────────────────────────────────────────

    async def _gate_update_db(self, task: TaskState) -> Tuple[bool, str]:
        """Update the compiled database YAML files to reflect changes."""
        task.status = TaskStatus.UPDATING_DB

        changed_files = task.gate_results.get("execute_data", {}).get("files_changed", [])
        updates_made = []

        # Update code_index.yaml line counts for modified files
        code_index_path = COMPILED_DB / "code_index.yaml"
        if code_index_path.exists():
            with open(code_index_path) as f:
                code_index = yaml.safe_load(f) or {}

            files_list = code_index.get("files", [])
            changed = False

            for fp in changed_files:
                if not os.path.exists(fp):
                    continue
                actual_lines = sum(1 for _ in open(fp))
                actual_size = os.path.getsize(fp)
                actual_hash = hashlib.sha256(open(fp, "rb").read()).hexdigest()[:16]
                actual_mtime = datetime.fromtimestamp(
                    os.path.getmtime(fp), tz=timezone.utc
                ).isoformat()

                found = False
                for entry in files_list:
                    if entry.get("path") == fp:
                        entry["lines"] = actual_lines
                        entry["size_bytes"] = actual_size
                        entry["hash"] = actual_hash
                        entry["last_modified"] = actual_mtime
                        found = True
                        changed = True
                        updates_made.append(f"updated code_index for {fp}")
                        break

                if not found:
                    # New file — add entry
                    files_list.append(
                        {
                            "path": fp,
                            "lines": actual_lines,
                            "size_bytes": actual_size,
                            "hash": actual_hash,
                            "last_modified": actual_mtime,
                            "component": task.affected_components[0] if task.affected_components else "unknown",
                        }
                    )
                    changed = True
                    updates_made.append(f"added code_index entry for {fp}")

            if changed:
                code_index["files"] = files_list
                code_index["last_updated"] = datetime.now(timezone.utc).isoformat()
                with open(code_index_path, "w") as f:
                    yaml.dump(code_index, f, default_flow_style=False, allow_unicode=True)

        # Close any gaps that this task addresses
        gaps_path = COMPILED_DB / "gaps.yaml"
        if gaps_path.exists():
            with open(gaps_path) as f:
                gaps_data = yaml.safe_load(f) or {}

            gaps_list = gaps_data.get("gaps", [])
            gaps_changed = False

            for gap in gaps_list:
                if gap.get("status") != "open":
                    continue
                for comp_id in task.affected_components:
                    if comp_id in gap.get("affected_components", []):
                        # Ask LLM if this gap was resolved
                        gap_check_prompt = f"""Did this task resolve the gap?

TASK: {task.description}
GAP ID: {gap['id']}
GAP TITLE: {gap.get('title', '')}
GAP DESCRIPTION: {gap.get('description', '')}

Respond with ONLY: yes or no"""
                        try:
                            resp, _ = await self.llm.complete(
                                [
                                    {
                                        "role": "system",
                                        "content": "Answer yes or no only.",
                                    },
                                    {"role": "user", "content": gap_check_prompt},
                                ],
                                max_tokens=10,
                                temperature=0.0,
                            )
                            if resp.strip().lower().startswith("yes"):
                                gap["status"] = "resolved"
                                gap["resolved_at"] = datetime.now(timezone.utc).isoformat()
                                gap["resolved_by"] = f"agent-v2:{task.task_id}"
                                gaps_changed = True
                                updates_made.append(f"closed gap {gap['id']}")
                        except Exception:
                            pass  # non-fatal
                        break

            if gaps_changed:
                gaps_data["gaps"] = gaps_list
                with open(gaps_path, "w") as f:
                    yaml.dump(gaps_data, f, default_flow_style=False, allow_unicode=True)

        # Invalidate cache so next reads see fresh data
        self.db.invalidate_cache()

        return True, f"DB updated: {len(updates_made)} changes — {', '.join(updates_made) or 'none'}"

    # ── Gate 8: COMMIT ────────────────────────────────────────────

    async def _gate_commit(self, task: TaskState) -> Tuple[bool, str]:
        """Stage and commit all changes to the work branch."""
        task.status = TaskStatus.COMMITTING

        changed_files = task.gate_results.get("execute_data", {}).get("files_changed", [])

        # Also commit DB updates
        db_files = [
            str(COMPILED_DB / "code_index.yaml"),
            str(COMPILED_DB / "gaps.yaml"),
        ]
        all_files = changed_files + [f for f in db_files if os.path.exists(f)]

        # Remove backup files from commit
        all_files = [f for f in all_files if ".agent_v2_backup." not in f]

        commit_msg = (
            f"agent-v2: {task.description[:72]}\n\n"
            f"Task-ID: {task.task_id}\n"
            f"Components: {', '.join(task.affected_components)}\n"
            f"LLM-Tier: {task.llm_tier_used}\n"
            f"Gate-Results: all 8 gates passed\n"
        )

        self.git.commit(commit_msg, all_files)

        # Clean up backup files
        for fp in changed_files:
            backup = fp + f".agent_v2_backup.{task.task_id}"
            if os.path.exists(backup):
                os.remove(backup)

        diff_stat = self.git.diff_stat()
        return True, f"Committed to {task.branch_name}\n{diff_stat}"

    # ── Audit ─────────────────────────────────────────────────────

    def _audit(self, task: TaskState):
        """Append task result to JSONL audit log."""
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "task_id": task.task_id,
            "description": task.description,
            "status": task.status.value,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "llm_tier_used": task.llm_tier_used,
            "branch_name": task.branch_name,
            "affected_components": task.affected_components,
            "error": task.error,
            "gate_results": {
                k: v for k, v in task.gate_results.items() if k != "context_data"
            },
        }
        with open(AUDIT_LOG, "a") as f:
            f.write(json.dumps(record) + "\n")


# ── Task Queue ────────────────────────────────────────────────────────────────


class TaskQueue:
    """Read/write tasks from the YAML task queue file."""

    def __init__(self, queue_path: Path = TASK_QUEUE):
        self.queue_path = queue_path

    def _load(self) -> Dict:
        if not self.queue_path.exists():
            return {"tasks": []}
        with open(self.queue_path) as f:
            return yaml.safe_load(f) or {"tasks": []}

    def _save(self, data: Dict):
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.queue_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    def pop_next(self) -> Optional[TaskState]:
        """Return and mark-in-progress the next QUEUED task."""
        data = self._load()
        for task_data in data.get("tasks", []):
            if task_data.get("status") == "queued":
                task_id = task_data.get("id") or hashlib.sha256(
                    task_data["description"].encode()
                ).hexdigest()[:12]
                task = TaskState(
                    task_id=task_id,
                    description=task_data["description"],
                )
                task_data["status"] = "in_progress"
                task_data["started_at"] = datetime.now(timezone.utc).isoformat()
                self._save(data)
                return task
        return None

    def mark_done(self, task: TaskState):
        """Update the queue entry with final status."""
        data = self._load()
        for task_data in data.get("tasks", []):
            if task_data.get("id") == task.task_id or (
                task_data.get("description") == task.description
                and task_data.get("status") == "in_progress"
            ):
                task_data["status"] = task.status.value
                task_data["completed_at"] = task.completed_at or datetime.now(
                    timezone.utc
                ).isoformat()
                task_data["branch_name"] = task.branch_name
                task_data["error"] = task.error
                break
        self._save(data)

    def add(self, description: str, task_id: Optional[str] = None) -> str:
        """Add a new task to the queue. Returns task_id."""
        data = self._load()
        tid = task_id or hashlib.sha256(
            (description + datetime.now(timezone.utc).isoformat()).encode()
        ).hexdigest()[:12]
        data.setdefault("tasks", []).append(
            {
                "id": tid,
                "description": description,
                "status": "queued",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._save(data)
        return tid


# ── Main Loop ─────────────────────────────────────────────────────────────────


async def run_agent(poll_interval: int = 30):
    """Continuously poll task queue and execute tasks."""
    log = logging.getLogger("agent-v2.main")
    pipeline = AgentPipeline()
    queue = TaskQueue()

    log.info("NEXUS Agent v2 started. Polling every %ds.", poll_interval)

    while True:
        task = queue.pop_next()
        if task is None:
            await asyncio.sleep(poll_interval)
            continue

        log.info("Starting task %s: %s", task.task_id, task.description)
        task = await pipeline.execute_task(task)
        queue.mark_done(task)
        log.info(
            "Task %s finished: %s%s",
            task.task_id,
            task.status.value,
            f" — {task.error}" if task.error else "",
        )

        # Brief pause between tasks
        await asyncio.sleep(2)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="NEXUS Agent v2")
    subparsers = parser.add_subparsers(dest="command")

    # run — start the agent loop
    run_p = subparsers.add_parser("run", help="Start the agent loop")
    run_p.add_argument("--poll", type=int, default=30, help="Poll interval (seconds)")

    # enqueue — add a task
    enq_p = subparsers.add_parser("enqueue", help="Add a task to the queue")
    enq_p.add_argument("description", help="Task description")
    enq_p.add_argument("--id", dest="task_id", default=None)

    # status — show queue
    subparsers.add_parser("status", help="Show task queue status")

    # run-once — execute a single task inline (for testing)
    once_p = subparsers.add_parser("run-once", help="Run a single task inline")
    once_p.add_argument("description", help="Task description")
    once_p.add_argument("--id", dest="task_id", default=None)

    args = parser.parse_args()

    if args.command == "run":
        asyncio.run(run_agent(poll_interval=args.poll))

    elif args.command == "enqueue":
        queue = TaskQueue()
        tid = queue.add(args.description, task_id=args.task_id)
        print(f"Enqueued task {tid}: {args.description}")

    elif args.command == "status":
        queue = TaskQueue()
        data = queue._load()
        tasks = data.get("tasks", [])
        if not tasks:
            print("Queue is empty.")
        else:
            print(f"{'ID':<14} {'STATUS':<14} {'DESCRIPTION'}")
            print("-" * 70)
            for t in tasks:
                print(
                    f"{t.get('id', '?'):<14} {t.get('status', '?'):<14} {t.get('description', '')[:42]}"
                )

    elif args.command == "run-once":
        async def _once():
            pipeline = AgentPipeline()
            tid = args.task_id or hashlib.sha256(
                args.description.encode()
            ).hexdigest()[:12]
            task = TaskState(task_id=tid, description=args.description)
            result = await pipeline.execute_task(task)
            print(f"\nResult: {result.status.value}")
            if result.error:
                print(f"Error: {result.error}")
            print(f"Branch: {result.branch_name}")
            for gate, data in result.gate_results.items():
                if isinstance(data, dict) and "passed" in data:
                    status = "PASS" if data["passed"] else "FAIL"
                    print(f"  {gate}: {status} — {data.get('result', '')[:80]}")

        asyncio.run(_once())

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
