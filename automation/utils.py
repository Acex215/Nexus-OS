"""Shared utilities for NEXUS OS CAF automation modules."""
import re


def _strip_json(raw: str) -> str:
    """Strip markdown code fences and extract the first JSON object."""
    cleaned = re.sub(r'```(?:json)?\s*', '', raw).strip().rstrip('`').strip()
    m = re.search(r'\{.*\}', cleaned, re.DOTALL)
    return m.group() if m else ""
