#!/usr/bin/env python3
"""Failure Analyzer — diagnoses failed task steps and produces revised execution plans.

When a task step fails, instead of retrying the same plan, this module:
  1. Collects error context (command, stderr, exit code) plus live environment info
  2. Sends it to the LLM with the original intent and plan
  3. Gets back a REVISED plan that addresses the root cause
  4. Returns the revised plan for the orchestrator to execute

The LLM also receives the COMMAND_ALLOWLIST so it stops generating disallowed
commands (like `cd`) and uses absolute paths instead.

Public API:
    analyze_failure(intent, failed_step, step_result, step_index,
                    execution_plan, failure_history) -> dict
"""

import json
import logging
import re
import subprocess

from llm_router import route_llm_call
from guardrails import COMMAND_ALLOWLIST

log = logging.getLogger("failure_analyzer")

# ── Failure history (module-level so both dev_orchestrator and command_executor
#    can access it via import without circular dependencies) ───────────────────
_failure_history: dict[str, list] = {}  # intent_id -> list of analysis result dicts


def clear_failure_history(intent_id: str | None = None) -> None:
    """Clear stored failure history.

    If intent_id is given, clears only that intent's history.
    If None, clears all history (used on full restart).
    """
    if intent_id is None:
        _failure_history.clear()
    else:
        _failure_history.pop(intent_id, None)


# ── System prompt ─────────────────────────────────────────────────────────────

_ANALYZE_SYSTEM = """\
You are a senior DevOps engineer analyzing a failed automated task step on a \
Raspberry Pi 5 cluster (aarch64, Debian Bookworm) running NEXUS OS.

Your job: diagnose the root cause and produce a corrected execution plan.

Respond ONLY with valid JSON — no markdown fences, no explanation outside JSON:
{
  "diagnosis": "one sentence explaining what went wrong",
  "root_cause": "missing_dependency|wrong_path|permission_error|syntax_error|environment|allowlist_violation|other",
  "pre_fix_commands": ["safe setup commands to run before retrying, e.g. pip3 install X"],
  "revised_plan": [
    {"command": "corrected command using absolute paths", "description": "what this does"}
  ],
  "confidence": 0.85,
  "should_retry": true
}

Rules:
- NEVER use 'cd' in commands — it is NOT in the allowlist.  Use absolute paths.
  BAD:  cd /opt/nexus && pytest tests/
  GOOD: python3 -m pytest /opt/nexus/tests/
- If a binary is missing, add its installation to pre_fix_commands.
- pre_fix_commands run without approval gates — limit to installs and config only.
- revised_plan replaces the failed step and all steps that follow it.
- If the same failure appears in PREVIOUS ATTEMPTS, try a DIFFERENT approach.
- Set should_retry=false only when human intervention is unavoidably required.\
"""

# ── Public API ────────────────────────────────────────────────────────────────

def analyze_failure(
    intent: dict,
    failed_step: dict,
    step_result: dict,
    step_index: int,
    execution_plan: list,
    failure_history: list | None = None,
) -> dict:
    """Diagnose a failed plan step and return a revised plan.

    Args:
        intent:          Full intent dict (id, title, description, affected_files, …)
        failed_step:     The step dict from execution_plan that failed
        step_result:     Execution result dict {stdout, stderr, returncode, timed_out}
        step_index:      0-based index of the failed step in execution_plan
        execution_plan:  Full original list of step dicts
        failure_history: Previous analyze_failure results for this intent (loop guard)

    Returns:
        {
            "diagnosis":        str,
            "root_cause":       str,
            "pre_fix_commands": list[str],
            "revised_plan":     list[dict],
            "confidence":       float,
            "should_retry":     bool,
        }
    """
    # Use module-level history if caller doesn't pass one
    if failure_history is None:
        failure_history = _failure_history.get(intent.get("id", ""), [])

    env_context  = _gather_environment_context(failed_step, intent=intent)
    user_prompt  = _build_prompt(
        intent, failed_step, step_result, step_index,
        execution_plan, failure_history, env_context,
    )

    log.info(
        "Analyzing failure for intent=%s step=%d rc=%s",
        intent.get("id", "?"), step_index, step_result.get("returncode"),
    )

    result = route_llm_call("plan", _ANALYZE_SYSTEM, user_prompt)

    if result.get("error") or not result.get("response"):
        log.warning("LLM unavailable during failure analysis: %s", result.get("error"))
        return _fallback(step_result)

    parsed = _parse_response(result["response"])
    log.info(
        "Failure analysis: root_cause=%s confidence=%.2f should_retry=%s",
        parsed["root_cause"], parsed["confidence"], parsed["should_retry"],
    )
    return parsed


# ── Helpers ───────────────────────────────────────────────────────────────────

def _gather_environment_context(failed_step: dict, intent: dict | None = None) -> str:
    """Run quick diagnostic probes to help the LLM understand the environment."""
    cmd    = failed_step.get("command", "")
    binary = cmd.split()[0].lstrip("$").strip() if cmd else ""

    # Determine working directory from affected_files or default
    affected = (intent or {}).get("affected_files", [])
    work_dir = "/opt/nexus/automation"
    for p in affected:
        import os
        candidate = p if os.path.isdir(p) else os.path.dirname(p)
        if candidate and os.path.isdir(candidate):
            work_dir = candidate
            break

    checks: list[str] = []

    # Binary availability
    if binary:
        checks.append(f"which {binary} 2>&1 || echo 'NOT FOUND: {binary}'")
        # Common alternatives for known binaries
        if binary in ("pytest", "py.test"):
            checks.append("python3 -m pytest --version 2>&1 || echo 'python3 -m pytest: not available'")
            checks.append("pip3 show pytest 2>&1 | grep -E 'Name|Version|Location' || echo 'pytest not installed'")
        elif binary == "make":
            checks.append(f"ls {work_dir}/Makefile 2>&1 || echo 'No Makefile in {work_dir}'")
        elif binary in ("npm", "node"):
            checks.append(f"ls {work_dir}/package.json 2>&1 || echo 'No package.json in {work_dir}'")

    # Project layout
    checks += [
        f"ls -la {work_dir}/ 2>&1 | head -30",
        f"find {work_dir} -maxdepth 2 -name 'test_*.py' -o -name '*_test.py' 2>/dev/null | head -10",
        f"ls {work_dir}/Makefile 2>/dev/null && grep -E '^[a-zA-Z][a-zA-Z0-9_-]*:' {work_dir}/Makefile | head -20 || echo 'No Makefile'",
        f"ls {work_dir}/pytest.ini {work_dir}/setup.cfg {work_dir}/pyproject.toml 2>&1",
    ]

    # Python environment
    checks += [
        "python3 --version 2>&1",
        "pip3 list --format=columns 2>&1 | head -20",
        "echo CWD: $(pwd)",
        "echo PATH: $PATH",
    ]

    # Affected file existence
    for p in affected[:5]:
        checks.append(f"ls -la {p} 2>&1 | head -5")

    parts: list[str] = []
    for check in checks:
        try:
            r = subprocess.run(
                check, shell=True, capture_output=True, text=True, timeout=10
            )
            out = (r.stdout + r.stderr).strip()
            parts.append(f"$ {check}\n{out}")
        except Exception as exc:
            parts.append(f"$ {check}\nERROR: {exc}")

    return "\n\n".join(parts)


def _build_prompt(
    intent: dict,
    failed_step: dict,
    step_result: dict,
    step_index: int,
    execution_plan: list,
    failure_history: list,
    env_context: str,
) -> str:
    error_output = (
        step_result.get("stderr", "") or step_result.get("stdout", "")
    ).strip()[:1500]

    allowlist_note = (
        "ALLOWED COMMANDS (first token must be in this list for auto-approval):\n"
        + json.dumps(COMMAND_ALLOWLIST)
        + "\n\nNOT in allowlist: 'cd', 'bash', 'sh', 'sudo' (except specific combos).\n"
        "Use absolute paths everywhere instead of 'cd'."
    )

    history_block = ""
    if failure_history:
        history_block = "\n\nPREVIOUS ATTEMPTS (do NOT repeat these fixes):\n"
        for idx, h in enumerate(failure_history, 1):
            history_block += (
                f"  Attempt {idx}: {h.get('diagnosis', 'unknown')}\n"
                f"  Fix tried:  {json.dumps(h.get('pre_fix_commands', []))}\n"
                f"  Result:     still failed\n\n"
            )

    # Compact plan representation — only show steps from failure point onward
    remaining = execution_plan[step_index:]

    return (
        f"INTENT ID: {intent.get('id', '?')}\n"
        f"TITLE:     {intent.get('title', '')}\n"
        f"DESC:      {intent.get('description', '').strip()[:600]}\n"
        f"FILES:     {json.dumps(intent.get('affected_files', []))}\n\n"
        f"FAILED STEP ({step_index + 1} of {len(execution_plan)}):\n"
        f"  command:   {failed_step.get('command', '')}\n"
        f"  exit_code: {step_result.get('returncode', '?')}\n"
        f"  timed_out: {step_result.get('timed_out', False)}\n\n"
        f"ERROR OUTPUT:\n{error_output}\n\n"
        f"REMAINING STEPS (from failure onward):\n"
        f"{json.dumps(remaining, indent=2)}\n\n"
        f"ENVIRONMENT:\n{env_context}\n\n"
        f"{allowlist_note}"
        f"{history_block}\n\n"
        f"Produce the corrected JSON plan."
    )


def _parse_response(raw: str) -> dict:
    """Strip markdown fences and parse the LLM's JSON response."""
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    blob = m.group() if m else ""

    try:
        data = json.loads(blob)
    except (json.JSONDecodeError, ValueError):
        log.warning("failure_analyzer: could not parse LLM JSON response")
        return _fallback_parse()

    data.setdefault("diagnosis",        "LLM did not provide a diagnosis")
    data.setdefault("root_cause",       "other")
    data.setdefault("pre_fix_commands", [])
    data.setdefault("revised_plan",     [])
    data.setdefault("confidence",       0.5)
    data.setdefault("should_retry",     True)

    # Sanitise types
    data["pre_fix_commands"] = [str(c) for c in data["pre_fix_commands"] if c]
    data["confidence"]       = max(0.0, min(1.0, float(data["confidence"])))
    data["should_retry"]     = bool(data["should_retry"])

    return data


def _fallback(step_result: dict) -> dict:
    """Return a safe no-op result when the LLM is unavailable."""
    return {
        "diagnosis":        "LLM unavailable — cannot analyse failure automatically",
        "root_cause":       "other",
        "pre_fix_commands": [],
        "revised_plan":     [],
        "confidence":       0.0,
        "should_retry":     False,
    }


def _fallback_parse() -> dict:
    """Return a safe no-op result when the LLM response cannot be parsed."""
    return {
        "diagnosis":        "Failed to parse LLM analysis response",
        "root_cause":       "other",
        "pre_fix_commands": [],
        "revised_plan":     [],
        "confidence":       0.0,
        "should_retry":     False,
    }
