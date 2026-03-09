#!/usr/bin/env python3
"""NEXUS OS Planning Engine

Deterministic task selection from the intent registry.
The orchestrator uses this to decide WHAT to work on next;
the LLM is only used to decide HOW to do it.

Protected file — do NOT modify intent_registry.yaml except via update_intent_status().
"""
import json
import logging
import re
import yaml
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("planning_engine")

INTENT_REGISTRY_PATH = Path("/opt/nexus/automation/intent_registry.yaml")
NOTIF_STATE_PATH     = Path("/opt/nexus/automation/.notification_state.json")

CATEGORY_ORDER   = {"next_step": 0, "next_phase": 1, "roadmap": 2, "idea": 3}
RISK_ORDER       = {"low": 0, "medium": 1, "high": 2}
COMPLEXITY_ORDER = {"low": 0, "medium": 1, "high": 2, "very_high": 3}

VALID_TRANSITIONS = {
    "pending":     {"in_progress", "blocked"},
    "in_progress": {"completed", "failed", "blocked", "decomposed"},
    "blocked":     {"pending"},
    "failed":      {"pending", "blocked"},   # retry or skip
    "decomposed":  set(),   # terminal — sub-intents carry the work
}

SKIP_STATUSES = {"completed", "in_progress", "blocked", "failed", "decomposed"}


# ── Notification state helpers ────────────────────────────────────────────────

def _load_notif_state() -> dict:
    """Load per-intent notification state from disk (empty dict on missing/corrupt)."""
    try:
        if NOTIF_STATE_PATH.exists():
            return json.loads(NOTIF_STATE_PATH.read_text())
    except Exception:
        pass
    return {}


def _save_notif_state(state: dict) -> None:
    """Persist notification state atomically."""
    try:
        tmp = NOTIF_STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.replace(NOTIF_STATE_PATH)
    except Exception:
        pass


# ── Public API ────────────────────────────────────────────────────────────────

def load_intent_registry() -> list[dict]:
    """Read intent_registry.yaml and return the list of intent dicts."""
    with open(INTENT_REGISTRY_PATH) as f:
        data = yaml.safe_load(f)
    return data.get("intents", [])


def get_intent_status(intent_id: str) -> str | None:
    """Return the status string for a specific intent, or None if not found."""
    for intent in load_intent_registry():
        if intent.get("id") == intent_id:
            return intent.get("status")
    return None


def sorted_by_priority(intents: list[dict]) -> list[dict]:
    """Sort intents by category → risk → complexity (all ascending)."""
    def sort_key(i):
        cat  = CATEGORY_ORDER.get(i.get("category", "idea"), 99)
        risk = RISK_ORDER.get(i.get("risk", "high"), 99)
        comp = COMPLEXITY_ORDER.get(i.get("complexity", "very_high"), 99)
        return (cat, risk, comp)

    return sorted(intents, key=sort_key)


def select_next_intent(thinkpad_online: bool = False) -> tuple[dict | None, list[dict]]:
    """Select the best autonomous intent and collect intents needing notification.

    Scans ALL intents in priority order.  Returns:
      (selected_intent | None, needs_notification_list)

    selected_intent        — first autonomous, dependency-met, pending intent; or None.
    needs_notification_list — pending intents with autonomous=false that are ready
                              to execute but need human approval.  Deduped: each intent
                              is included at most once per 24 h (or on status change).
    """
    intents      = load_intent_registry()
    ordered      = sorted_by_priority(intents)
    id_to_status = {i["id"]: i.get("status", "pending") for i in intents}

    selected:   dict | None = None
    to_notify:  list[dict]  = []
    notif_state = _load_notif_state()
    now         = datetime.now(timezone.utc)
    state_dirty = False

    for intent in ordered:
        status   = intent.get("status", "pending")
        category = intent.get("category", "idea")

        if status in SKIP_STATUSES:
            continue
        if category == "idea":
            continue

        # All dependencies must be completed or decomposed
        # (decomposed = done; replaced by sub-tasks, counts as satisfied)
        deps  = intent.get("depends_on", []) or []
        unmet = [d for d in deps
                 if id_to_status.get(d) not in ("completed", "decomposed")]
        if unmet:
            continue

        # Tier-1-only intents require the ThinkPad to be online
        if intent.get("tier1_required", False) and not thinkpad_online:
            continue

        # Intent is actionable — route it
        if intent.get("autonomous", True):
            if selected is None:
                selected = intent
            # Keep scanning so we collect all non-autonomous intents for notification
        else:
            # Check dedup: skip if we notified recently and status hasn't changed
            iid       = intent["id"]
            prev      = notif_state.get(iid, {})
            prev_ts   = prev.get("timestamp", "")
            prev_stat = prev.get("status", "")

            should_send = False
            if prev_stat != status:
                should_send = True
            elif prev_ts:
                try:
                    age = (now - datetime.fromisoformat(prev_ts)).total_seconds()
                    should_send = age > 86400  # re-notify after 24 h
                except ValueError:
                    should_send = True
            else:
                should_send = True

            if should_send:
                to_notify.append(intent)
                notif_state[iid] = {"status": status, "timestamp": now.isoformat()}
                state_dirty = True

    if state_dirty:
        _save_notif_state(notif_state)

    return (selected, to_notify)


def update_intent_status(intent_id: str, new_status: str) -> bool:
    """Update the status field for one intent. Only the status field is touched.

    Valid transitions:
      pending     → in_progress | blocked
      in_progress → completed   | failed
      blocked     → pending
    """
    current = get_intent_status(intent_id)
    if current is None:
        return False

    allowed = VALID_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        return False

    with open(INTENT_REGISTRY_PATH) as f:
        content = f.read()

    # Find the start of this intent's block.
    # Handles both YAML styles:
    #   original intents:   ^- id: ns-004.1        (no indent, unquoted)
    #   decomposed intents: ^  - id: "ns-004.1"    (2-space indent, quoted)
    id_re = re.compile(
        r'^\s*- id:\s*["\']?' + re.escape(intent_id) + r'["\']?\s*$',
        re.MULTILINE,
    )
    m = id_re.search(content)
    if not m:
        return False

    # Find the end of this block (next `- id:` entry, any indentation, or EOF)
    next_entry = re.search(r'\n\s*- id:', content[m.end():])
    block_end  = m.end() + next_entry.start() if next_entry else len(content)

    block = content[m.start():block_end]

    # Replace only the status line within this block, preserving its indentation.
    # Handles both `  status: x` (2-space) and `    status: x` (4-space).
    new_block = re.sub(
        r'^([ \t]*)status: \S+',
        rf'\g<1>status: {new_status}',
        block,
        flags=re.MULTILINE,
        count=1,
    )
    if new_block == block:
        return False

    with open(INTENT_REGISTRY_PATH, "w") as f:
        f.write(content[:m.start()] + new_block + content[block_end:])

    return True


def _intent_to_yaml_block(intent: dict) -> str:
    """Serialize an intent dict to YAML lines matching the registry format.

    Uses 0-indent for the list item marker and 2-indent for fields — the same
    format as all other entries in intent_registry.yaml.  This makes appended
    sub-intents valid siblings in the top-level intents: sequence.
    """
    iid   = intent["id"]
    title = intent.get("title", f"Sub-task {iid}").replace('"', '\\"')
    desc  = intent.get("description", "").replace("\n", " ").strip()[:400]
    cat   = intent.get("category", "next_step")
    risk  = intent.get("risk", "medium")
    comp  = intent.get("complexity", "medium")
    auto  = "true" if intent.get("autonomous", True) else "false"
    deps  = intent.get("depends_on", []) or []
    crits = intent.get("acceptance_criteria", []) or []
    files = intent.get("affected_files", []) or []

    lines: list[str] = []
    lines.append(f'- id: {iid}')
    lines.append(f'  title: "{title}"')
    if desc:
        lines.append( '  description: >')
        lines.append(f'    {desc}')
    else:
        lines.append( '  description: ""')
    lines.append(f'  category: {cat}')
    lines.append( '  status: pending')
    lines.append(f'  risk: {risk}')
    lines.append(f'  complexity: {comp}')
    lines.append(f'  autonomous: {auto}')
    if deps:
        lines.append('  depends_on:')
        for d in deps:
            lines.append(f'  - "{d}"')
    else:
        lines.append('  depends_on: []')
    if crits:
        lines.append('  acceptance_criteria:')
        for c in crits:
            c_s = str(c).replace('"', '\\"')
            lines.append(f'  - "{c_s}"')
    else:
        lines.append('  acceptance_criteria: []')
    if files:
        lines.append('  affected_files:')
        for ff in files:
            ff_s = str(ff) if isinstance(ff, dict) else ff
            lines.append(f'  - {ff_s}')
    else:
        lines.append('  affected_files: []')
    return "\n".join(lines)


def decompose_intent(parent_intent: dict, sub_tasks: list[dict]) -> list[dict]:
    """Break a parent intent into ordered sub-intents and write them to the registry.

    sub_tasks — list of dicts from the plan's decomposition array.  Each should have:
        title, description, acceptance_criteria, affected_files, risk, complexity.

    Sub-intent IDs are '<parent_id>.1', '<parent_id>.2', etc.
    Each sub-intent depends on the previous one (sequential chain).
    Parent intent is transitioned to 'decomposed' (must currently be 'in_progress').

    Returns the list of sub-intent dicts that were appended.
    """
    # Hard cap: never decompose deeper than 2 levels
    MAX_DECOMPOSE_DEPTH = 2
    current_depth = parent_intent["id"].count(".")
    if current_depth >= MAX_DECOMPOSE_DEPTH:
        log.warning("Depth limit (%d) reached for %s — forcing direct execution",
                    MAX_DECOMPOSE_DEPTH, parent_intent["id"])
        return []

    parent_id = parent_intent["id"]

    sub_intents: list[dict] = []
    for idx, task in enumerate(sub_tasks, 1):
        sub_id = f"{parent_id}.{idx}"
        sub = {
            "id":                   sub_id,
            "title":                str(task.get("title", f"Sub-task {idx} of {parent_id}"))[:120],
            "description":          str(task.get("description", ""))[:400],
            "category":             parent_intent.get("category", "next_step"),
            "risk":                 str(task.get("risk", parent_intent.get("risk", "medium"))),
            "complexity":           str(task.get("complexity", parent_intent.get("complexity", "medium"))),
            "autonomous":           bool(task.get("autonomous", parent_intent.get("autonomous", True))),
            "depends_on":           [f"{parent_id}.{idx - 1}"] if idx > 1 else [],
            "acceptance_criteria":  list(task.get("acceptance_criteria", [])),
            "affected_files":       list(task.get("affected_files", [])),
        }
        sub_intents.append(sub)

    # Append sub-intent YAML blocks to the registry file
    with open(INTENT_REGISTRY_PATH) as fh:
        content = fh.read()

    additions = "\n" + "\n".join(_intent_to_yaml_block(s) for s in sub_intents) + "\n"

    with open(INTENT_REGISTRY_PATH, "w") as fh:
        fh.write(content.rstrip() + additions)

    # Transition parent → decomposed
    update_intent_status(parent_id, "decomposed")

    return sub_intents


def update_intent_autonomous(intent_id: str, autonomous: bool) -> bool:
    """Set the autonomous flag for one intent in the registry.

    Returns True if the change was written.  Returns False if the intent was not
    found or the autonomous field is missing from its YAML block.
    """
    with open(INTENT_REGISTRY_PATH) as f:
        content = f.read()

    # Handles both YAML styles:
    #   original intents:   ^- id: ns-004.1        (no indent, unquoted)
    #   decomposed intents: ^  - id: "ns-004.1"    (2-space indent, quoted)
    id_re = re.compile(
        r'^\s*- id:\s*["\']?' + re.escape(intent_id) + r'["\']?\s*$',
        re.MULTILINE,
    )
    m = id_re.search(content)
    if not m:
        return False

    next_entry = re.search(r'\n\s*- id:', content[m.end():])
    block_end  = m.end() + next_entry.start() if next_entry else len(content)
    block      = content[m.start():block_end]

    val       = "true" if autonomous else "false"
    new_block = re.sub(
        r'^([ \t]*)autonomous: \S+',
        rf'\g<1>autonomous: {val}',
        block,
        flags=re.MULTILINE,
        count=1,
    )
    if new_block == block:
        return False

    with open(INTENT_REGISTRY_PATH, "w") as f:
        f.write(content[:m.start()] + new_block + content[block_end:])
    return True


def remove_as_dependency(dep_id: str) -> int:
    """Remove dep_id from every depends_on list in the registry.

    Called when an intent is skipped so its downstream dependents are unblocked.
    Fixes up any orphaned 'depends_on:' with no remaining items.
    Returns the count of intent blocks that were modified.
    """
    with open(INTENT_REGISTRY_PATH) as f:
        content = f.read()

    # Remove lines of the form:  '      - "<dep_id>"'
    pattern = re.compile(r'^      - "' + re.escape(dep_id) + r'"\n', re.MULTILINE)
    count = len(pattern.findall(content))
    new_content = pattern.sub("", content)

    # An orphaned 'depends_on:' with no following list items (next line is a peer field)
    # becomes 'depends_on: []'
    new_content = re.sub(
        r"(    depends_on:)\n(?=    \w)",
        r"\1 []\n",
        new_content,
        flags=re.MULTILINE,
    )

    if new_content != content:
        with open(INTENT_REGISTRY_PATH, "w") as f:
            f.write(new_content)

    return count


def check_decomposed_complete(parent_id: str) -> bool:
    """Return True if all direct sub-intents of parent_id are completed."""
    intents = load_intent_registry()
    prefix  = f"{parent_id}."
    sub_ids = [i["id"] for i in intents if i["id"].startswith(prefix)]
    if not sub_ids:
        return False
    id_to_status = {i["id"]: i.get("status", "pending") for i in intents}
    return all(id_to_status.get(sid) == "completed" for sid in sub_ids)


def generate_follow_up_intents(
    completed_intent: dict,
    execution_result: dict,
) -> list[dict]:
    """After a successful task, use Tier 2 LLM to suggest 0-3 follow-up intents.

    New intents are appended to the registry with IDs '<parent_id>-f1', '-f2', etc.,
    category matching the parent, autonomous=True, depends_on=[parent_id].
    Returns the list of added intent dicts (empty list on failure or no suggestions).
    Only runs on successful executions — failed tasks don't get follow-ups.
    """
    parent_id = completed_intent.get("id", "")
    if not parent_id:
        return []

    if not execution_result.get("success", False):
        return []

    # Avoid generating follow-ups for follow-up intents (prevents runaway chains)
    if "-f" in parent_id:
        return []

    try:
        from llm_router import route_llm_call  # lazy — avoids circular import
    except ImportError:
        return []

    prompt = (
        f"You just completed this task:\n"
        f"Title: {completed_intent.get('title', '')}\n"
        f"Description: {completed_intent.get('description', '')[:300]}\n\n"
        "Are there immediate follow-up tasks that should be done?\n"
        "Consider: testing, documentation, integration with other components, cleanup.\n"
        "Only suggest tasks that are concrete and actionable right now.\n"
        "Respond ONLY with JSON — no markdown, no explanation:\n"
        "{\"follow_ups\": ["
        "{\"title\": \"short title\", \"description\": \"what to do\", "
        "\"complexity\": \"low\", \"risk\": \"low\"}"
        "]}\n"
        "If no follow-ups are needed, respond: {\"follow_ups\": []}"
    )

    result = route_llm_call(
        "classify",
        "You are a task planner. Respond only with valid JSON.",
        prompt,
    )

    if result.get("error") or not result.get("response"):
        return []

    try:
        import re as _re
        raw = result["response"]
        raw = _re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
        m   = _re.search(r"\{.*\}", raw, _re.DOTALL)
        if not m:
            return []
        data      = json.loads(m.group())
        follow_ups = [f for f in data.get("follow_ups", []) if isinstance(f, dict)]
    except Exception:
        return []

    if not follow_ups:
        return []

    follow_ups = follow_ups[:3]  # cap at 3

    new_intents: list[dict] = []
    for idx, fu in enumerate(follow_ups, 1):
        fu_id = f"{parent_id}-f{idx}"
        sub   = {
            "id":                  fu_id,
            "title":               str(fu.get("title", f"Follow-up {idx} for {parent_id}"))[:120],
            "description":         str(fu.get("description", ""))[:400],
            "category":            completed_intent.get("category", "next_step"),
            "risk":                str(fu.get("risk", "low")),
            "complexity":          str(fu.get("complexity", "low")),
            "autonomous":          True,
            "depends_on":          [parent_id],
            "acceptance_criteria": list(fu.get("acceptance_criteria", [])),
            "affected_files":      list(fu.get("affected_files", [])),
        }
        new_intents.append(sub)

    # Append YAML blocks to the registry
    with open(INTENT_REGISTRY_PATH) as fh:
        content = fh.read()

    additions = "\n" + "\n".join(_intent_to_yaml_block(s) for s in new_intents) + "\n"

    with open(INTENT_REGISTRY_PATH, "w") as fh:
        fh.write(content.rstrip() + additions)

    return new_intents


def get_active_intents(n: int = 5) -> str:
    """Return a formatted string of the top n pending/in_progress intents for context injection."""
    intents = load_intent_registry()
    active  = [i for i in intents if i.get("status") in ("pending", "in_progress")]
    ordered = sorted_by_priority(active)[:n]

    if not ordered:
        return "No active intents."

    lines = []
    for i in ordered:
        status = i.get("status", "?")
        cat    = i.get("category", "?")
        lines.append(
            f"[{status.upper()}] {i['id']} ({cat}): {i['title']}\n"
            f"  {i.get('description', '')[:120].strip()}"
        )
    return "\n\n".join(lines)
