#!/usr/bin/env python3
"""
NEXUS CAF Codebase Indexer
Walks source directories, chunks files by type, embeds with sentence-transformers,
and upserts into ChromaDB collections. Tracks indexed state in SQLite.

Usage:
    python3 indexer.py                   # full index run
    python3 indexer.py --dry-run         # show what would be indexed, no writes
    python3 indexer.py --force           # re-index everything regardless of hash
    python3 indexer.py --collection code_chunks   # only that collection
    python3 indexer.py --dir /opt/nexus/agents    # restrict walk to one directory
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

warnings.filterwarnings("ignore")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

# ── Constants ────────────────────────────────────────────────────────────────

CHROMA_HOST = "localhost"
CHROMA_PORT = 8000
EMBED_MODEL  = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_BATCH  = 32
LARGE_FILE_BYTES = 100_000
LARGE_CHUNK_CHARS = 4_000
LARGE_OVERLAP_CHARS = 200
FALLBACK_LINES = 50

DB_PATH = Path("/mnt/nexus-nas/knowledge/index_tracking.db")
REMOTE_CONFIG_DIR = Path("/mnt/nexus-nas/knowledge/collected_configs")
TRANSCRIPT_DIR = Path("/mnt/nexus-nas/knowledge/transcripts")

WALK_ROOTS = [
    Path("/home/mhuraibi/nexus"),
    Path("/opt/nexus/agents"),
    Path("/opt/nexus/contracts"),
    Path("/opt/nexus/automation"),
]
SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", "build", ".pytest_cache"}

REMOTE_NODES = {
    "nexus-master":  "10.0.20.3",
    "nexus-ai":      "10.0.20.4",
    "nexus-storage": "10.0.20.11",
    "nexus-ai2":     "10.0.20.6",
}
REMOTE_GLOBS = [
    "/etc/systemd/system/nexus-*.service",
    "/etc/systemd/system/geth.service",
    "/etc/systemd/system/nexus-geth.service",
    "/etc/systemd/system/ollama.service",
    "/etc/systemd/system/chromadb.service",
    "/etc/systemd/system/ipfs.service",
    "/etc/systemd/system/local-inference.service",
    "/etc/iptables/rules.v4",
]

# extension → (collection, language/type)
EXT_MAP = {
    ".py":      ("code_chunks",   "python"),
    ".sol":     ("code_chunks",   "solidity"),
    ".sh":      ("code_chunks",   "bash"),
    ".js":      ("code_chunks",   "javascript"),
    ".ts":      ("code_chunks",   "typescript"),
    ".yaml":    ("code_chunks",   "yaml"),
    ".yml":     ("code_chunks",   "yaml"),
    ".json":    ("code_chunks",   "json"),
    ".md":      ("docs_chunks",   "markdown"),
    ".service": ("infra_configs", "systemd"),
    ".conf":    ("infra_configs", "config"),
    ".rules":   ("infra_configs", "iptables"),
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("indexer")


# ── SQLite tracking ──────────────────────────────────────────────────────────

def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS indexed_files (
            file_path       TEXT PRIMARY KEY,
            file_hash       TEXT NOT NULL,
            collection      TEXT NOT NULL,
            chunks_created  INTEGER NOT NULL,
            indexed_at      TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def get_tracked(conn: sqlite3.Connection, file_path: str):
    row = conn.execute(
        "SELECT file_hash, chunks_created FROM indexed_files WHERE file_path=?",
        (file_path,)
    ).fetchone()
    return row  # (hash, chunks) or None


def update_tracked(conn: sqlite3.Connection, file_path: str, file_hash: str,
                   collection: str, chunks: int):
    conn.execute("""
        INSERT INTO indexed_files (file_path, file_hash, collection, chunks_created, indexed_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(file_path) DO UPDATE SET
            file_hash=excluded.file_hash,
            collection=excluded.collection,
            chunks_created=excluded.chunks_created,
            indexed_at=excluded.indexed_at
    """, (file_path, file_hash, collection, chunks, datetime.now(timezone.utc).isoformat()))
    conn.commit()


# ── Utilities ────────────────────────────────────────────────────────────────

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chunk_id(file_path: str, chunk_identifier: str) -> str:
    raw = f"{file_path}:{chunk_identifier}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def read_file(path: Path) -> str | None:
    """Read text file, trying utf-8 then latin-1. Returns None on failure."""
    for enc in ("utf-8", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, PermissionError):
            continue
    return None


def is_binary(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:8192]
        return b"\x00" in chunk
    except (PermissionError, OSError):
        return True


def large_file_chunks(text: str) -> list[str]:
    """Split text at character boundaries with overlap for large files."""
    chunks, start = [], 0
    while start < len(text):
        end = start + LARGE_CHUNK_CHARS
        chunks.append(text[start:end])
        start = end - LARGE_OVERLAP_CHARS
        if start >= len(text):
            break
    return chunks


# ── Tree-sitter Python chunker ───────────────────────────────────────────────

def _load_ts_python():
    try:
        import tree_sitter_python as tsp
        from tree_sitter import Language, Parser
        lang = Language(tsp.language())
        parser = Parser(lang)
        return parser
    except Exception:
        return None


_TS_PARSER = None
_TS_TRIED  = False


def ts_parser():
    global _TS_PARSER, _TS_TRIED
    if not _TS_TRIED:
        _TS_PARSER = _load_ts_python()
        _TS_TRIED = True
    return _TS_PARSER


def _node_text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _node_name(node, source: bytes) -> str:
    for child in node.children:
        if child.type == "identifier":
            return _node_text(child, source)
    return ""


def _node_docstring(node, source: bytes) -> str:
    """Extract the first string literal from the function/class body."""
    body = next((c for c in node.children if c.type == "block"), None)
    if not body:
        return ""
    for stmt in body.children:
        if stmt.type == "expression_statement":
            for s in stmt.children:
                if s.type == "string":
                    return _node_text(s, source)
    return ""


def _extract_ts_chunks(source_bytes: bytes, file_path: str, mtime: str) -> list[dict]:
    """Use tree-sitter to extract function/class chunks from Python source."""
    parser = ts_parser()
    if parser is None:
        return []

    try:
        tree = parser.parse(source_bytes)
    except Exception:
        return []

    module = Path(file_path).stem
    chunks = []

    def process_node(node, class_name: str = ""):
        if node.type == "function_definition":
            fname = _node_name(node, source_bytes)
            doc   = _node_docstring(node, source_bytes)
            body  = _node_text(node, source_bytes)
            cid   = chunk_id(file_path, f"{''.join([class_name,'.',fname] if class_name else [fname])}")
            meta  = {
                "file_path":    file_path,
                "language":     "python",
                "function_name": fname,
                "module_name":  module,
                "last_modified": mtime,
            }
            if class_name:
                meta["class_name"] = class_name
            chunks.append({"id": cid, "text": body, "meta": meta})

        elif node.type == "class_definition":
            cname = _node_name(node, source_bytes)
            doc   = _node_docstring(node, source_bytes)
            # Emit the class signature + docstring as its own chunk
            # Collect header lines up to the first method
            class_body = next((c for c in node.children if c.type == "block"), None)
            header_end = node.start_byte
            if class_body:
                header_end = class_body.start_byte
            class_header = source_bytes[node.start_byte:header_end].decode("utf-8", errors="replace")
            if doc:
                class_header += f"\n    {doc}"
            cid = chunk_id(file_path, f"class.{cname}")
            chunks.append({
                "id": cid,
                "text": class_header,
                "meta": {
                    "file_path":    file_path,
                    "language":     "python",
                    "class_name":   cname,
                    "function_name": "",
                    "module_name":  module,
                    "last_modified": mtime,
                }
            })
            # Recurse into class body for methods
            if class_body:
                for child in class_body.children:
                    process_node(child, class_name=cname)

    for node in tree.root_node.children:
        process_node(node)

    return chunks


# ── Language-specific chunkers ───────────────────────────────────────────────

def chunk_python(text: str, file_path: str, mtime: str) -> list[dict]:
    source = text.encode("utf-8", errors="replace")
    chunks = _extract_ts_chunks(source, file_path, mtime)
    if chunks:
        return chunks
    # Fallback: line-based
    lines = text.splitlines()
    module = Path(file_path).stem
    result = []
    for i in range(0, len(lines), FALLBACK_LINES):
        block = "\n".join(lines[i:i + FALLBACK_LINES])
        cid = chunk_id(file_path, f"lines.{i}")
        result.append({
            "id": cid,
            "text": block,
            "meta": {"file_path": file_path, "language": "python",
                     "module_name": module, "last_modified": mtime},
        })
    return result


def chunk_solidity(text: str, file_path: str, mtime: str) -> list[dict]:
    """Split on contract and function boundaries."""
    fname = Path(file_path).stem
    mtime_val = mtime

    # Try splitting on top-level constructs
    pattern = re.compile(
        r'^(?:contract|library|interface|function)\s+(\w+)',
        re.MULTILINE
    )
    matches = list(pattern.finditer(text))

    if not matches:
        # Whole file as one chunk
        cid = chunk_id(file_path, "whole")
        return [{"id": cid, "text": text,
                 "meta": {"file_path": file_path, "language": "solidity",
                          "contract_name": fname, "function_name": "",
                          "last_modified": mtime_val}}]

    chunks = []
    current_contract = fname
    for idx, m in enumerate(matches):
        start = m.start()
        end   = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        kind  = m.group(0).split()[0]
        name  = m.group(1)
        if kind in ("contract", "library", "interface"):
            current_contract = name
        cid = chunk_id(file_path, f"{kind}.{name}")
        chunks.append({
            "id": cid,
            "text": block,
            "meta": {
                "file_path":     file_path,
                "language":      "solidity",
                "contract_name": current_contract,
                "function_name": name if kind == "function" else "",
                "last_modified": mtime_val,
            }
        })
    return chunks


def chunk_bash(text: str, file_path: str, mtime: str) -> list[dict]:
    """Split on function boundaries."""
    script = Path(file_path).stem
    func_re = re.compile(r'^(\w[\w_-]*)\s*\(\s*\)\s*\{', re.MULTILINE)
    matches = list(func_re.finditer(text))

    if not matches:
        cid = chunk_id(file_path, "whole")
        return [{"id": cid, "text": text,
                 "meta": {"file_path": file_path, "language": "bash",
                          "script_name": script, "last_modified": mtime}}]

    chunks = []
    for idx, m in enumerate(matches):
        start = m.start()
        end   = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        name  = m.group(1)
        cid   = chunk_id(file_path, f"func.{name}")
        chunks.append({
            "id": cid,
            "text": block,
            "meta": {"file_path": file_path, "language": "bash",
                     "script_name": script, "function_name": name,
                     "last_modified": mtime},
        })
    return chunks


def chunk_markdown(text: str, file_path: str, mtime: str) -> list[dict]:
    """Split on markdown headers."""
    doc = Path(file_path).stem
    header_re = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
    matches = list(header_re.finditer(text))

    if not matches:
        cid = chunk_id(file_path, "whole")
        return [{"id": cid, "text": text,
                 "meta": {"file_path": file_path, "section_title": doc,
                          "document_name": doc, "last_modified": mtime}}]

    # Preamble before first header
    chunks = []
    if matches[0].start() > 0:
        preamble = text[:matches[0].start()].strip()
        if preamble:
            cid = chunk_id(file_path, "preamble")
            chunks.append({"id": cid, "text": preamble,
                           "meta": {"file_path": file_path, "section_title": "preamble",
                                    "document_name": doc, "last_modified": mtime}})

    for idx, m in enumerate(matches):
        start = m.start()
        end   = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        title = m.group(2).strip()
        cid   = chunk_id(file_path, f"section.{title[:60]}")
        chunks.append({
            "id": cid,
            "text": block,
            "meta": {"file_path": file_path, "section_title": title,
                     "document_name": doc, "last_modified": mtime},
        })
    return chunks


def chunk_whole(text: str, file_path: str, mtime: str, lang: str) -> list[dict]:
    """Single-chunk for YAML, JSON, config files."""
    name = Path(file_path).name
    stem = Path(file_path).stem
    meta = {"file_path": file_path, "config_type": lang,
            "service_name": stem, "last_modified": mtime}
    if lang in ("systemd", "config", "iptables"):
        meta["node_name"] = "nexus-admin"
    cid = chunk_id(file_path, "whole")
    return [{"id": cid, "text": text, "meta": meta}]


# ── Transcript chunkers ──────────────────────────────────────────────────────

def chunk_by_turns(filepath: str, content: str, session_date: str) -> list[dict]:
    """Chunk transcripts that use **User:** / **Assistant:** turn markers."""
    filename = os.path.basename(filepath)
    chunks = []
    seen_hashes: set[str] = set()

    turn_re = re.compile(r'\*\*(?:User|Assistant):\*\*|\n(?:User|Assistant):\s')
    parts   = turn_re.split(content)
    markers = turn_re.findall(content)

    for i, part in enumerate(parts):
        part = part.strip()
        if not part or len(part) < 50:
            continue

        content_key  = re.sub(r'\s+', ' ', part[:200]).lower()
        content_hash = hashlib.md5(content_key.encode()).hexdigest()
        if content_hash in seen_hashes:
            continue
        seen_hashes.add(content_hash)

        role = "assistant"
        if i > 0 and i - 1 < len(markers) and "User" in markers[i - 1]:
            role = "user"

        if len(part) > 1500:
            part = part[:1500] + "..."

        cid = f"transcript-{hashlib.sha256(part[:300].encode()).hexdigest()[:16]}"
        chunks.append({
            "id": cid,
            "text": part,
            "meta": {
                "session_date": session_date,
                "topic": part[:80].strip(),
                "participants": "md, claude",
                "source_file": filename,
                "chunk_index": i,
                "role": role,
            },
        })

    return chunks


def chunk_by_sections(filepath: str, content: str, session_date: str) -> list[dict]:
    """Chunk section-based transcript summaries (actual file format)."""
    filename = os.path.basename(filepath)
    chunks: list[dict] = []
    seen_hashes: set[str] = set()

    # Split on explicit section markers that appear at the start of a line:
    #   [Phase Name: ...]  [Section: ...]  or a repeated [YYYY-MM-DD_...] filename
    sections = re.split(
        r'\n(?=\[(?:Phase Name|Section):|'
        r'\[20\d{2}-\d{2}-\d{2})',
        content,
    )

    # Fallback: double blank lines
    if len(sections) <= 1:
        sections = [s.strip() for s in re.split(r'\n{2,}', content) if s.strip()]

    for i, section in enumerate(sections):
        section = section.strip()
        if not section or len(section) < 50:
            continue

        # Deduplicate by hashing the first 200 normalised chars
        content_key  = re.sub(r'\s+', ' ', section[:200]).lower()
        content_hash = hashlib.md5(content_key.encode()).hexdigest()
        if content_hash in seen_hashes:
            continue
        seen_hashes.add(content_hash)

        # Extract a human-readable topic
        topic_match = re.match(r'\[(?:Phase Name:\s*)?(.+?)\]', section)
        if topic_match:
            topic = topic_match.group(1).strip()
        else:
            topic = section.split('\n')[0][:80].strip()

        if len(section) > 1500:
            section = section[:1500] + "..."

        # Content-hash based ID — deduplicates across files automatically
        cid = f"transcript-{hashlib.sha256(section[:300].encode()).hexdigest()[:16]}"

        chunks.append({
            "id": cid,
            "text": section,
            "meta": {
                "session_date": session_date,
                "topic": topic,
                "participants": "md, claude",
                "source_file": filename,
                "chunk_index": i,
            },
        })

    return chunks


def chunk_transcript(filepath: str, content: str) -> list[dict]:
    """Chunk a transcript file. Auto-detects format."""
    filename = os.path.basename(filepath)

    # Date from filename prefix (strip leading '[' if present)
    date_match = re.match(r'(\d{4}-\d{2}-\d{2})', filename.lstrip('['))
    session_date = date_match.group(1) if date_match else "unknown"

    # Format 1: User/Assistant turn markers
    if re.search(r'\*\*(?:User|Assistant):\*\*|\nUser:\s|\nAssistant:\s', content):
        return chunk_by_turns(filepath, content, session_date)

    # Format 2: Section-based summaries
    return chunk_by_sections(filepath, content, session_date)


# ── File dispatcher ──────────────────────────────────────────────────────────

def chunks_for_file(path: Path, collection: str, lang: str) -> list[dict]:
    """Read a local file and produce its chunks."""
    if is_binary(path):
        return []

    size = path.stat().st_size
    if size == 0:
        return []

    text = read_file(path)
    if text is None:
        log.warning("Encoding error, skipping: %s", path)
        return []

    mtime = mtime_iso(path)
    fp    = str(path)

    # Large-file override
    if size > LARGE_FILE_BYTES:
        log.debug("Large file (%d bytes), character-chunking: %s", size, path)
        result = []
        for i, block in enumerate(large_file_chunks(text)):
            cid = chunk_id(fp, f"large.{i}")
            result.append({"id": cid, "text": block,
                           "meta": {"file_path": fp, "language": lang,
                                    "last_modified": mtime, "chunk_index": str(i)}})
        return result

    if lang == "python":
        return chunk_python(text, fp, mtime)
    elif lang == "solidity":
        return chunk_solidity(text, fp, mtime)
    elif lang == "bash":
        return chunk_bash(text, fp, mtime)
    elif lang == "markdown":
        return chunk_markdown(text, fp, mtime)
    else:
        return chunk_whole(text, fp, mtime, lang)


# ── Directory walker ─────────────────────────────────────────────────────────

def walk_files(roots: list[Path], only_collection: str | None = None,
               only_dir: Path | None = None) -> Generator[tuple[Path, str, str], None, None]:
    """Yield (path, collection, language) for each indexable file."""
    effective_roots = [only_dir] if only_dir else roots
    for root in effective_roots:
        if not root.exists():
            log.warning("Walk root does not exist: %s", root)
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune skip dirs in place
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fname in filenames:
                path = Path(dirpath) / fname
                ext  = path.suffix.lower()
                if ext not in EXT_MAP:
                    continue
                collection, lang = EXT_MAP[ext]
                if only_collection and collection != only_collection:
                    continue
                yield path, collection, lang


# ── SSH remote config collection ─────────────────────────────────────────────

def collect_remote_configs(dry_run: bool, only_collection: str | None) -> list[dict]:
    """SSH to each cluster node, fetch config files, return chunks for infra_configs."""
    if only_collection and only_collection != "infra_configs":
        return []

    all_chunks = []
    REMOTE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    for node_name, ip in REMOTE_NODES.items():
        node_dir = REMOTE_CONFIG_DIR / node_name
        node_dir.mkdir(parents=True, exist_ok=True)

        # Build a single SSH command that lists and cats files.
        # Use || true so permission errors on individual files don't fail the whole command.
        # Try sudo cat for iptables; fall back silently.
        glob_list = " ".join(REMOTE_GLOBS)
        ssh_cmd = (
            f"for f in {glob_list}; do "
            f"  [ -f \"$f\" ] || continue; "
            f"  echo \"===FILE:$f===\"; "
            f"  sudo cat \"$f\" 2>/dev/null || cat \"$f\" 2>/dev/null || echo '[PERMISSION DENIED]'; "
            f"done; true"
        )
        try:
            result = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                 f"mhuraibi@{ip}", ssh_cmd],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                log.warning("SSH to %s (%s) failed: %s", node_name, ip,
                            result.stderr.strip()[:120])
                continue
        except subprocess.TimeoutExpired:
            log.warning("SSH timeout for %s (%s)", node_name, ip)
            continue
        except Exception as e:
            log.warning("SSH error for %s (%s): %s", node_name, ip, e)
            continue

        # Parse the cat output into per-file blocks
        output = result.stdout
        file_blocks = re.split(r'===FILE:(/[^\n]+)===\n?', output)
        # file_blocks: [pre, path1, content1, path2, content2, ...]
        # Deduplicate: nexus-*.service glob can overlap explicit entries
        seen_paths: set[str] = set()
        i = 1
        while i + 1 < len(file_blocks):
            remote_path = file_blocks[i].strip()
            content     = file_blocks[i + 1]
            i += 2
            if remote_path in seen_paths:
                continue
            seen_paths.add(remote_path)

            if not content.strip() or content.strip() == "[PERMISSION DENIED]":
                continue

            local_name = Path(remote_path).name
            local_path = node_dir / local_name

            if not dry_run:
                local_path.write_text(content, encoding="utf-8")
                log.debug("Saved %s → %s", remote_path, local_path)

            # Build chunk
            mtime_str = datetime.now(timezone.utc).isoformat()
            ext = Path(remote_path).suffix.lower()
            lang = {".service": "systemd", ".conf": "config",
                    ".v4": "iptables", ".rules": "iptables"}.get(ext, "config")
            stem = Path(remote_path).stem
            cid  = chunk_id(f"{node_name}:{remote_path}", "whole")
            all_chunks.append({
                "id": cid,
                "text": content,
                "collection": "infra_configs",
                "meta": {
                    "file_path":    remote_path,
                    "node_name":    node_name,
                    "node_ip":      ip,
                    "service_name": stem,
                    "config_type":  lang,
                    "last_modified": mtime_str,
                    "source":       "ssh_collected",
                },
                "tracking_key": f"ssh:{node_name}:{remote_path}",
            })

        log.info("SSH %s (%s): collected %d config chunks",
                 node_name, ip, sum(1 for c in all_chunks if c["meta"].get("node_name") == node_name))

    return all_chunks


# ── Transcript collection ─────────────────────────────────────────────────────

def collect_transcripts(only_collection: str | None, force: bool,
                        conn: sqlite3.Connection | None) -> list[dict]:
    """Walk TRANSCRIPT_DIR and return chunks for the session_transcripts collection.

    Handles skip-if-unchanged via the tracking DB (pass conn=None for dry-run).
    """
    if only_collection and only_collection != "session_transcripts":
        return []

    if not TRANSCRIPT_DIR.exists():
        log.warning("Transcript dir not found: %s", TRANSCRIPT_DIR)
        return []

    result: list[dict] = []
    skipped = 0

    for fpath in sorted(TRANSCRIPT_DIR.iterdir()):
        if fpath.suffix.lower() != ".md":
            continue

        try:
            file_hash = sha256_file(fpath)
        except OSError as e:
            log.warning("Cannot hash transcript %s: %s", fpath.name, e)
            continue

        tracking_key = str(fpath)

        if not force and conn is not None:
            row = get_tracked(conn, tracking_key)
            if row and row[0] == file_hash:
                log.debug("Transcript unchanged, skip: %s", fpath.name)
                skipped += 1
                continue

        content = read_file(fpath)
        if not content:
            continue

        chunks = chunk_transcript(str(fpath), content)
        if not chunks:
            log.debug("Transcript produced 0 chunks: %s", fpath.name)
            continue

        for c in chunks:
            c["_tracking_key"] = tracking_key
            c["_file_hash"]    = file_hash

        result.extend(chunks)
        log.debug("Transcript %s → %d chunks", fpath.name, len(chunks))

    if skipped:
        log.info("Transcripts: %d file(s) unchanged, skipped", skipped)

    return result


# ── Embedding + ChromaDB upsert ───────────────────────────────────────────────

def load_embedder():
    from sentence_transformers import SentenceTransformer
    log.info("Loading embedding model %s ...", EMBED_MODEL)
    return SentenceTransformer(EMBED_MODEL)


def load_chroma():
    import chromadb
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    client.heartbeat()
    return client


def upsert_chunks(chroma_client, embedder, collection_name: str,
                  chunks: list[dict], dry_run: bool) -> int:
    if not chunks:
        return 0
    if dry_run:
        return len(chunks)

    col = chroma_client.get_or_create_collection(collection_name)
    total = 0

    for batch_start in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[batch_start:batch_start + EMBED_BATCH]
        texts = [c["text"] for c in batch]
        ids   = [c["id"]   for c in batch]
        metas = [c["meta"] for c in batch]

        # Sanitize metadata: ChromaDB requires str/int/float/bool values
        clean_metas = []
        for m in metas:
            clean_metas.append({k: (str(v) if not isinstance(v, (str, int, float, bool)) else v)
                                 for k, v in m.items()})

        try:
            vecs = embedder.encode(texts, batch_size=EMBED_BATCH,
                                   show_progress_bar=False).tolist()
            col.upsert(ids=ids, embeddings=vecs, documents=texts, metadatas=clean_metas)
            total += len(batch)
        except Exception as e:
            log.error("Upsert failed for batch starting %d in %s: %s",
                      batch_start, collection_name, e)

    return total


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="NEXUS CAF Codebase Indexer")
    ap.add_argument("--dry-run",    action="store_true",
                    help="Show what would be indexed without writing anything")
    ap.add_argument("--force",      action="store_true",
                    help="Re-index all files regardless of hash")
    ap.add_argument("--collection", metavar="NAME",
                    help="Only index into this ChromaDB collection")
    ap.add_argument("--dir",        metavar="PATH",
                    help="Only walk this directory (overrides default roots)")
    ap.add_argument("--no-remote",  action="store_true",
                    help="Skip SSH collection of remote node configs")
    ap.add_argument("--verbose",    action="store_true")
    args = ap.parse_args()

    if args.verbose:
        log.setLevel(logging.DEBUG)

    only_dir = Path(args.dir).resolve() if args.dir else None

    t_start = time.perf_counter()

    if args.dry_run:
        log.info("=== DRY RUN — no writes will occur ===")

    # ── Open DB and ChromaDB ──
    if not args.dry_run:
        conn = open_db(DB_PATH)
        log.info("Tracking DB: %s", DB_PATH)
    else:
        conn = None

    if not args.dry_run:
        try:
            chroma = load_chroma()
            log.info("ChromaDB connected at %s:%s", CHROMA_HOST, CHROMA_PORT)
        except Exception as e:
            log.error("Cannot connect to ChromaDB: %s", e)
            sys.exit(1)
        embedder = load_embedder()
    else:
        chroma = embedder = None

    # ── Statistics ──
    stats = {
        "files_scanned":  0,
        "files_indexed":  0,
        "files_skipped":  0,
        "files_error":    0,
        "chunks_total":   0,
        "by_collection":  {},
        "errors":         [],
    }

    # ── Walk local files ──
    pending: dict[str, list[dict]] = {}  # collection → [chunk, ...]

    for path, collection, lang in walk_files(WALK_ROOTS, args.collection, only_dir):
        stats["files_scanned"] += 1

        try:
            file_hash = sha256_file(path)
        except (PermissionError, OSError) as e:
            log.warning("Cannot hash %s: %s", path, e)
            stats["files_error"] += 1
            continue

        tracking_key = str(path)

        # Check tracking DB
        if not args.dry_run and not args.force:
            row = get_tracked(conn, tracking_key)
            if row and row[0] == file_hash:
                stats["files_skipped"] += 1
                log.debug("Unchanged, skip: %s", path)
                continue

        # Produce chunks
        try:
            file_chunks = chunks_for_file(path, collection, lang)
        except Exception as e:
            log.warning("Chunking failed for %s: %s", path, e)
            stats["files_error"] += 1
            stats["errors"].append(f"{path}: {e}")
            continue

        if not file_chunks:
            stats["files_skipped"] += 1
            continue

        if args.dry_run:
            print(f"  [DRY] {collection:<22} {lang:<12} {len(file_chunks):>3} chunks  {path}")
            stats["files_indexed"] += 1
            stats["chunks_total"]  += len(file_chunks)
            stats["by_collection"].setdefault(collection, 0)
            stats["by_collection"][collection] += len(file_chunks)
            continue

        # Accumulate for batched upsert
        pending.setdefault(collection, []).extend(
            [{**c, "_tracking_key": tracking_key,
              "_file_hash": file_hash} for c in file_chunks]
        )
        # Flush when batch is large enough
        if sum(len(v) for v in pending.values()) >= EMBED_BATCH * 4:
            _flush_pending(pending, chroma, embedder, conn, stats)

    # Flush remaining local file chunks
    if not args.dry_run and pending:
        _flush_pending(pending, chroma, embedder, conn, stats)

    # ── SSH remote configs ──
    if not args.no_remote:
        remote_chunks = collect_remote_configs(args.dry_run, args.collection)
        if remote_chunks:
            if args.dry_run:
                for c in remote_chunks:
                    node = c["meta"].get("node_name", "?")
                    fp   = c["meta"].get("file_path", "?")
                    print(f"  [DRY] infra_configs          ssh        "
                          f"  1 chunks  ssh:{node}:{fp}")
                stats["files_indexed"]  += len(remote_chunks)
                stats["chunks_total"]   += len(remote_chunks)
                stats["by_collection"].setdefault("infra_configs", 0)
                stats["by_collection"]["infra_configs"] += len(remote_chunks)
            else:
                remote_by_col: dict[str, list[dict]] = {}
                for c in remote_chunks:
                    col = c.pop("collection", "infra_configs")
                    tkey = c.pop("tracking_key", c["id"])
                    c["_tracking_key"] = tkey
                    c["_file_hash"]    = sha256_bytes(c["text"].encode())
                    remote_by_col.setdefault(col, []).append(c)
                _flush_pending(remote_by_col, chroma, embedder, conn, stats)

    # ── Transcript collection ──
    t_chunks = collect_transcripts(
        args.collection,
        args.force,
        conn if not args.dry_run else None,
    )
    if t_chunks:
        if args.dry_run:
            by_file: dict[str, int] = {}
            for c in t_chunks:
                src = c["meta"]["source_file"]
                by_file[src] = by_file.get(src, 0) + 1
            for src_file, n in sorted(by_file.items()):
                print(f"  [DRY] session_transcripts    transcript  {n:>3} chunks  {src_file}")
            stats["chunks_total"] += len(t_chunks)
            stats["by_collection"].setdefault("session_transcripts", 0)
            stats["by_collection"]["session_transcripts"] += len(t_chunks)
        else:
            _flush_pending(
                {"session_transcripts": t_chunks},
                chroma, embedder, conn, stats,
            )

    # ── Print summary ──
    elapsed = time.perf_counter() - t_start
    print("\n" + "=" * 60)
    print(f"  NEXUS Indexer {'(DRY RUN) ' if args.dry_run else ''}Summary")
    print("=" * 60)
    print(f"  Files scanned  : {stats['files_scanned']}")
    print(f"  Files indexed  : {stats['files_indexed']}")
    print(f"  Files skipped  : {stats['files_skipped']}  (unchanged)")
    print(f"  Files errored  : {stats['files_error']}")
    print(f"  Chunks created : {stats['chunks_total']}")
    print(f"  Time elapsed   : {elapsed:.1f}s")
    print()
    print("  By collection:")
    for col, cnt in sorted(stats["by_collection"].items()):
        print(f"    {col:<25} {cnt:>5} chunks")
    if stats["errors"]:
        print(f"\n  Errors ({len(stats['errors'])}):")
        for e in stats["errors"][:10]:
            print(f"    {e}")
    print("=" * 60)

    if not args.dry_run and conn:
        conn.close()


def _flush_pending(pending: dict[str, list[dict]], chroma, embedder, conn, stats):
    """Upsert all pending chunks and update tracking DB."""
    for collection, chunks in list(pending.items()):
        # Group by file for tracking
        by_file: dict[str, list[dict]] = {}
        for c in chunks:
            tkey = c.pop("_tracking_key", c["id"])
            fhash = c.pop("_file_hash", "")
            by_file.setdefault(tkey, {"hash": fhash, "col": collection, "chunks": []})
            by_file[tkey]["chunks"].append(c)

        all_file_chunks = [c for info in by_file.values() for c in info["chunks"]]
        upserted = upsert_chunks(chroma, embedder, collection, all_file_chunks, dry_run=False)

        stats["files_indexed"] += len(by_file)
        stats["chunks_total"]  += upserted
        stats["by_collection"].setdefault(collection, 0)
        stats["by_collection"][collection] += upserted

        for tkey, info in by_file.items():
            update_tracked(conn, tkey, info["hash"], collection, len(info["chunks"]))
            log.debug("Indexed %d chunks → %s  [%s]", len(info["chunks"]), collection, tkey)

    pending.clear()


if __name__ == "__main__":
    main()
