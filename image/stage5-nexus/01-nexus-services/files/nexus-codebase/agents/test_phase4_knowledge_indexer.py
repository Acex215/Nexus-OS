"""Tests for knowledge_indexer.py — Phase 4 Knowledge & Learning."""

import json
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
import chromadb

import knowledge_indexer as ki

# ── Helpers ───────────────────────────────────────────────────────────────────

def _unique_collection() -> str:
    return f"test_dev_assistant_{uuid.uuid4().hex[:8]}"


def _make_entry(
    idx: int,
    success: bool = True,
    description: str = None,
) -> dict:
    return {
        "id": f"log-20260319T{idx:06d}-aabbcc",
        "task_id": f"task-{idx:03d}",
        "description": description or f"Implement feature number {idx}",
        "priority": "P1",
        "risk": "low",
        "affected_files": [f"/opt/nexus/agents/mod{idx}.py"],
        "status": "done" if success else "failed",
        "success": success,
        "error": None if success else f"Compilation error in mod{idx}.py",
        "commit_hash": f"abc{idx:04d}" if success else None,
        "blockchain_tx": None,
        "branch": f"task/task-{idx:03d}",
        "diffs": [],
        "lines_added": idx * 10,
        "lines_removed": idx,
        "files_changed": 1,
        "plan_summary": None,
        "duration_seconds": float(idx),
        "timestamp": f"2026-03-19T0{idx}:00:00+00:00",
        "sub_task_of": None,
    }


def _delete_collection(name: str) -> None:
    try:
        client = chromadb.HttpClient(host="localhost", port=8000)
        client.delete_collection(name)
    except Exception:
        pass


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_index_task(tmp_path):
    col = _unique_collection()
    try:
        entry = _make_entry(1)
        ok = await ki.index_task(entry, _collection_name=col)
        assert ok is True

        results = ki.query_similar_tasks(
            entry["description"], n=1, _collection_name=col
        )
        assert len(results) == 1
        r = results[0]
        assert r["task_id"] == entry["task_id"]
        assert r["status"] == "done"
        assert r["success"] is True
        assert "distance" in r
    finally:
        _delete_collection(col)


@pytest.mark.asyncio
async def test_query_similar(tmp_path):
    col = _unique_collection()
    try:
        entries = [
            _make_entry(1, description="Add authentication middleware to API"),
            _make_entry(2, description="Fix database connection pooling bug"),
            _make_entry(3, description="Implement JWT token refresh logic"),
        ]
        for e in entries:
            await ki.index_task(e, _collection_name=col)

        results = ki.query_similar_tasks(
            "authentication and JWT tokens", n=3, _collection_name=col
        )
        assert len(results) >= 1
        # The closest result should be auth-related (entry 1 or 3)
        top_task_ids = {r["task_id"] for r in results[:2]}
        assert top_task_ids & {"task-001", "task-003"}, (
            f"Expected auth-related task in top 2, got: {top_task_ids}"
        )
    finally:
        _delete_collection(col)


@pytest.mark.asyncio
async def test_query_failures_only(tmp_path):
    col = _unique_collection()
    try:
        for i in range(1, 4):
            await ki.index_task(_make_entry(i, success=(i <= 2)), _collection_name=col)

        results = ki.query_similar_tasks(
            "feature implementation", n=10, include_failures=False, _collection_name=col
        )
        assert len(results) >= 1
        for r in results:
            assert r["success"] is True, f"Got a failure in results: {r}"
    finally:
        _delete_collection(col)


@pytest.mark.asyncio
async def test_empty_collection(tmp_path):
    col = _unique_collection()
    try:
        # Create an empty collection by just getting/creating it, no inserts
        client = chromadb.HttpClient(host="localhost", port=8000)
        client.get_or_create_collection(col)

        results = ki.query_similar_tasks("anything at all", n=5, _collection_name=col)
        assert results == []
    finally:
        _delete_collection(col)


@pytest.mark.asyncio
async def test_backfill(tmp_path):
    col = _unique_collection()
    jsonl_file = tmp_path / "task_log.jsonl"
    try:
        entries = [_make_entry(i) for i in range(1, 4)]
        with open(jsonl_file, "w", encoding="utf-8") as fh:
            for e in entries:
                fh.write(json.dumps(e) + "\n")

        count = ki.backfill_from_jsonl(str(jsonl_file), _collection_name=col)
        assert count == 3

        client = chromadb.HttpClient(host="localhost", port=8000)
        collection = client.get_collection(col)
        assert collection.count() == 3
    finally:
        _delete_collection(col)
