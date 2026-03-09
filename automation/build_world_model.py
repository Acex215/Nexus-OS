#!/usr/bin/env python3
"""
NEXUS CAF World Model Builder
Scans the codebase, extracts modules/symbols/dependencies via AST,
and writes everything into a SQLite world model at:
  /mnt/nexus-nas/knowledge/world_model.db

Usage:
    python3 build_world_model.py            # full build (updates changed files)
    python3 build_world_model.py --force    # drop and rebuild everything
    python3 build_world_model.py --verbose  # debug-level output
"""

import argparse
import ast
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH   = Path("/mnt/nexus-nas/knowledge/world_model.db")
LOG_FILE  = Path("/opt/nexus/automation/indexer.log")

WALK_ROOTS = [
    Path("/home/mhuraibi/nexus"),
    Path("/opt/nexus/agents"),
    Path("/opt/nexus/contracts"),
    Path("/opt/nexus/automation"),
]
SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", "build", ".pytest_cache"}

PROTECTED_NAMES = {
    "hierarchy_manager.py", "agent_registry.py", "agent_workflow.py",
    "blockchain_logger.py", "llm_client.py",
}
PROTECTED_EXTS  = {".sol"}
PROTECTED_GLOBS = {"genesis*.json"}   # checked by fnmatch below

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("world_model")


# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS modules (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,
    path              TEXT NOT NULL UNIQUE,
    module_type       TEXT,
    language          TEXT,
    description       TEXT,
    stability         TEXT DEFAULT 'stable',
    owner             TEXT DEFAULT 'md',
    last_modified     TEXT,
    lines_of_code     INTEGER,
    test_command      TEXT,
    build_command     TEXT,
    known_hazards     TEXT,
    dependencies_json TEXT
);

CREATE TABLE IF NOT EXISTS symbols (
    id          INTEGER PRIMARY KEY,
    module_id   INTEGER REFERENCES modules(id),
    name        TEXT NOT NULL,
    symbol_type TEXT,
    signature   TEXT,
    docstring   TEXT,
    line_number INTEGER,
    is_public   INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS dependencies (
    source_id       INTEGER REFERENCES modules(id),
    target_id       INTEGER REFERENCES modules(id),
    dependency_type TEXT,
    PRIMARY KEY (source_id, target_id, dependency_type)
);

CREATE TABLE IF NOT EXISTS service_health (
    id           INTEGER PRIMARY KEY,
    timestamp    TEXT,
    node_name    TEXT,
    service_name TEXT,
    status       TEXT,
    cpu_percent  REAL,
    memory_mb    REAL,
    extra_json   TEXT
);

CREATE TABLE IF NOT EXISTS indexed_files (
    file_path     TEXT PRIMARY KEY,
    file_hash     TEXT NOT NULL,
    collection    TEXT NOT NULL,
    chunks_created INTEGER,
    indexed_at    TEXT
);

CREATE TABLE IF NOT EXISTS lessons (
    id              INTEGER PRIMARY KEY,
    timestamp       TEXT,
    intent_id       TEXT,
    outcome         TEXT,
    root_cause      TEXT,
    useful_context  TEXT,
    missing_context TEXT,
    resolution      TEXT,
    tags_json       TEXT
);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_modules_path       ON modules(path);
CREATE INDEX IF NOT EXISTS idx_symbols_module_id  ON symbols(module_id);
CREATE INDEX IF NOT EXISTS idx_symbols_name       ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_deps_source        ON dependencies(source_id);
CREATE INDEX IF NOT EXISTS idx_deps_target        ON dependencies(target_id);
CREATE INDEX IF NOT EXISTS idx_sh_node_time       ON service_health(node_name, timestamp);
"""


def open_db(path: Path, force: bool = False) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    if force and path.exists():
        log.warning("--force: removing existing %s", path)
        path.unlink()
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    conn.executescript(INDEXES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.commit()
    return conn


# ── Helpers ───────────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def count_lines(path: Path) -> int:
    try:
        return sum(1 for _ in path.open("rb"))
    except OSError:
        return 0


def is_protected(path: Path) -> bool:
    import fnmatch
    name = path.name
    if name in PROTECTED_NAMES:
        return True
    if path.suffix in PROTECTED_EXTS:
        return True
    for pattern in PROTECTED_GLOBS:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def classify_module_type(path: Path) -> str:
    s = str(path)
    if "/agents/" in s:
        return "agent"
    if "/contracts/" in s:
        return "contract"
    if "/automation/" in s:
        return "script"
    if "libnexus" in s or "nexus_storage" in s:
        return "library"
    if "/tests/" in s or path.name.startswith("test_"):
        return "test"
    if "/scripts/" in s:
        return "script"
    if "/phase4/" in s:
        return "research"
    return "module"


def classify_language(path: Path) -> str:
    return {
        ".py":  "python",
        ".sol": "solidity",
        ".sh":  "bash",
        ".js":  "javascript",
        ".ts":  "typescript",
    }.get(path.suffix.lower(), "unknown")


def read_text(path: Path) -> Optional[str]:
    for enc in ("utf-8", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, PermissionError):
            continue
    return None


# ── Python AST extraction ─────────────────────────────────────────────────────

def _get_docstring(node: ast.AST) -> str:
    return (ast.get_docstring(node) or "").strip()[:1000]


def _build_signature(node) -> str:
    """Reconstruct a human-readable function signature."""
    try:
        args = node.args
        parts = []
        # positional-only args (Python 3.8+)
        for a in getattr(args, "posonlyargs", []):
            parts.append(a.arg)
        for a in args.args:
            parts.append(a.arg)
        if args.vararg:
            parts.append(f"*{args.vararg.arg}")
        for a in args.kwonlyargs:
            parts.append(a.arg)
        if args.kwarg:
            parts.append(f"**{args.kwarg.arg}")
        return f"{node.name}({', '.join(parts)})"
    except Exception:
        return node.name


def extract_python_symbols(path: Path, module_id: int) -> list[dict]:
    src = read_text(path)
    if src is None:
        return []
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as e:
        log.warning("AST parse error in %s: %s", path, e)
        return []

    symbols = []

    def visit(node, class_name: str = ""):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name    = node.name
            sig     = _build_signature(node)
            if class_name:
                sig = f"{class_name}.{sig}"
            doc     = _get_docstring(node)
            is_pub  = 0 if name.startswith("_") else 1
            symbols.append({
                "module_id":   module_id,
                "name":        name,
                "symbol_type": "method" if class_name else "function",
                "signature":   sig,
                "docstring":   doc,
                "line_number": node.lineno,
                "is_public":   is_pub,
            })
            # visit nested functions
            for child in ast.walk(node):
                if child is node:
                    continue
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    visit(child, class_name)

        elif isinstance(node, ast.ClassDef):
            cname  = node.name
            doc    = _get_docstring(node)
            is_pub = 0 if cname.startswith("_") else 1
            symbols.append({
                "module_id":   module_id,
                "name":        cname,
                "symbol_type": "class",
                "signature":   cname,
                "docstring":   doc,
                "line_number": node.lineno,
                "is_public":   is_pub,
            })
            for child in node.body:
                visit(child, class_name=cname)

    for node in ast.iter_child_nodes(tree):
        visit(node)

    return symbols


def extract_python_imports(path: Path) -> list[str]:
    """Return list of raw module names imported by this file."""
    src = read_text(path)
    if src is None:
        return []
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return []
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


# ── Solidity extraction ───────────────────────────────────────────────────────

def extract_solidity_symbols(path: Path, module_id: int) -> list[dict]:
    src = read_text(path)
    if src is None:
        return []
    symbols = []
    # contracts / interfaces / libraries
    for m in re.finditer(r'^(?:contract|interface|library)\s+(\w+)', src, re.MULTILINE):
        symbols.append({
            "module_id":   module_id,
            "name":        m.group(1),
            "symbol_type": "contract",
            "signature":   m.group(0).strip(),
            "docstring":   "",
            "line_number": src[:m.start()].count("\n") + 1,
            "is_public":   1,
        })
    # functions
    for m in re.finditer(
        r'^\s+function\s+(\w+)\s*\(([^)]*)\)\s*(public|private|internal|external|[^{]*)',
        src, re.MULTILINE
    ):
        fname = m.group(1)
        params = m.group(2).strip()
        vis    = m.group(3).strip().split()[0] if m.group(3).strip() else ""
        is_pub = 0 if vis in ("private", "internal") else 1
        symbols.append({
            "module_id":   module_id,
            "name":        fname,
            "symbol_type": "function",
            "signature":   f"{fname}({params})",
            "docstring":   "",
            "line_number": src[:m.start()].count("\n") + 1,
            "is_public":   is_pub,
        })
    return symbols


# ── Bash extraction ───────────────────────────────────────────────────────────

def extract_bash_symbols(path: Path, module_id: int) -> list[dict]:
    src = read_text(path)
    if src is None:
        return []
    symbols = []
    for m in re.finditer(r'^(\w[\w_-]*)\s*\(\s*\)\s*\{', src, re.MULTILINE):
        fname = m.group(1)
        symbols.append({
            "module_id":   module_id,
            "name":        fname,
            "symbol_type": "function",
            "signature":   f"{fname}()",
            "docstring":   "",
            "line_number": src[:m.start()].count("\n") + 1,
            "is_public":   1,
        })
    return symbols


# ── Module description heuristic ─────────────────────────────────────────────

def extract_module_description(path: Path, language: str) -> str:
    """Return module-level docstring or first comment block."""
    src = read_text(path)
    if not src:
        return ""
    if language == "python":
        try:
            tree = ast.parse(src)
            doc  = ast.get_docstring(tree)
            if doc:
                return doc.strip()[:300]
        except SyntaxError:
            pass
    # Fallback: first non-empty comment lines
    lines = src.splitlines()
    desc_lines = []
    for line in lines[:20]:
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("/*"):
            desc_lines.append(stripped.lstrip("#/ *").strip())
        elif desc_lines:
            break
    return " ".join(desc_lines)[:300]


# ── Codebase walk ─────────────────────────────────────────────────────────────

SCANNABLE_EXTS = {".py", ".sol", ".sh"}


def walk_scannable(roots: list[Path]):
    for root in roots:
        if not root.exists():
            log.warning("Root not found: %s", root)
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fname in filenames:
                path = Path(dirpath) / fname
                if path.suffix.lower() in SCANNABLE_EXTS:
                    yield path


# ── Dependency resolution ─────────────────────────────────────────────────────

def build_module_name_index(path_to_id: dict[str, int]) -> dict[str, int]:
    """
    Map Python module stem names → module_id for intra-codebase resolution.
    e.g. "blockchain_logger" → id of blockchain_logger.py
    """
    idx: dict[str, int] = {}
    for path_str, mid in path_to_id.items():
        p = Path(path_str)
        if p.suffix == ".py":
            idx[p.stem] = mid
            # also map dotted-package style by relative parts
            # e.g. agents.blockchain_logger → same id
    return idx


def resolve_import(import_name: str, name_idx: dict[str, int]) -> Optional[int]:
    """Try to resolve an import string to a module_id."""
    # Direct stem match: "blockchain_logger"
    if import_name in name_idx:
        return name_idx[import_name]
    # Last segment: "nexus_agents.blockchain_logger" → "blockchain_logger"
    last = import_name.rsplit(".", 1)[-1]
    if last in name_idx:
        return name_idx[last]
    # Any segment
    for part in import_name.split("."):
        if part in name_idx:
            return name_idx[part]
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="NEXUS World Model Builder")
    ap.add_argument("--force",   action="store_true", help="Rebuild from scratch")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.verbose:
        log.setLevel(logging.DEBUG)

    t0 = time.perf_counter()
    conn = open_db(DB_PATH, force=args.force)
    log.info("World model DB: %s", DB_PATH)

    # ── Collect existing paths so we only insert/update changed files ──
    existing = {
        row["path"]: row["id"]
        for row in conn.execute("SELECT id, path FROM modules")
    }

    # ── Phase 1: register modules and extract symbols ──
    path_to_id: dict[str, int] = {}   # path string → module id
    n_modules  = 0
    n_symbols  = 0
    n_new      = 0
    n_updated  = 0

    for path in walk_scannable(WALK_ROOTS):
        path_str  = str(path)
        language  = classify_language(path)
        mod_type  = classify_module_type(path)
        protected = is_protected(path)
        stability = "core" if protected else "stable"
        hazards   = "PROTECTED — do not auto-modify" if protected else None
        mtime     = mtime_iso(path)
        loc       = count_lines(path)
        desc      = extract_module_description(path, language)
        name      = path.stem

        if path_str in existing:
            # Update in place
            conn.execute("""
                UPDATE modules SET
                    last_modified=?, lines_of_code=?, description=?,
                    stability=?, known_hazards=?, module_type=?, language=?
                WHERE path=?
            """, (mtime, loc, desc, stability, hazards, mod_type, language, path_str))
            mid = existing[path_str]
            # Clear old symbols for this module
            conn.execute("DELETE FROM symbols WHERE module_id=?", (mid,))
            n_updated += 1
        else:
            cur = conn.execute("""
                INSERT INTO modules
                    (name, path, module_type, language, description,
                     stability, owner, last_modified, lines_of_code, known_hazards)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (name, path_str, mod_type, language, desc,
                  stability, "md", mtime, loc, hazards))
            mid = cur.lastrowid
            n_new += 1

        path_to_id[path_str] = mid
        n_modules += 1

        # Extract symbols
        if language == "python":
            syms = extract_python_symbols(path, mid)
        elif language == "solidity":
            syms = extract_solidity_symbols(path, mid)
        elif language == "bash":
            syms = extract_bash_symbols(path, mid)
        else:
            syms = []

        if syms:
            conn.executemany("""
                INSERT INTO symbols
                    (module_id, name, symbol_type, signature, docstring, line_number, is_public)
                VALUES (:module_id, :name, :symbol_type, :signature, :docstring, :line_number, :is_public)
            """, syms)
            n_symbols += syms.__len__()
            log.debug("  %s → %d symbols", path.name, len(syms))

    conn.commit()

    # ── Phase 2: build dependency edges ──
    name_idx = build_module_name_index(path_to_id)
    n_deps = 0

    # Clear existing dependency edges for files we just processed
    conn.execute("DELETE FROM dependencies WHERE source_id IN (%s)"
                 % ",".join(str(v) for v in path_to_id.values()))

    for path_str, source_id in path_to_id.items():
        path = Path(path_str)
        if path.suffix != ".py":
            continue
        imports = extract_python_imports(path)
        seen_targets: set[int] = set()
        for imp in imports:
            target_id = resolve_import(imp, name_idx)
            if target_id and target_id != source_id and target_id not in seen_targets:
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO dependencies
                            (source_id, target_id, dependency_type)
                        VALUES (?,?,'import')
                    """, (source_id, target_id))
                    seen_targets.add(target_id)
                    n_deps += 1
                except sqlite3.IntegrityError:
                    pass

    # ── Phase 3: write dependencies_json back into modules ──
    for path_str, mid in path_to_id.items():
        rows = conn.execute("""
            SELECT m.name, m.path
            FROM dependencies d JOIN modules m ON m.id = d.target_id
            WHERE d.source_id = ?
        """, (mid,)).fetchall()
        dep_list = [{"name": r["name"], "path": r["path"]} for r in rows]
        conn.execute("UPDATE modules SET dependencies_json=? WHERE id=?",
                     (json.dumps(dep_list) if dep_list else None, mid))

    conn.commit()

    # ── Summary ──
    elapsed = time.perf_counter() - t0
    db_size  = DB_PATH.stat().st_size // 1024

    print("\n" + "=" * 60)
    print("  NEXUS World Model Build Summary")
    print("=" * 60)
    print(f"  Modules registered  : {n_modules}  ({n_new} new, {n_updated} updated)")
    print(f"  Symbols extracted   : {n_symbols}")
    print(f"  Dependency edges    : {n_deps}")
    print(f"  DB size             : {db_size} KB")
    print(f"  Elapsed             : {elapsed:.1f}s")

    print("\n  Module types:")
    for row in conn.execute(
        "SELECT module_type, COUNT(*) as n FROM modules GROUP BY module_type ORDER BY n DESC"
    ):
        print(f"    {row['module_type']:<15} {row['n']:>4}")

    print("\n  Stability breakdown:")
    for row in conn.execute(
        "SELECT stability, COUNT(*) as n FROM modules GROUP BY stability ORDER BY n DESC"
    ):
        print(f"    {row['stability']:<10} {row['n']:>4}")

    print("\n  Top 10 most-depended-upon modules:")
    for row in conn.execute("""
        SELECT m.name, m.path, COUNT(*) as n
        FROM dependencies d JOIN modules m ON m.id = d.target_id
        GROUP BY d.target_id ORDER BY n DESC LIMIT 10
    """):
        print(f"    {row['name']:<30} ← {row['n']} imports")

    print("\n  Protected (core) files:")
    for row in conn.execute(
        "SELECT name, path FROM modules WHERE stability='core' ORDER BY name"
    ):
        print(f"    {row['name']:<30} {row['path']}")

    print("=" * 60)
    conn.close()


if __name__ == "__main__":
    main()
