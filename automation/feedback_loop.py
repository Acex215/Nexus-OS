#!/usr/bin/env python3
"""NEXUS OS CAF — Feedback Loop

Closes the learning loop: after every task execution this module performs
structured analysis, stores lessons, and updates the change ledger.
Lessons are fed back into future context packets via get_relevant_lessons().

Public API:
    analyze_task_result(intent, plan, execution_result, context_packet) -> dict
    store_lesson(analysis, intent)                -> None
    write_change_ledger_entry(intent, plan, result) -> None
    get_relevant_lessons(task_description, n)     -> list[dict]
    get_improvement_stats()                       -> dict
"""

import hashlib
import json
import logging
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from llm_router import route_llm_call

log = logging.getLogger("feedback_loop")

DB_PATH       = "/mnt/nexus-nas/knowledge/world_model.db"
LEDGER_PATH   = Path("/opt/nexus/automation/change_ledger.md")

# ── LLM analysis prompts ───────────────────────────────────────────────────────

_ANALYSIS_SYSTEM = """\
You are analyzing the result of an automated task execution. Given the intent, \
plan, execution result, and context that was used, provide a structured analysis.
Respond ONLY with valid JSON:
{
  "outcome": "success|failure|partial",
  "root_cause": "For failures: what went wrong. For success: what key factor enabled it.",
  "useful_context": "Which pieces of the context packet were actually helpful for this task",
  "missing_context": "What information was needed but not available in the context",
  "resolution": "For failures: what would fix it. For success: any improvements possible.",
  "tags": ["relevant", "tags", "for", "categorization"],
  "improvement_suggestions": [
    "Specific suggestion 1 for improving future similar tasks",
    "Specific suggestion 2"
  ],
  "retrieval_quality": "good|adequate|poor",
  "plan_quality": "good|adequate|poor",
  "should_retry": false
}\
"""


def _strip_json(raw: str) -> str:
    cleaned = re.sub(r'```(?:json)?\s*', '', raw).strip().rstrip('`').strip()
    m = re.search(r'\{.*\}', cleaned, re.DOTALL)
    return m.group() if m else ""


def _fallback_analysis(execution_result: dict) -> dict:
    """Minimal analysis when LLM is unavailable."""
    success = execution_result.get("success", False)
    err     = execution_result.get("error", "")
    return {
        "outcome":                "success" if success else "failure",
        "root_cause":             "" if success else (err[:200] or "unknown error"),
        "useful_context":         "unavailable (LLM offline)",
        "missing_context":        "",
        "resolution":             "" if success else "Check step stderr output",
        "tags":                   ["llm_offline"],
        "improvement_suggestions": [],
        "retrieval_quality":      "unknown",
        "plan_quality":           "unknown",
        "should_retry":           False,
    }


# ── Public API ─────────────────────────────────────────────────────────────────

def analyze_task_result(
    intent: dict,
    plan: dict,
    execution_result: dict,
    context_packet: str,
) -> dict:
    """Run LLM post-task analysis. Returns structured analysis dict.

    Falls back to a heuristic analysis if all LLM tiers are offline.
    """
    success       = execution_result.get("success", False)
    failed_step   = execution_result.get("failed_step")
    steps_done    = execution_result.get("steps_completed", 0)
    branch        = execution_result.get("branch", "")
    err           = execution_result.get("error", "")

    # Build compact step result summary
    outputs = execution_result.get("outputs", [])
    step_lines: list[str] = []
    for i, out in enumerate(outputs[:8]):   # cap at 8 steps in prompt
        rc    = out.get("returncode", "?")
        etype = "✅" if rc == 0 else "❌"
        step_lines.append(
            f"  Step {i+1}: {etype} rc={rc}  "
            f"stdout={out.get('stdout','')[:120]!r}  "
            f"stderr={out.get('stderr','')[:80]!r}"
        )

    user_prompt = (
        f"Intent ID: {intent.get('id', '?')}\n"
        f"Title: {intent.get('title', '')}\n"
        f"Description: {intent.get('description', '')[:300]}\n\n"
        f"Plan summary: {plan.get('summary', '')}\n"
        f"Steps planned: {len(plan.get('steps', []))}\n"
        f"Confidence: {plan.get('confidence', '?')}\n"
        f"Risk: {plan.get('risk_assessment', '?')}\n\n"
        f"Execution outcome: {'SUCCESS' if success else 'FAILURE'}\n"
        f"Steps completed: {steps_done}/{len(plan.get('steps', []))}\n"
        + (f"Failed at step: {failed_step}\n" if failed_step else "")
        + (f"Error: {err[:300]}\n" if err else "")
        + "\nStep results:\n"
        + "\n".join(step_lines)
        + "\n\nContext packet used (first 3000 chars):\n"
        + context_packet[:3000]
        + "\n\nProvide your structured analysis."
    )

    result = route_llm_call("analyze_code", _ANALYSIS_SYSTEM, user_prompt)

    if result.get("error") or not result.get("response"):
        log.info("analyze_task_result: LLM unavailable — using fallback analysis")
        return _fallback_analysis(execution_result)

    blob = _strip_json(result["response"])
    if not blob:
        return _fallback_analysis(execution_result)

    try:
        analysis = json.loads(blob)
    except json.JSONDecodeError:
        return _fallback_analysis(execution_result)

    # Normalise and type-check fields
    return {
        "outcome":                str(analysis.get("outcome", "failure"))[:20],
        "root_cause":             str(analysis.get("root_cause", ""))[:500],
        "useful_context":         str(analysis.get("useful_context", ""))[:500],
        "missing_context":        str(analysis.get("missing_context", ""))[:500],
        "resolution":             str(analysis.get("resolution", ""))[:500],
        "tags":                   list(analysis.get("tags", []))[:20],
        "improvement_suggestions": list(analysis.get("improvement_suggestions", []))[:5],
        "retrieval_quality":      str(analysis.get("retrieval_quality", "unknown"))[:20],
        "plan_quality":           str(analysis.get("plan_quality", "unknown"))[:20],
        "should_retry":           bool(analysis.get("should_retry", False)),
    }


def store_lesson(analysis: dict, intent: dict) -> None:
    """Persist analysis as a lesson in world_model.db and ChromaDB."""
    intent_id = intent.get("id", "unknown")

    # Augment tags with quality metrics so get_improvement_stats can aggregate them
    tags = list(analysis.get("tags", []))
    rq = analysis.get("retrieval_quality", "")
    pq = analysis.get("plan_quality", "")
    if rq:
        tags.append(f"retrieval:{rq}")
    if pq:
        tags.append(f"plan:{pq}")

    # ── SQLite ────────────────────────────────────────────────────────────────
    try:
        db = sqlite3.connect(DB_PATH)
        db.execute("""
            INSERT INTO lessons
                (timestamp, intent_id, outcome, root_cause,
                 useful_context, missing_context, resolution, tags_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(timezone.utc).isoformat(),
            intent_id,
            analysis.get("outcome", ""),
            analysis.get("root_cause", ""),
            analysis.get("useful_context", ""),
            analysis.get("missing_context", ""),
            analysis.get("resolution", ""),
            json.dumps(tags),
        ))
        db.commit()
        db.close()
        log.info("store_lesson: lesson stored for intent %s", intent_id)
    except sqlite3.Error as e:
        log.warning("store_lesson: DB write failed: %s", e)

    # ── ChromaDB ──────────────────────────────────────────────────────────────
    outcome   = analysis.get("outcome", "failure")
    col_name  = "nexus_failures" if outcome != "success" else "nexus_decisions"
    doc_text  = (
        f"Intent: {intent_id} — {intent.get('title', '')}\n"
        f"Outcome: {outcome}\n"
        f"Root cause: {analysis.get('root_cause', '')}\n"
        f"Resolution: {analysis.get('resolution', '')}\n"
        f"Tags: {', '.join(tags)}"
    )
    doc_id = "lesson_" + hashlib.sha256(
        f"{intent_id}{datetime.utcnow().isoformat()}".encode()
    ).hexdigest()[:16]

    try:
        import chromadb
        client = chromadb.HttpClient(host="localhost", port=8000)
        col    = client.get_or_create_collection(col_name)
        col.upsert(
            ids=[doc_id],
            documents=[doc_text],
            metadatas=[{
                "intent_id": intent_id,
                "outcome":   outcome,
                "tags":      json.dumps(tags[:10]),
            }],
        )
        log.info("store_lesson: stored in ChromaDB collection %s", col_name)
    except Exception as e:
        log.warning("store_lesson: ChromaDB write failed: %s", e)


def write_change_ledger_entry(
    intent: dict,
    plan: dict,
    execution_result: dict,
) -> None:
    """Append a PR-style entry to change_ledger.md."""
    ts           = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    intent_id    = intent.get("id", "unknown")
    title        = intent.get("title", "untitled")
    success      = execution_result.get("success", False)
    branch       = execution_result.get("branch", "N/A")
    files_created  = plan.get("files_created", []) or []
    files_modified = plan.get("files_modified", []) or []
    steps_done   = execution_result.get("steps_completed", 0)
    steps_total  = len(plan.get("steps", []))
    confidence   = plan.get("confidence", "?")
    resolution   = execution_result.get("error", "") or plan.get("summary", "")

    status_icon  = "✅ Completed" if success else "❌ Failed"

    # Fetch the stored lesson for this intent (most recent)
    lesson_text  = ""
    try:
        db  = sqlite3.connect(DB_PATH)
        row = db.execute(
            "SELECT outcome, root_cause, resolution FROM lessons "
            "WHERE intent_id=? ORDER BY timestamp DESC LIMIT 1",
            (intent_id,),
        ).fetchone()
        db.close()
        if row:
            outcome, root_cause, resolution_text = row
            lesson_text = resolution_text or root_cause or ""
    except Exception:
        pass

    if not lesson_text:
        lesson_text = resolution[:200] if resolution else "No lesson recorded."

    # Format file lists
    fc_str = ", ".join(Path(f).name for f in files_created)  or "(none)"
    fm_str = ", ".join(Path(f).name for f in files_modified) or "(none)"

    entry = (
        f"\n## [{ts}] Intent: {intent_id} — {title}\n\n"
        f"**Status:** {status_icon}  \n"
        f"**Branch:** `{branch}`  \n"
        f"**Files created:** {fc_str}  \n"
        f"**Files modified:** {fm_str}  \n"
        f"**Steps:** {steps_done}/{steps_total} completed  \n"
        f"**Confidence:** {confidence}  \n"
        f"**Lesson:** {lesson_text[:300]}\n\n"
        f"---\n"
    )

    try:
        LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LEDGER_PATH, "a") as f:
            f.write(entry)
        log.info("write_change_ledger_entry: appended entry for %s", intent_id)
    except Exception as e:
        log.warning("write_change_ledger_entry: write failed: %s", e)


def get_relevant_lessons(task_description: str, n: int = 3) -> list[dict]:
    """Query lessons table for entries relevant to the current task.

    Scoring:
      +2 — any task keyword found in lesson tags
      +1 — keyword match in root_cause or resolution text
      Recency tie-break: most recent lessons preferred.

    Returns top n lessons as dicts, most relevant first.
    """
    try:
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT * FROM lessons ORDER BY timestamp DESC LIMIT 50"
        ).fetchall()
        db.close()
    except sqlite3.Error as e:
        log.debug("get_relevant_lessons: DB error: %s", e)
        return []

    if not rows:
        return []

    # Extract task keywords (words > 3 chars)
    keywords = [
        w for w in re.split(r'\W+', task_description.lower())
        if len(w) > 3
    ][:10]

    scored: list[tuple[int, dict]] = []
    for row in rows:
        lesson = dict(row)
        score  = 0
        try:
            tags = json.loads(lesson.get("tags_json") or "[]")
        except json.JSONDecodeError:
            tags = []

        # Tag overlap
        tag_text = " ".join(str(t).lower() for t in tags)
        for kw in keywords:
            if kw in tag_text:
                score += 2
                break

        # Text match in root_cause / resolution
        text_blob = (
            (lesson.get("root_cause") or "")
            + " "
            + (lesson.get("resolution") or "")
        ).lower()
        for kw in keywords:
            if kw in text_blob:
                score += 1
                break

        if score > 0:
            lesson["_score"] = score
            scored.append((score, lesson))

    # Sort: primary = score desc, secondary = timestamp desc (already ordered)
    scored.sort(key=lambda x: x[0], reverse=True)
    return [lesson for _, lesson in scored[:n]]


def get_improvement_stats() -> dict:
    """Return aggregate statistics from the lessons table."""
    try:
        db = sqlite3.connect(DB_PATH)
        rows = db.execute("SELECT * FROM lessons ORDER BY timestamp DESC").fetchall()
        db.close()
    except sqlite3.Error as e:
        log.debug("get_improvement_stats: DB error: %s", e)
        return {"error": str(e)}

    total   = len(rows)
    if total == 0:
        return {
            "total_tasks":              0,
            "success_rate":             0.0,
            "common_failure_causes":    [],
            "most_useful_context_types": [],
            "avg_retrieval_quality":    "unknown",
            "avg_plan_quality":         "unknown",
            "lessons_stored":           0,
        }

    outcomes   = [r[3] for r in rows]   # outcome column index 3
    successes  = sum(1 for o in outcomes if o == "success")
    root_causes = [r[4] for r in rows if r[3] != "success" and r[4]]

    # Extract top failure cause keywords
    cause_words: list[str] = []
    for cause in root_causes[:20]:
        words = re.split(r'\W+', cause.lower())
        cause_words.extend(w for w in words if len(w) > 4)
    common_causes = [w for w, _ in Counter(cause_words).most_common(5)]

    # Useful context types
    useful_texts = [r[5] for r in rows if r[5]]   # useful_context column
    ctx_words: list[str] = []
    for text in useful_texts[:20]:
        for keyword in ["code_chunks", "nexus_failures", "nexus_decisions",
                        "session_transcripts", "infra_configs", "web_research"]:
            if keyword in text:
                ctx_words.append(keyword)
    most_useful = [w for w, _ in Counter(ctx_words).most_common(3)]

    # Quality averages from tags
    ret_quals: list[str] = []
    plan_quals: list[str] = []
    for row in rows:
        try:
            tags = json.loads(row[8] or "[]")   # tags_json column
        except (json.JSONDecodeError, TypeError):
            tags = []
        for tag in tags:
            if isinstance(tag, str) and tag.startswith("retrieval:"):
                ret_quals.append(tag.split(":", 1)[1])
            elif isinstance(tag, str) and tag.startswith("plan:"):
                plan_quals.append(tag.split(":", 1)[1])

    avg_rq = Counter(ret_quals).most_common(1)[0][0] if ret_quals else "unknown"
    avg_pq = Counter(plan_quals).most_common(1)[0][0] if plan_quals else "unknown"

    return {
        "total_tasks":               total,
        "success_rate":              round(successes / total, 2),
        "common_failure_causes":     common_causes,
        "most_useful_context_types": most_useful,
        "avg_retrieval_quality":     avg_rq,
        "avg_plan_quality":          avg_pq,
        "lessons_stored":            total,
    }
