#!/usr/bin/env python3
"""
NEXUS CAF Three-Tier Memory System
===================================
Provides context packets for LLM prompts assembled from three tiers:

  Tier 0 — Constitutional memory (always present, ~600 tokens)
            Loaded from constitution.json: identity, principles, cluster topology,
            protected files. Never truncated.

  Tier 1 — Working memory (~2000-4000 tokens)
            Task-specific ChromaDB semantic search results, world model module
            info, recent failures, and relevant lessons.

  Tier 2 — Background memory (~1000-2000 tokens)
            Secondary collection results and cross-references.

The total packet is capped at MAX_CONTEXT_CHARS to stay within LLM context limits.

Public API:
    build_context_packet(task_description, task_type=None, affected_files=None) -> str
    classify_task(task_description) -> str
    load_constitution() -> str
"""

import json
import logging
import re
import sqlite3
import warnings
from pathlib import Path
from typing import Optional

warnings.filterwarnings("ignore")

log = logging.getLogger("context_builder")

# ── Paths ─────────────────────────────────────────────────────────────────────

AUTOMATION_DIR   = Path(__file__).parent
CONSTITUTION_PATH = AUTOMATION_DIR / "constitution.json"
WORLD_MODEL_PATH  = Path("/mnt/nexus-nas/knowledge/world_model.db")

CHROMA_HOST = "localhost"
CHROMA_PORT = 8000

# Approx 7000 tokens × 4 chars/token
MAX_CONTEXT_CHARS = 28_000
# Constitutional block is always preserved — never count against the limit
CONSTITUTION_RESERVE = 3_000

# ── Retrieval profiles ────────────────────────────────────────────────────────

RETRIEVAL_PROFILES: dict[str, dict] = {
    "code_change": {
        "primary":    ["code_chunks"],
        "secondary":  ["nexus_decisions"],
        "world_model": True,
        "lessons":     True,
    },
    "config_change": {
        "primary":    ["infra_configs", "code_chunks"],
        "secondary":  ["nexus_failures"],
        "world_model": True,
        "lessons":     True,
    },
    "new_feature": {
        "primary":    ["docs_chunks", "session_transcripts"],
        "secondary":  ["code_chunks", "nexus_decisions"],
        "world_model": True,
        "lessons":     True,
    },
    "bug_fix": {
        "primary":    ["code_chunks", "nexus_failures"],
        "secondary":  ["infra_configs"],
        "world_model": True,
        "lessons":     True,
    },
    "research": {
        "primary":    ["docs_chunks", "web_research"],
        "secondary":  ["session_transcripts"],
        "world_model": False,
        "lessons":     False,
    },
    "health_check": {
        "primary":    ["infra_configs"],
        "secondary":  [],
        "world_model": True,
        "lessons":     False,
    },
}

# ── Task classifier (keyword heuristic, no LLM) ───────────────────────────────

_CLASSIFY_RULES: list[tuple[list[str], str]] = [
    (["fix", "bug", "error", "broken", "fail", "crash", "traceback", "exception",
      "wrong", "incorrect", "not working"],           "bug_fix"),
    (["config", "systemd", "iptables", "firewall", "mount", "service",
      "timer", "unit", "network", "vlan", "route"],   "config_change"),
    (["research", "investigate", "explore", "learn", "study",
      "document", "explain", "understand"],            "research"),
    (["health", "status", "check", "monitor", "ping",
      "verify", "validate", "inspect"],                "health_check"),
    (["add", "create", "implement", "new", "feature", "build",
      "write", "develop", "introduce"],                "new_feature"),
]


def classify_task(task_description: str) -> str:
    """
    Classify a task description into one of the RETRIEVAL_PROFILES keys
    using a fast keyword heuristic (no LLM call).

    Uses word-boundary matching so e.g. "route" won't fire on "blockchain_router".
    """
    lowered = task_description.lower()
    for keywords, task_type in _CLASSIFY_RULES:
        if any(re.search(r'\b' + re.escape(kw) + r'\b', lowered) for kw in keywords):
            return task_type
    return "code_change"


# ── Constitutional memory (Tier 0) ────────────────────────────────────────────

def load_constitution() -> str:
    """
    Read constitution.json and format as a compact, LLM-ready string.
    Returns a stable ~600-token block covering identity, principles,
    cluster topology, and protected files.
    """
    try:
        data = json.loads(CONSTITUTION_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.warning("constitution.json not found at %s", CONSTITUTION_PATH)
        return "# CONSTITUTIONAL MEMORY\n[constitution.json missing — re-run setup]\n"
    except json.JSONDecodeError as e:
        log.error("constitution.json is malformed: %s", e)
        return "# CONSTITUTIONAL MEMORY\n[constitution.json parse error]\n"

    lines = ["# CONSTITUTIONAL MEMORY (Tier 0 — always present)"]
    lines.append(f"\n## Identity\n{data.get('identity', '')}")

    principles = data.get("principles", [])
    lines.append("\n## Core Principles")
    for i, p in enumerate(principles, 1):
        lines.append(f"  {i}. {p}")

    cluster = data.get("cluster", {})
    nodes   = cluster.get("nodes", {})
    lines.append("\n## Cluster Topology")
    lines.append(f"  Chain ID: {cluster.get('chain_id', '?')}  |  Block period: {cluster.get('block_period', '?')}")
    for node_name, info in nodes.items():
        lines.append(f"  {node_name:<15} {info.get('ip','?'):<13} {info.get('role','')}")

    contracts = cluster.get("contracts", {})
    if contracts:
        lines.append("\n## Key Contract Addresses")
        for name, addr in contracts.items():
            lines.append(f"  {name}: {addr}")

    protected = data.get("protected_files", [])
    lines.append("\n## Protected Files (NEVER auto-modify)")
    for pf in protected:
        lines.append(f"  {pf}")

    lines.append(f"\n## Purpose\n  {data.get('purpose', '')}")
    lines.append(f"\n## Founder\n  {data.get('founder', '')}")

    return "\n".join(lines)


# ── ChromaDB search (Tier 1 / Tier 2) ────────────────────────────────────────

_chroma_client = None


def _get_chroma():
    global _chroma_client
    if _chroma_client is None:
        import chromadb
        _chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    return _chroma_client


def chroma_search(collection_name: str, query: str, n: int = 5) -> list[tuple[str, dict]]:
    """
    Search a ChromaDB collection semantically.
    Returns a list of (document_text, metadata) tuples, empty list on any error.
    """
    try:
        client = _get_chroma()
        col = client.get_collection(collection_name)
        if col.count() == 0:
            return []
        actual_n = min(n, col.count())
        results  = col.query(
            query_texts=[query],
            n_results=actual_n,
            include=["documents", "metadatas"],
        )
        docs  = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        return list(zip(docs, metas))
    except Exception as e:
        log.debug("chroma_search(%s, %r): %s", collection_name, query[:40], e)
        return []


# ── World model queries ───────────────────────────────────────────────────────

def query_world_model(file_path: str) -> Optional[dict]:
    """
    Look up a module in world_model.db by exact or partial path match.
    Returns a dict with module info and its dependencies, or None if not found.
    """
    if not WORLD_MODEL_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(str(WORLD_MODEL_PATH))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM modules WHERE path=? OR path LIKE ?",
            (file_path, f"%{Path(file_path).name}%")
        ).fetchone()
        if row is None:
            conn.close()
            return None
        info = dict(row)
        # Fetch symbols
        syms = conn.execute(
            "SELECT name, symbol_type, signature, is_public FROM symbols WHERE module_id=? ORDER BY line_number",
            (info["id"],)
        ).fetchall()
        info["symbols"] = [dict(s) for s in syms]
        # Parse deps json
        if info.get("dependencies_json"):
            try:
                info["dependencies"] = json.loads(info["dependencies_json"])
            except json.JSONDecodeError:
                info["dependencies"] = []
        conn.close()
        return info
    except sqlite3.Error as e:
        log.debug("query_world_model(%s): %s", file_path, e)
        return None


def get_recent_failures(n: int = 3) -> list[tuple[str, dict]]:
    """Get the n most recent entries from the nexus_failures collection."""
    return chroma_search("nexus_failures", "failure error crash", n=n)


def get_lessons(task_description: str, n: int = 2) -> list[dict]:
    """
    Query world_model.db lessons table for entries relevant to the task.
    Simple keyword match on outcome, root_cause, resolution fields.
    """
    if not WORLD_MODEL_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(str(WORLD_MODEL_PATH))
        conn.row_factory = sqlite3.Row
        # Extract first few meaningful words for a lightweight search
        words = [w for w in re.split(r'\W+', task_description.lower()) if len(w) > 3][:6]
        if not words:
            conn.close()
            return []
        conditions = " OR ".join(
            ["outcome LIKE ? OR root_cause LIKE ? OR resolution LIKE ?"] * len(words)
        )
        params = []
        for w in words:
            params.extend([f"%{w}%", f"%{w}%", f"%{w}%"])
        rows = conn.execute(
            f"SELECT * FROM lessons WHERE {conditions} ORDER BY timestamp DESC LIMIT ?",
            params + [n]
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except sqlite3.Error as e:
        log.debug("get_lessons: %s", e)
        return []


# ── Context assembly ──────────────────────────────────────────────────────────

def _format_chroma_results(results: list[tuple[str, dict]], label: str,
                            max_chars_each: int = 800) -> str:
    if not results:
        return ""
    lines = [f"\n### {label}"]
    for i, (doc, meta) in enumerate(results, 1):
        # Key metadata fields in a compact header line
        fp   = meta.get("file_path", meta.get("node_name", ""))
        fn   = meta.get("function_name", meta.get("section_title", ""))
        lang = meta.get("language", meta.get("config_type", ""))
        header_parts = [x for x in [fp, fn, lang] if x]
        header = " | ".join(header_parts) if header_parts else f"result {i}"
        # Trim document text
        snippet = doc.strip()[:max_chars_each]
        if len(doc.strip()) > max_chars_each:
            snippet += "\n... [truncated]"
        lines.append(f"\n[{i}] {header}\n```\n{snippet}\n```")
    return "\n".join(lines)


def _format_world_model_info(info: dict) -> str:
    lines = [f"\n### World Model: {info['name']}"]
    lines.append(f"  Path: {info['path']}")
    lines.append(f"  Type: {info.get('module_type','?')}  |  Language: {info.get('language','?')}  |  Stability: {info.get('stability','?')}  |  LOC: {info.get('lines_of_code','?')}")
    if info.get("known_hazards"):
        lines.append(f"  ⚠ Hazards: {info['known_hazards']}")
    if info.get("description"):
        lines.append(f"  Description: {info['description'][:200]}")
    deps = info.get("dependencies", [])
    if deps:
        dep_names = ", ".join(d["name"] for d in deps[:8])
        lines.append(f"  Depends on: {dep_names}")
    syms = info.get("symbols", [])
    public_syms = [s for s in syms if s.get("is_public")]
    if public_syms:
        sym_list = ", ".join(s["name"] for s in public_syms[:12])
        lines.append(f"  Public symbols ({len(public_syms)}): {sym_list}")
    return "\n".join(lines)


def _format_lessons(lessons: list[dict]) -> str:
    if not lessons:
        return ""
    lines = ["\n### Lessons Learned"]
    for i, lesson in enumerate(lessons, 1):
        lines.append(f"\n[{i}] {lesson.get('timestamp','')[:10]}")
        if lesson.get("outcome"):
            lines.append(f"  Outcome: {lesson['outcome'][:200]}")
        if lesson.get("root_cause"):
            lines.append(f"  Root cause: {lesson['root_cause'][:200]}")
        if lesson.get("resolution"):
            lines.append(f"  Resolution: {lesson['resolution'][:200]}")
    return "\n".join(lines)


def _format_lessons_enriched(lessons: list[dict]) -> str:
    """Format lessons in the PR-style format for Tier 1 working memory."""
    if not lessons:
        return ""
    lines = ["\n--- RELEVANT LESSONS ---"]
    for lesson in lessons:
        ts       = (lesson.get("timestamp") or "")[:10]
        iid      = lesson.get("intent_id", "?")
        outcome  = lesson.get("outcome", "?")
        cause    = (lesson.get("root_cause") or "")[:200]
        fix      = (lesson.get("resolution") or "")[:200]
        if outcome == "success":
            lines.append(f"\n[{ts}] Intent {iid} (success): {cause or 'Completed successfully.'}")
            if fix:
                lines.append(f"Key: {fix}")
        else:
            lines.append(f"\n[{ts}] Intent {iid} ({outcome}): {cause or 'Unknown failure.'}")
            if fix:
                lines.append(f"Fix: {fix}")
    return "\n".join(lines)


def build_context_packet(
    task_description: str,
    task_type: Optional[str] = None,
    affected_files: Optional[list[str]] = None,
) -> str:
    """
    Assemble a three-tier context packet for the given task.

    Args:
        task_description: Natural language description of the task.
        task_type:        One of RETRIEVAL_PROFILES keys. Auto-classified if None.
        affected_files:   Paths of files the task will touch (used for world model lookup).

    Returns:
        A formatted string ready for injection into an LLM system prompt.
        Always under MAX_CONTEXT_CHARS characters.
    """
    if task_type is None:
        task_type = classify_task(task_description)
    if task_type not in RETRIEVAL_PROFILES:
        log.warning("Unknown task_type %r, falling back to code_change", task_type)
        task_type = "code_change"

    profile = RETRIEVAL_PROFILES[task_type]

    sections: list[str] = []

    # ── Tier 0: Constitutional memory (always, never truncated) ──
    constitution = load_constitution()
    sections.append(constitution)
    sections.append(f"\n---\n\n# TASK CONTEXT\n**Task:** {task_description}\n**Type:** {task_type}")

    # ── Tier 1: Primary working memory ──
    sections.append("\n\n---\n\n# WORKING MEMORY (Tier 1 — primary retrieval)")
    found_primary = False
    for col_name in profile["primary"]:
        results = chroma_search(col_name, task_description, n=5)
        if results:
            label = f"From `{col_name}`"
            sections.append(_format_chroma_results(results, label, max_chars_each=600))
            found_primary = True
    if not found_primary:
        sections.append("\n[No primary results — collections may be empty]")

    # ── World model (Tier 1 extension) ──
    if profile["world_model"] and affected_files:
        sections.append("\n\n---\n\n# WORLD MODEL (affected files)")
        for fp in affected_files[:4]:   # cap at 4 files
            info = query_world_model(fp)
            if info:
                sections.append(_format_world_model_info(info))
            else:
                sections.append(f"\n[No world model entry for: {fp}]")

    # ── Tier 2: Background memory ──
    if profile["secondary"]:
        sections.append("\n\n---\n\n# BACKGROUND MEMORY (Tier 2 — secondary retrieval)")
        for col_name in profile["secondary"]:
            results = chroma_search(col_name, task_description, n=2)
            if results:
                label = f"From `{col_name}`"
                sections.append(_format_chroma_results(results, label, max_chars_each=400))

    # ── Recent failures (always checked for bug_fix / config_change) ──
    if task_type in ("bug_fix", "config_change"):
        failures = get_recent_failures(n=3)
        if failures:
            sections.append("\n\n---\n\n# RECENT FAILURES")
            sections.append(_format_chroma_results(failures, "nexus_failures", max_chars_each=400))

    # ── Lessons (Tier 1 extension) ──
    if profile["lessons"]:
        try:
            from feedback_loop import get_relevant_lessons as _get_relevant
            lessons = _get_relevant(task_description, n=3)
        except Exception:
            lessons = get_lessons(task_description, n=2)
        if lessons:
            sections.append("\n\n---\n")
            sections.append(_format_lessons_enriched(lessons))

    # ── Assemble and truncate ──
    # Constitutional memory is always the first section; preserve it intact.
    constitution_len = len(constitution)
    budget = MAX_CONTEXT_CHARS - constitution_len - CONSTITUTION_RESERVE

    # Build the non-constitution part
    rest_sections = sections[1:]      # everything after constitution
    rest_text     = "\n".join(rest_sections)

    if len(rest_text) > budget:
        rest_text = rest_text[:budget] + "\n\n... [context truncated to fit token limit]"

    full_packet = constitution + "\n" + rest_text
    return full_packet
