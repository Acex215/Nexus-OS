import logging
from typing import Optional

logger = logging.getLogger("self_improver")

# Proposal templates keyed by failure category
_PROPOSALS = {
    "context_overflow": {
        "description": "Add context size monitoring and auto-trim to coordinator prompts when approaching token limit",
        "priority": "P1",
        "risk": "medium",
        "rationale": "Context overflow failures indicate prompts are hitting token limits; trimming will reduce these failures",
        "category": "context_overflow",
    },
    "scope_violation": {
        "description": "Improve scope declaration in task decomposer to include all transitively affected files",
        "priority": "P2",
        "risk": "low",
        "rationale": "Scope violations suggest the decomposer is not fully enumerating files that changes will touch",
        "category": "scope_violation",
    },
    "missing_file": {
        "description": "Add file existence check in _execute before attempting SEARCH/REPLACE patches",
        "priority": "P1",
        "risk": "low",
        "rationale": "Missing file failures can be caught early with a pre-flight existence check, avoiding wasted LLM calls",
        "category": "missing_file",
    },
    "coder_partial": {
        "description": "Modify task decomposer to split multi-file changes into one sub-task per file",
        "priority": "P2",
        "risk": "medium",
        "rationale": "Partial patch failures occur when a single task spans too many files; splitting reduces patch complexity",
        "category": "coder_partial",
    },
    "timeout": {
        "description": "Add adaptive timeout in llm_router_v2 based on prompt length (longer prompt = longer timeout)",
        "priority": "P2",
        "risk": "low",
        "rationale": "Fixed timeouts cause failures on legitimately long prompts; scaling timeout with input length will reduce false timeouts",
        "category": "timeout",
    },
    "lm_unavailable": {
        "description": "Add LLM endpoint watchdog that auto-pauses queue when endpoints go down",
        "priority": "P1",
        "risk": "low",
        "rationale": "LLM unavailability cascades into task failures; a watchdog lets the queue wait rather than fail",
        "category": "lm_unavailable",
    },
}

# Priority ordering for sorting (lower index = higher priority)
_PRIORITY_ORDER = {"P1": 0, "P2": 1}


def generate_proposals(summary: Optional[dict] = None) -> list:
    """Generate improvement proposals based on current performance metrics."""
    if summary is None:
        try:
            from metrics import get_performance_summary
            summary = get_performance_summary()
        except Exception as e:
            logger.error("Failed to get performance summary: %s", e)
            return []

    proposals = []

    # High-level proposal if success rate is critically low
    success_rate = summary.get("success_rate", 0.0)
    if success_rate < 50:
        proposals.append({
            "description": (
                f"Review and simplify coordinator system prompt to reduce task failure rate "
                f"(currently {success_rate}%)"
            ),
            "priority": "P1",
            "risk": "medium",
            "rationale": f"Overall success rate of {success_rate}% is critically low; simplifying the coordinator prompt is the highest-leverage intervention",
            "category": "general",
        })

    # Per-category proposals for any category with at least one failure
    categories = summary.get("failure_categories", {})
    for category, count in categories.items():
        if count > 0 and category in _PROPOSALS:
            proposals.append(_PROPOSALS[category].copy())

    if not proposals:
        return []

    # Sort by priority (P1 before P2), deduplicate by category, cap at 3
    proposals.sort(key=lambda p: _PRIORITY_ORDER.get(p["priority"], 99))
    seen = set()
    unique = []
    for p in proposals:
        if p["category"] not in seen:
            seen.add(p["category"])
            unique.append(p)
        if len(unique) == 3:
            break

    return unique


def format_proposals(proposals: Optional[list] = None) -> str:
    """Return a Discord-formatted string listing improvement proposals."""
    if proposals is None:
        proposals = generate_proposals()

    if not proposals:
        return "No improvement proposals at this time."

    lines = ["🔧 **Self-Improvement Proposals**", ""]
    for i, p in enumerate(proposals, start=1):
        lines.append(f"{i}. [{p['priority']}] {p['description']}")
        lines.append(f"   Rationale: {p['rationale']}")
    lines.append("")
    lines.append("Say `approve N` to add proposal N to the task queue.")

    return "\n".join(lines)
