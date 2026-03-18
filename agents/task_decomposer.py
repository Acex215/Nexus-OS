#!/usr/bin/env python3
"""NEXUS OS Dev Assistant — Sub-task Decomposition (Phase 2)

Uses the coordinator LLM tier to break complex tasks into scoped
sub-tasks with dependency tracking and affected file declarations.

Usage:
    from task_decomposer import decompose_task
    sub_tasks = await decompose_task(task_dict, llm_router)
    # Returns list of dicts: [{description, priority, risk, depends_on, affected_files}]
    # Returns None if decomposition is not needed (task is simple enough).
"""

import json
import logging
from typing import Optional

log = logging.getLogger("task_decomposer")

# ── Decomposition prompt ──────────────────────────────────────────────────────

DECOMPOSE_SYSTEM = """You are a senior software architect decomposing a development task into small, independently executable sub-tasks for an autonomous coding assistant.

Rules:
1. Each sub-task must modify at most 2-3 files.
2. Each sub-task must be completable with a single SEARCH/REPLACE patch session (max 10 patches).
3. Sub-tasks execute in dependency order — declare depends_on when ordering matters.
4. Every sub-task must declare affected_files upfront.
5. If the task is simple enough to do in one pass (≤3 steps, ≤3 files), return null.
6. Priority inherits from the parent unless there's a reason to differ.
7. Risk: "low" for adding code/tests, "medium" for refactoring, "high" for anything touching configs/contracts/deployment.

Respond ONLY with valid JSON. No markdown fences, no explanation.

Format:
{
  "needs_decomposition": true,
  "sub_tasks": [
    {
      "description": "Clear, specific description of what to do",
      "priority": "P2",
      "risk": "low",
      "depends_on": [],
      "affected_files": ["/opt/nexus/agents/some_file.py"]
    }
  ]
}

Or if decomposition is not needed:
{"needs_decomposition": false, "sub_tasks": []}
"""

DECOMPOSE_USER_TEMPLATE = """Task to decompose:
- ID: {task_id}
- Description: {description}
- Priority: {priority}
- Risk: {risk}
- Affected files (if known): {affected_files}

Analyze this task. If it requires more than 3 steps or touches more than 3 files, decompose it into sub-tasks. Otherwise return needs_decomposition=false."""


# ── Decomposer ────────────────────────────────────────────────────────────────

async def decompose_task(
    task: dict,
    llm_generate,  # async callable: (agent_id, messages, task_type, **kwargs) -> dict
) -> Optional[list[dict]]:
    """Decompose a task into sub-tasks using the coordinator LLM.

    Args:
        task: Task dict from TaskQueue.
        llm_generate: Async LLM call function (from llm_router_v2).

    Returns:
        List of sub-task dicts if decomposition needed, None otherwise.
    """
    task_id = task.get("id", "unknown")
    description = task.get("description", "")
    priority = task.get("priority", "P2")
    risk = task.get("risk", "low")
    affected = task.get("affected_files", [])

    user_msg = DECOMPOSE_USER_TEMPLATE.format(
        task_id=task_id,
        description=description,
        priority=priority,
        risk=risk,
        affected_files=", ".join(affected) if affected else "not specified",
    )

    messages = [
        {"role": "system", "content": DECOMPOSE_SYSTEM},
        {"role": "user", "content": user_msg},
    ]

    try:
        result = await llm_generate(
            "dev-assistant",
            messages,
            task_type="planning",
            max_tokens=2048,
            temperature=0.2,
        )

        content = result.get("content", "")
        if not content:
            log.warning("Empty LLM response for decomposition of %s", task_id)
            return None

        # Strip any markdown fences the LLM might add despite instructions
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        parsed = json.loads(content)

        if not parsed.get("needs_decomposition", False):
            log.info("Task %s does not need decomposition", task_id)
            return None

        sub_tasks = parsed.get("sub_tasks", [])
        if not sub_tasks:
            return None

        # Validate sub-task structure
        validated = []
        for i, st in enumerate(sub_tasks):
            if not isinstance(st, dict) or not st.get("description"):
                log.warning("Skipping invalid sub-task %d for %s", i, task_id)
                continue
            validated.append({
                "description": st["description"],
                "priority": st.get("priority", priority),
                "risk": st.get("risk", risk),
                "depends_on": st.get("depends_on", []),
                "affected_files": st.get("affected_files", []),
            })

        if len(validated) <= 1:
            # Single sub-task = no real decomposition
            return None

        log.info("Decomposed %s into %d sub-tasks", task_id, len(validated))
        return validated

    except json.JSONDecodeError as e:
        log.error("JSON parse error in decomposition of %s: %s", task_id, e)
        return None
    except Exception as e:
        log.error("Decomposition failed for %s: %s", task_id, e)
        return None
