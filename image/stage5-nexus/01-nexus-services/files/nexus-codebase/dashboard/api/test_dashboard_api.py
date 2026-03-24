"""Tests for dashboard_api.py
Run: cd /opt/nexus/dashboard/api && python3 -m pytest test_dashboard_api.py -v --tb=short
"""

import importlib as _importlib
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import httpx

# ---------------------------------------------------------------------------
# Ensure the api directory is importable and dashboard_api loads cleanly
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))

import dashboard_api
from dashboard_api import app

# ---------------------------------------------------------------------------
# pytest-asyncio: mark all async tests automatically
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Shared fixture: httpx async client backed by the FastAPI ASGI app
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ===========================================================================
# 1. test_health_proxy
# ===========================================================================
async def test_health_proxy(client):
    mock_data = {"status": "ok", "connected_clients": 3, "queue_size": 0}
    with patch("dashboard_api._http_get", new=AsyncMock(return_value=mock_data)):
        r = await client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "connected_clients" in data


# ===========================================================================
# 2. test_nodes_proxy
# ===========================================================================
async def test_nodes_proxy(client):
    mock_nodes = [
        {"hostname": "nexus-master", "ip": "10.0.20.3", "resources": {"cpu_percent": 42}},
        {"hostname": "nexus-ai",     "ip": "10.0.20.4", "resources": {"cpu_percent": 15}},
    ]
    with patch("dashboard_api._http_get", new=AsyncMock(return_value=mock_nodes)):
        r = await client.get("/api/nodes")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["hostname"] == "nexus-master"


# ===========================================================================
# 3. test_blockchain_summary
# ===========================================================================
async def test_blockchain_summary(client):
    dashboard_api._cache.clear()

    mock_w3 = MagicMock()
    mock_w3.is_connected.return_value = True
    mock_w3.eth.block_number = 1800
    mock_w3.eth.chain_id = 123454321
    # Empty signer list to avoid Web3.to_checksum_address complexity
    mock_w3.manager.request_blocking.return_value = []

    with patch("dashboard_api._get_w3", return_value=mock_w3), \
         patch("dashboard_api._w3_contract", return_value=(mock_w3, None)):
        r = await client.get("/api/blockchain/summary")

    assert r.status_code == 200
    data = r.json()
    assert data["block_number"]      == 1800
    assert data["chain_id"]          == 123454321
    assert "validators"              in data
    assert "reasoning_entries"       in data
    assert "registered_nodes"        in data
    assert "mesh_peers"              in data


# ===========================================================================
# 4. test_blockchain_blocks
# ===========================================================================
async def test_blockchain_blocks(client):
    def make_block(n):
        return {
            "number":       n,
            "timestamp":    1700000000 + n * 12,
            "transactions": ["tx1", "tx2"],
            "miner":        "0xabcdef1234",
            "gasUsed":      21000,
        }

    mock_w3 = MagicMock()
    mock_w3.is_connected.return_value = True
    mock_w3.eth.block_number = 1802
    mock_w3.eth.get_block.side_effect = make_block

    with patch("dashboard_api._get_w3", return_value=mock_w3):
        r = await client.get("/api/blockchain/blocks?count=3")

    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 3
    assert "number"    in data[0]
    assert "timestamp" in data[0]
    assert "tx_count"  in data[0]
    assert "miner"     in data[0]
    assert data[0]["tx_count"] == 2


# ===========================================================================
# 5. test_blockchain_transactions
# ===========================================================================
async def test_blockchain_transactions(client):
    fake_hash = MagicMock()
    fake_hash.hex.return_value = "0xdeadbeef00000000"

    tx = {
        "hash":  fake_hash,
        "from":  "0xSender",
        "to":    "0xContract",
        "value": 0,
        "input": b"\x12\x34\x56",
    }
    # dict supports both [] and .get()
    tx_obj = MagicMock()
    tx_obj.__getitem__ = lambda s, k: tx[k]
    tx_obj.get = lambda k, d=None: tx.get(k, d)

    block = {"transactions": [tx_obj]}
    block_obj = MagicMock()
    block_obj.__getitem__ = lambda s, k: block[k]

    receipt_obj = MagicMock()
    receipt_obj.__getitem__ = lambda s, k: {"gasUsed": 50000}[k]

    mock_w3 = MagicMock()
    mock_w3.is_connected.return_value = True
    mock_w3.eth.get_block.return_value = block_obj
    mock_w3.eth.get_transaction_receipt.return_value = receipt_obj

    with patch("dashboard_api._get_w3", return_value=mock_w3):
        r = await client.get("/api/blockchain/transactions?block=1800")

    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 1
    txn = data[0]
    assert "hash"          in txn
    assert "from"          in txn
    assert "to"            in txn
    assert "value_eth"     in txn
    assert "gas_used"      in txn
    assert "input_preview" in txn


# ===========================================================================
# 6. test_tasks_queue
# ===========================================================================
async def test_tasks_queue(client):
    dashboard_api._task_queue_cache_ts = 0

    mock_payload = {
        "type":  "queue_status",
        "queue": [{"id": "abc", "description": "do x", "status": "pending"}],
    }
    mock_ws = AsyncMock()
    mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
    mock_ws.__aexit__  = AsyncMock(return_value=False)
    mock_ws.send = AsyncMock()
    mock_ws.recv = AsyncMock(return_value=json.dumps(mock_payload))

    with patch("websockets.connect", return_value=mock_ws):
        r = await client.get("/api/tasks/queue")

    assert r.status_code == 200
    data = r.json()
    assert "queue" in data or "type" in data


# ===========================================================================
# 7. test_tasks_history
# ===========================================================================
async def test_tasks_history(client, tmp_path):
    log_file = tmp_path / "task_log.jsonl"
    entries = [
        {"id": f"task-{i}", "description": f"task {i}",
         "status": "completed", "timestamp": 1700000000 + i}
        for i in range(5)
    ]
    log_file.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    with patch.object(dashboard_api, "TASK_LOG_FILE", log_file):
        r = await client.get("/api/tasks/history?limit=3")

    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 3
    assert data[0]["id"] == "task-4"   # reversed — most recent first


# ===========================================================================
# 8. test_tasks_submit
# ===========================================================================
async def test_tasks_submit(client):
    mock_resp = {"status": "queued", "task_id": "new-task-id"}
    mock_ws = AsyncMock()
    mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
    mock_ws.__aexit__  = AsyncMock(return_value=False)
    mock_ws.send = AsyncMock()
    mock_ws.recv = AsyncMock(return_value=json.dumps(mock_resp))

    with patch("websockets.connect", return_value=mock_ws):
        r = await client.post(
            "/api/tasks/submit",
            json={"description": "run the test suite", "priority": "P2"},
        )

    assert r.status_code == 200
    # Verify WS message contained the right fields
    sent_raw = mock_ws.send.call_args[0][0]
    msg = json.loads(sent_raw)
    assert msg["type"] == "submit_task"
    assert msg["payload"]["description"] == "run the test suite"
    assert msg["payload"]["priority"]    == "P2"


# ===========================================================================
# 9. test_knowledge_collections
# ===========================================================================
async def test_knowledge_collections(client):
    mock_data = [
        {"name": "nexus_docs", "id": "col-1", "metadata": {"desc": "docs"}},
        {"name": "agent_logs", "id": "col-2", "metadata": {}},
    ]
    with patch("dashboard_api._http_get", new=AsyncMock(return_value=mock_data)):
        r = await client.get("/api/knowledge/collections")

    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["name"] == "nexus_docs"
    assert "id" in data[0]


# ===========================================================================
# 10. test_knowledge_search
# ===========================================================================
async def test_knowledge_search(client):
    mock_results = {
        "ids":       [["id1", "id2"]],
        "documents": [["doc text one", "doc text two"]],
        "distances": [[0.12, 0.34]],
    }
    with patch("dashboard_api._http_post", new=AsyncMock(return_value=mock_results)):
        r = await client.post(
            "/api/knowledge/search",
            json={"collection": "nexus_docs", "query": "agent status", "n": 2},
        )

    assert r.status_code == 200
    data = r.json()
    assert "documents" in data
    assert "ids"        in data


# ===========================================================================
# 11. test_agents_status
# ===========================================================================
async def test_agents_status(client, tmp_path):
    log_file = tmp_path / "task_log.jsonl"
    entries = [
        {"success": True},
        {"success": True},
        {"success": False, "error": "timeout"},
        {"success": True},
    ]
    log_file.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    # Mock aiohttp.ClientSession so LLM health-checks succeed instantly
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__  = AsyncMock(return_value=False)

    mock_sess = MagicMock()
    mock_sess.get.return_value = mock_resp
    mock_sess.__aenter__ = AsyncMock(return_value=mock_sess)
    mock_sess.__aexit__  = AsyncMock(return_value=False)

    with patch.object(dashboard_api, "TASK_LOG_FILE", log_file), \
         patch("aiohttp.ClientSession", return_value=mock_sess):
        r = await client.get("/api/agents/status")

    assert r.status_code == 200
    data = r.json()
    assert "llm_endpoints"     in data
    assert "task_success_rate" in data
    assert "total_tasks"       in data
    assert data["total_tasks"]       == 4
    assert data["task_success_rate"] == pytest.approx(0.75, abs=0.01)


# ===========================================================================
# 12. test_git_log
# ===========================================================================
async def test_git_log(client):
    fake_output = (
        "\x1eabc123def456\x1fAlice\x1f2024-01-15T10:00:00+00:00\x1fAdd overview panel\n\n"
        " 3 files changed, 150 insertions(+), 5 deletions(-)\n"
        "\x1ebebeef001122\x1fBob\x1f2024-01-14T09:00:00+00:00\x1fFix gateway proxy\n\n"
        " 1 file changed, 10 insertions(+)\n"
    )
    with patch("dashboard_api._run", new=AsyncMock(return_value=(fake_output, "", 0))):
        r = await client.get("/api/git/log?count=2")

    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["hash"]          == "abc123def456"
    assert data[0]["author"]        == "Alice"
    assert data[0]["message"]       == "Add overview panel"
    assert data[0]["files_changed"] == 3
    assert data[1]["hash"]          == "bebeef001122"


# ===========================================================================
# 13. test_git_diff
# ===========================================================================
async def test_git_diff(client):
    fake_diff = (
        "commit abc123def456abc123def456\n"
        "Author: Alice\n\n"
        "    Add overview panel\n\n"
        "diff --git a/OverviewPanel.jsx b/OverviewPanel.jsx\n"
        "+new line\n"
    )
    with patch("dashboard_api._run", new=AsyncMock(return_value=(fake_diff, "", 0))):
        r = await client.get("/api/git/diff/abc123def456abc123def456")

    assert r.status_code == 200
    data = r.json()
    assert "diff"   in data
    assert "commit" in data
    assert "Add overview panel" in data["diff"]


async def test_git_diff_invalid_hash(client):
    # Non-hex chars ('g', 'z', '-') — router accepts the path segment but the
    # endpoint's own validation rejects it before calling git
    r = await client.get("/api/git/diff/ggggzzzz-not-hex")
    assert r.status_code == 200
    assert "error" in r.json()


# ===========================================================================
# 14. test_git_branches
# ===========================================================================
async def test_git_branches(client):
    fake_output = (
        "* main   abc1234 Add overview panel\n"
        "  dev    bbb5678 WIP: training endpoints\n"
    )
    with patch("dashboard_api._run", new=AsyncMock(return_value=(fake_output, "", 0))):
        r = await client.get("/api/git/branches")

    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["name"]    == "main"
    assert data[0]["current"] is True
    assert data[1]["name"]    == "dev"
    assert data[1]["current"] is False


# ===========================================================================
# 15. test_tokens_costs
# ===========================================================================
async def test_tokens_costs(client):
    mock_th = MagicMock()
    mock_th.OPERATION_COSTS = {"inference": 10, "exec": 5, "storage_pin": 3}

    def _mock_import(name, *a, **kw):
        if name == "token_hooks":
            return mock_th
        return _importlib.import_module(name, *a, **kw)

    with patch("importlib.import_module", side_effect=_mock_import):
        r = await client.get("/api/tokens/costs")

    assert r.status_code == 200
    data = r.json()
    assert "operation_costs" in data
    assert data["currency"]  == "ECT"
    assert "inference" in data["operation_costs"]


# ===========================================================================
# 16. test_logs_gateway
# ===========================================================================
async def test_logs_gateway(client):
    fake_lines = (
        "2024-01-15T10:00:00+0000 nexus-admin nexus-gateway[1234]: INFO client connected\n"
        "2024-01-15T10:00:01+0000 nexus-admin nexus-gateway[1234]: INFO heartbeat\n"
    )
    with patch("dashboard_api._run", new=AsyncMock(return_value=(fake_lines, "", 0))):
        r = await client.get("/api/logs/gateway?lines=2")

    assert r.status_code == 200
    data = r.json()
    assert "lines" in data
    assert isinstance(data["lines"], list)
    assert len(data["lines"]) == 2
    assert "nexus-gateway" in data["lines"][0]


# ===========================================================================
# 17. test_terminal_exec_allowed
# ===========================================================================
async def test_terminal_exec_allowed(client):
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"nexus-admin\n", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        r = await client.post("/api/terminal/exec", json={"command": "hostname"})

    assert r.status_code == 200
    data = r.json()
    assert data["allowed"]     is True
    assert data["return_code"] == 0
    assert "nexus-admin" in data["stdout"]


# ===========================================================================
# 18. test_terminal_exec_blocked
# ===========================================================================
async def test_terminal_exec_blocked(client):
    r = await client.post("/api/terminal/exec", json={"command": "rm -rf /opt/nexus"})
    assert r.status_code == 200
    data = r.json()
    assert data["allowed"]     is False
    assert data["return_code"] == 126
    assert "Permission denied" in data["stderr"]


async def test_terminal_exec_blocked_import(client):
    r = await client.post("/api/terminal/exec", json={"command": "python3 -c __import__('os')"})
    assert r.status_code == 200
    data = r.json()
    assert data["allowed"] is False


# ===========================================================================
# 19. test_service_health
# ===========================================================================
async def test_service_health(client):
    async def fake_run(cmd, cwd=None):
        if cmd and cmd[0] == "systemctl":
            return ("active\n", "", 0)
        return ("", "", 0)

    async def fake_ssh_run(host, cmd, timeout=10.0):
        return "active"

    with patch("dashboard_api._run",     new=fake_run), \
         patch("dashboard_api._ssh_run", new=fake_ssh_run):
        r = await client.get("/api/health/services")

    assert r.status_code == 200
    data = r.json()
    assert "services" in data
    svcs = data["services"]
    assert isinstance(svcs, list)
    assert len(svcs) > 0
    for s in svcs:
        if "error" not in s:
            assert s["active"] is True
            assert s["state"]  == "active"


# ===========================================================================
# 20. test_training_log
# ===========================================================================
async def test_training_log(client, tmp_path):
    log_file = tmp_path / "training_log.jsonl"

    with patch.object(dashboard_api, "TRAINING_LOG_FILE", log_file):
        r = await client.post("/api/training/log", json={
            "prompt":      "Write a Python function to parse JSON",
            "outcome":     "success",
            "commit_hash": "abc123def456",
            "notes":       "worked cleanly",
        })

    assert r.status_code == 200
    assert r.json()["status"] == "logged"

    lines = [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    entry = lines[0]
    assert entry["prompt"]      == "Write a Python function to parse JSON"
    assert entry["outcome"]     == "success"
    assert entry["commit_hash"] == "abc123def456"
    assert "timestamp" in entry


async def test_training_log_missing_prompt(client, tmp_path):
    log_file = tmp_path / "training_log.jsonl"
    with patch.object(dashboard_api, "TRAINING_LOG_FILE", log_file):
        r = await client.post("/api/training/log", json={"outcome": "success"})
    assert r.status_code == 200
    assert "error" in r.json()


# ===========================================================================
# 21. test_training_sessions
# ===========================================================================
async def test_training_sessions(client, tmp_path):
    log_file = tmp_path / "training_log.jsonl"
    entries = [
        {"prompt": f"prompt {i}", "outcome": "success", "timestamp": 1700000000 + i}
        for i in range(3)
    ]
    log_file.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    with patch.object(dashboard_api, "TRAINING_LOG_FILE", log_file):
        r = await client.get("/api/training/sessions?limit=2")

    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["prompt"] == "prompt 2"   # reversed — most recent first
    assert data[1]["prompt"] == "prompt 1"


# ===========================================================================
# 22. test_training_stats
# ===========================================================================
async def test_training_stats(client, tmp_path):
    log_file = tmp_path / "training_log.jsonl"
    entries = [
        {"prompt": "p1", "outcome": "success"},
        {"prompt": "p2", "outcome": "success"},
        {"prompt": "p3", "outcome": "failed"},
        {"prompt": "p4", "outcome": "partial"},
        {"prompt": "p5", "outcome": "success"},
    ]
    log_file.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    with patch.object(dashboard_api, "TRAINING_LOG_FILE", log_file):
        r = await client.get("/api/training/stats")

    assert r.status_code == 200
    data = r.json()
    assert data["total_sessions"] == 5
    assert data["success_count"]  == 3
    assert data["fail_count"]     == 1
    assert data["partial_count"]  == 1
    assert data["success_rate"]   == 60   # round(3/5 * 100)


async def test_training_stats_empty(client, tmp_path):
    log_file = tmp_path / "training_log.jsonl"
    # File doesn't exist — should return zeros
    with patch.object(dashboard_api, "TRAINING_LOG_FILE", log_file):
        r = await client.get("/api/training/stats")
    data = r.json()
    assert data["total_sessions"] == 0
    assert data["success_rate"]   == 0


# ===========================================================================
# 23. test_training_export_pairs
# ===========================================================================
async def test_training_export_pairs(client, tmp_path):
    log_file = tmp_path / "training_log.jsonl"
    fake_diff = "commit abc123\nAuthor: Alice\n\n    Implement X\n\n+new code\n"
    entries = [
        {"prompt": "Implement X", "outcome": "success",
         "commit_hash": "abc123def456abc1", "notes": "clean impl"},
        {"prompt": "Fix Y",       "outcome": "failed",
         "commit_hash": ""},
    ]
    log_file.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    with patch.object(dashboard_api, "TRAINING_LOG_FILE", log_file), \
         patch("dashboard_api._run", new=AsyncMock(return_value=(fake_diff, "", 0))):
        r = await client.get("/api/training/export/pairs")

    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "json" in ct or "octet" in ct or "application" in ct

    lines = [json.loads(l) for l in r.text.splitlines() if l.strip()]
    assert len(lines) == 2

    pair0 = lines[0]
    assert "instruction" in pair0
    assert "response"    in pair0
    assert pair0["instruction"] == "Implement X"
    # First entry has a commit hash — response should be the git diff
    assert "Implement X" in pair0["response"] or "new code" in pair0["response"]

    pair1 = lines[1]
    assert pair1["instruction"] == "Fix Y"
    # No commit hash — response falls back to outcome
    assert pair1["response"] == "failed"


# ===========================================================================
# 24. test_training_export_raw
# ===========================================================================
async def test_training_export_raw(client, tmp_path):
    log_file = tmp_path / "training_log.jsonl"
    entries = [
        {"prompt": "test prompt", "outcome": "success"},
        {"prompt": "other prompt", "outcome": "partial"},
    ]
    raw_content = "\n".join(json.dumps(e) for e in entries) + "\n"
    log_file.write_text(raw_content)

    with patch.object(dashboard_api, "TRAINING_LOG_FILE", log_file):
        r = await client.get("/api/training/export/raw")

    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "application" in ct or "json" in ct

    lines = [json.loads(l) for l in r.text.splitlines() if l.strip()]
    assert len(lines) == 2
    assert lines[0]["prompt"] == "test prompt"
    assert lines[1]["prompt"] == "other prompt"
