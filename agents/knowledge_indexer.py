"""knowledge_indexer.py — Indexes completed task logs into ChromaDB.

Provides semantic retrieval of past tasks during planning (Phase 4).
"""

import json
import logging
from pathlib import Path

import chromadb

log = logging.getLogger("knowledge_indexer")

CHROMA_HOST = "localhost"
CHROMA_PORT = 8000
COLLECTION_NAME = "dev_assistant_tasks"

# ── Client / collection helpers ───────────────────────────────────────────────

def _get_client() -> chromadb.HttpClient:
    return chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)


def _get_collection(client: chromadb.HttpClient, name: str = COLLECTION_NAME):
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


def _build_document(entry: dict) -> str:
    files = ", ".join(entry.get("affected_files") or []) or "none"
    error = entry.get("error") or "none"
    return (
        f"{entry.get('description', '')}\n"
        f"Outcome: {entry.get('status', 'unknown')}\n"
        f"Error: {error}\n"
        f"Files: {files}\n"
        f"Duration: {entry.get('duration_seconds', 0)}s"
    )


def _build_metadata(entry: dict) -> dict:
    error_raw = entry.get("error") or "none"
    return {
        "task_id":   str(entry.get("task_id") or ""),
        "status":    str(entry.get("status") or ""),
        "success":   "true" if entry.get("success") else "false",
        "priority":  str(entry.get("priority") or ""),
        "risk":      str(entry.get("risk") or ""),
        "timestamp": str(entry.get("timestamp") or ""),
        "error":     error_raw[:200],
    }


# ── Public API ────────────────────────────────────────────────────────────────

async def index_task(
    log_entry: dict,
    *,
    _collection_name: str = COLLECTION_NAME,
) -> bool:
    """Upsert a single task log entry into ChromaDB. Returns True on success."""
    try:
        client = _get_client()
        collection = _get_collection(client, _collection_name)
        doc_id = log_entry["id"]
        document = _build_document(log_entry)
        metadata = _build_metadata(log_entry)
        collection.upsert(
            ids=[doc_id],
            documents=[document],
            metadatas=[metadata],
        )
        log.debug("Indexed task log entry %s into ChromaDB", doc_id)
        return True
    except Exception as exc:
        log.warning("knowledge_indexer: failed to index entry %s: %s",
                    log_entry.get("id", "?"), exc)
        return False


def query_similar_tasks(
    description: str,
    n: int = 5,
    include_failures: bool = True,
    *,
    _collection_name: str = COLLECTION_NAME,
) -> list[dict]:
    """Query ChromaDB for the N most similar past tasks by description.

    Returns a list of dicts with keys:
        task_id, description, status, error, success, timestamp, distance
    """
    try:
        client = _get_client()
        collection = _get_collection(client, _collection_name)

        count = collection.count()
        if count == 0:
            return []

        query_kwargs: dict = {
            "query_texts": [description],
            "n_results": min(n, count),
            "include": ["documents", "metadatas", "distances"],
        }
        if not include_failures:
            query_kwargs["where"] = {"success": {"$eq": "true"}}

        results = collection.query(**query_kwargs)

        entries = []
        ids       = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for doc_id, doc, meta, dist in zip(ids, documents, metadatas, distances):
            entries.append({
                "task_id":     meta.get("task_id", ""),
                "description": doc,
                "status":      meta.get("status", ""),
                "error":       meta.get("error", "none"),
                "success":     meta.get("success") == "true",
                "timestamp":   meta.get("timestamp", ""),
                "distance":    dist,
            })
        return entries

    except Exception as exc:
        log.warning("knowledge_indexer: query failed: %s", exc)
        return []


def _index_entry_sync(entry: dict, collection_name: str = COLLECTION_NAME) -> bool:
    """Synchronous upsert used by backfill."""
    try:
        client = _get_client()
        collection = _get_collection(client, collection_name)
        doc_id   = entry["id"]
        document = _build_document(entry)
        metadata = _build_metadata(entry)
        collection.upsert(
            ids=[doc_id],
            documents=[document],
            metadatas=[metadata],
        )
        return True
    except Exception as exc:
        log.warning("knowledge_indexer: backfill upsert failed for %s: %s",
                    entry.get("id", "?"), exc)
        return False


def backfill_from_jsonl(
    jsonl_path: str = "/opt/nexus/agents/logs/task_log.jsonl",
    *,
    _collection_name: str = COLLECTION_NAME,
) -> int:
    """Read all entries from *jsonl_path* and upsert into ChromaDB.

    Returns count of entries successfully indexed.
    """
    path = Path(jsonl_path)
    if not path.exists():
        log.warning("knowledge_indexer: backfill path not found: %s", jsonl_path)
        return 0

    indexed = 0
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                log.warning("knowledge_indexer: skipping corrupt JSONL line")
                continue
            if _index_entry_sync(entry, _collection_name):
                indexed += 1

    log.info("knowledge_indexer: backfilled %d entries from %s", indexed, jsonl_path)
    return indexed


# ── CLI entrypoint ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    count = backfill_from_jsonl()
    print(f"Indexed {count} task log entries into ChromaDB")
