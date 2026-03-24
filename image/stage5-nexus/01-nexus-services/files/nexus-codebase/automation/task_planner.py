#!/usr/bin/env python3
"""NEXUS OS Task Planner

Implements the planner-executor separation:
  Planner  → LLM generates a structured JSON execution plan
  Executor → orchestrator runs steps and calls verify_plan_result()

Uses llm_router for all LLM calls (role="plan" for planning, role="verify" for result check).

Public API:
    generate_execution_plan(intent, context_packet) -> dict | None
    verify_plan_result(intent, plan, execution_results) -> dict
"""
import json
import logging
import re

from llm_router import route_llm_call

log = logging.getLogger("task_planner")

# Set to True by generate_execution_plan when the failure is LLM unavailability
# (all_tiers_down), False for structural failures (bad JSON, unsafe steps, etc.).
# Callers can check this to decide whether a retry is worthwhile.
_last_failure_was_llm: bool = False

# ── System prompts ────────────────────────────────────────────────────────────

_PLAN_SYSTEM = """\
You are a task planner for the NEXUS OS development system. Given an intent (what to do) \
and context (relevant code, decisions, and constraints), generate a structured execution plan.

Respond ONLY with valid JSON in this format:
{
  "intent_id": "the intent id",
  "summary": "one-line summary of what will be done",
  "risk_assessment": "Low/Medium/High \u2014 brief explanation",
  "confidence": 0.0,
  "notify_human": false,
  "should_decompose": false,
  "decomposition": [],
  "steps": [
    {
      "step_num": 1,
      "action": "bash|create_file|modify_file|ssh_command",
      "command": "the command to run (for bash/ssh_command)",
      "path": "file path (for create_file/modify_file)",
      "content": "file content (for create_file)",
      "node": "nexus-admin|nexus-master|nexus-ai|nexus-storage|nexus-ai2",
      "description": "what this step does",
      "expect_pattern": "optional regex to verify success in stdout",
      "lines_added_estimate": 0,
      "lines_deleted_estimate": 0
    }
  ],
  "files_modified": [],
  "files_created": [],
  "tests_to_run": [],
  "rollback_steps": []
}

RULES:
- NEVER include commands that modify protected files
- NEVER use rm -rf, dd, fdisk, mkfs, reboot, shutdown
- Always include rollback steps (in reverse order)
- Set notify_human=true if confidence < 0.7 or risk is High
- All file changes go on git branches, never directly on main
- node defaults to nexus-admin if not specified
- For create_file steps: put full file content in the "content" field
- For bash steps on nexus-admin: omit "path" and "content"
- If the intent spans more than 8 steps OR covers multiple independent deliverables,
  set should_decompose=true and populate the decomposition array instead of steps.
  When should_decompose=true, steps may be an empty array [].
  decomposition format: [
    {
      "title": "concise sub-task title",
      "description": "what this sub-task achieves",
      "acceptance_criteria": ["verifiable criterion"],
      "affected_files": ["/path/to/file"],
      "risk": "low|medium|high",
      "complexity": "low|medium|high|very_high",
      "autonomous": true
    }
  ]

Protected files — NEVER touch:
  /opt/nexus/agents/hierarchy_manager.py
  /opt/nexus/agents/agent_registry.py
  /opt/nexus/agents/agent_workflow.py
  /opt/nexus/agents/blockchain_logger.py
  /opt/nexus/agents/llm_client.py
  /opt/nexus/agents/.env
  /opt/nexus/automation/constitution.json
  /opt/nexus/automation/intent_registry.yaml (only status field allowed)
  Any *.sol file
  Any genesis*.json file\
"""

_VERIFY_SYSTEM = """\
You are verifying whether a NEXUS OS task completed successfully.

You are given: the original intent, the execution plan, and the results of each step.

Return ONLY valid JSON:
{
  "success": true,
  "reason": "one-sentence explanation",
  "suggestions": "what to try next if failed, or empty string"
}

Be strict:
- If any step had a non-zero exit code and there was no rollback, likely failed.
- If acceptance criteria outputs are missing, likely failed.
- If tests_to_run produced errors, failed.
- Only return success=true if the core deliverable is clearly present.\
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

_PROTECTED = [
    "/opt/nexus/agents/hierarchy_manager.py",
    "/opt/nexus/agents/agent_registry.py",
    "/opt/nexus/agents/agent_workflow.py",
    "/opt/nexus/agents/blockchain_logger.py",
    "/opt/nexus/agents/llm_client.py",
    "/opt/nexus/agents/.env",
    "/opt/nexus/automation/constitution.json",
    ".sol",
    "genesis",
]

_DANGEROUS_CMDS = ["rm -rf", "dd ", "fdisk", "mkfs", "reboot", "shutdown", " poweroff"]


def _is_safe_step(step: dict) -> bool:
    cmd = step.get("command", "") + step.get("path", "")
    for p in _PROTECTED:
        if p in cmd:
            return False
    for d in _DANGEROUS_CMDS:
        if d in cmd:
            return False
    return True




def _parse_plan(raw: str) -> dict | None:
    blob = _strip_json(raw)
    if not blob:
        return None
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as e:
        log.debug("JSON parse error: %s", e)
        return None

    # Extract decomposition fields early — they change validation rules
    should_decompose = bool(data.get("should_decompose", False))
    decomposition: list[dict] = []
    if should_decompose:
        raw_decomp = data.get("decomposition", [])
        if isinstance(raw_decomp, list):
            decomposition = [
                {
                    "title":                str(d.get("title", ""))[:120],
                    "description":          str(d.get("description", ""))[:500],
                    "acceptance_criteria":  list(d.get("acceptance_criteria", [])),
                    "affected_files":       list(d.get("affected_files", [])),
                    "risk":                 str(d.get("risk", "medium")),
                    "complexity":           str(d.get("complexity", "medium")),
                    "autonomous":           bool(d.get("autonomous", True)),
                }
                for d in raw_decomp if isinstance(d, dict)
            ]
        if not decomposition:
            log.debug("Plan has should_decompose=true but empty decomposition array")
            return None

    # Validate steps (required unless decomposing)
    if not should_decompose:
        if "steps" not in data or not isinstance(data["steps"], list):
            log.debug("Plan missing 'steps' list")
            return None

    # Normalise steps
    clean_steps = []
    for i, s in enumerate(data.get("steps", []), 1):
        if not isinstance(s, dict):
            continue
        clean_steps.append({
            "step_num":               s.get("step_num", i),
            "action":                 s.get("action", "bash"),
            "command":                s.get("command", ""),
            "path":                   s.get("path", ""),
            "content":                s.get("content", ""),
            "node":                   s.get("node", "nexus-admin"),
            "description":            s.get("description", f"Step {i}"),
            "expect_pattern":         s.get("expect_pattern", ""),
            "lines_added_estimate":   s.get("lines_added_estimate", 0),
            "lines_deleted_estimate": s.get("lines_deleted_estimate", 0),
        })

    if not should_decompose and not clean_steps:
        log.debug("Plan has no usable steps")
        return None

    confidence = float(data.get("confidence", 0.5))
    risk       = str(data.get("risk_assessment", "Medium"))
    notify     = bool(data.get("notify_human", False))

    # Enforce notify_human if confidence or risk require it
    if confidence < 0.7 or risk.lower().startswith("high"):
        notify = True

    return {
        "intent_id":       data.get("intent_id", ""),
        "summary":         str(data.get("summary", ""))[:120],
        "risk_assessment": risk,
        "confidence":      confidence,
        "notify_human":    notify,
        "should_decompose": should_decompose,
        "decomposition":   decomposition,
        "steps":           clean_steps,
        "files_modified":  list(data.get("files_modified", [])),
        "files_created":   list(data.get("files_created", [])),
        "tests_to_run":    list(data.get("tests_to_run", [])),
        "rollback_steps":  list(data.get("rollback_steps", [])),
    }


# ── Public API ────────────────────────────────────────────────────────────────

def generate_execution_plan(intent: dict, context_packet: str) -> dict | None:
    """Generate a structured execution plan for the given intent.

    Uses llm_router role="plan". Retries once on JSON parse failure.
    Returns a validated plan dict or None.
    Sets the module-level _last_failure_was_llm flag so callers can distinguish
    LLM-unavailability (retriable) from structural failures (not retriable).
    """
    global _last_failure_was_llm
    _last_failure_was_llm = False

    intent_id = intent.get("id", "unknown")
    criteria  = intent.get("acceptance_criteria") or []
    files     = intent.get("affected_files") or []

    user_prompt = (
        f"Intent ID: {intent_id}\n"
        f"Title: {intent.get('title', '')}\n\n"
        f"Description:\n{intent.get('description', '').strip()}\n\n"
        f"Acceptance criteria:\n"
        + "\n".join(f"- {c}" for c in criteria)
        + f"\n\nAffected files:\n"
        + "\n".join(str(f) for f in files)
        + f"\n\nContext (use to inform file paths and commands — do not copy verbatim):\n"
        + context_packet[:4000]
        + "\n\nGenerate the execution plan."
    )

    result = route_llm_call("plan", _PLAN_SYSTEM, user_prompt)

    if result.get("error"):
        log.error("Plan generation failed for %s: %s", intent_id, result["error"])
        _last_failure_was_llm = (result["error"] == "all_tiers_down")
        return None

    plan = _parse_plan(result["response"])

    if plan is None:
        log.warning("Plan parse failed for %s — retrying", intent_id)
        retry_prompt = (
            "Your previous response could not be parsed as JSON. "
            "Return ONLY the raw JSON object with no markdown fences, "
            "no explanation, no preamble.\n\n" + user_prompt
        )
        result2 = route_llm_call("plan", _PLAN_SYSTEM, retry_prompt)
        if result2.get("response"):
            plan = _parse_plan(result2["response"])

    if plan is None:
        log.error("Plan generation gave unparseable JSON for %s after retry", intent_id)
        return None

    # Safety sweep: remove any step that touches protected files or runs dangerous commands
    safe_steps = [s for s in plan["steps"] if _is_safe_step(s)]
    removed = len(plan["steps"]) - len(safe_steps)
    if removed:
        log.warning("Removed %d unsafe step(s) from plan for %s", removed, intent_id)
        if not safe_steps:
            log.error("All steps were unsafe — aborting plan for %s", intent_id)
            return None
    plan["steps"] = safe_steps

    log.info(
        "Plan for %s: %d steps, confidence=%.2f, notify_human=%s, risk=%s",
        intent_id, len(plan["steps"]), plan["confidence"],
        plan["notify_human"], plan["risk_assessment"],
    )
    return plan


def verify_plan_result(intent: dict, plan: dict, execution_results: list) -> dict:
    """Check if the executed plan achieved the intent's goals.

    Uses llm_router role="verify".
    Returns {"success": bool, "reason": str, "suggestions": str}.
    """
    # Build a compact summary of execution
    step_summaries = []
    for i, res in enumerate(execution_results):
        step = plan["steps"][i] if i < len(plan["steps"]) else {}
        step_summaries.append(
            f"Step {i+1} ({step.get('description', '?')}): "
            f"rc={res.get('returncode', '?')} "
            f"stdout={res.get('stdout', '')[:200]!r} "
            f"stderr={res.get('stderr', '')[:100]!r}"
        )

    tests = plan.get("tests_to_run", [])
    user_prompt = (
        f"Intent: {intent.get('title', '')}\n"
        f"Summary: {plan.get('summary', '')}\n\n"
        f"Acceptance criteria:\n"
        + "\n".join(f"- {c}" for c in (intent.get("acceptance_criteria") or []))
        + f"\n\nExecution results:\n"
        + "\n".join(step_summaries)
        + (f"\n\nVerification tests run: {tests}" if tests else "")
        + "\n\nDid the task succeed?"
    )

    result = route_llm_call("verify", _VERIFY_SYSTEM, user_prompt)

    # Fallback: check if all steps had rc=0
    if result.get("error") or not result.get("response"):
        all_ok = all(r.get("returncode", 1) == 0 for r in execution_results)
        return {
            "success":     all_ok,
            "reason":      "LLM unavailable — inferred from exit codes",
            "suggestions": "" if all_ok else "Check step stderr output",
        }

    blob = _strip_json(result["response"])
    if blob:
        try:
            data = json.loads(blob)
            return {
                "success":     bool(data.get("success", False)),
                "reason":      str(data.get("reason", ""))[:300],
                "suggestions": str(data.get("suggestions", ""))[:300],
            }
        except json.JSONDecodeError:
            pass

    # Parse failed — fallback
    all_ok = all(r.get("returncode", 1) == 0 for r in execution_results)
    return {
        "success":     all_ok,
        "reason":      "Verify response unreadable — inferred from exit codes",
        "suggestions": "",
    }
