"""NEXUS Command Center — FastAPI backend.

Single data source for all 13 dashboard panels.
Run:  python3 dashboard_api.py
Port: 8768
"""

import asyncio
import json
import logging
import os
import sqlite3
import subprocess
import shlex
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import io
import aiohttp
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    from web3 import Web3
    from web3.middleware import ExtraDataToPOAMiddleware
    HAS_WEB3 = True
except ImportError:
    HAS_WEB3 = False

try:
    from sentence_transformers import SentenceTransformer as _ST
    _embed_model = _ST("sentence-transformers/all-MiniLM-L6-v2")
    HAS_EMBEDDINGS = True
except Exception:
    _embed_model = None
    HAS_EMBEDDINGS = False

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CONTRACTS_DIR     = Path("/opt/nexus/contracts/deployed")
TASK_LOG_FILE     = Path("/opt/nexus/agents/logs/task_log.jsonl")
TRAINING_LOG_FILE = Path("/opt/nexus/agents/logs/training_log.jsonl")
WORLD_MODEL_DB    = Path("/opt/nexus/automation/world_model.db")
NEXUS_REPO        = "/opt/nexus"

# ---------------------------------------------------------------------------
# External service endpoints
# ---------------------------------------------------------------------------
GETH_RPC        = os.environ.get("GETH_RPC",      "http://10.0.20.3:8545")
GATEWAY_HTTP    = os.environ.get("GATEWAY_URL",   "http://10.0.20.1:8766")
GATEWAY_WS      = os.environ.get("GATEWAY_WS",    "ws://10.0.20.1:8765/ws")
CHROMADB_URL    = os.environ.get("CHROMADB_URL",  "http://10.0.20.1:8000")
CHROMADB_V2     = f"{CHROMADB_URL}/api/v2/tenants/default_tenant/databases/default_database"
VALIDATOR_NODES = ["10.0.20.3", "10.0.20.4", "10.0.20.11"]

LLM_ENDPOINTS = {
    "coordinator": "http://10.0.30.3:1234/v1/models",
    "coder":       "http://10.0.30.2:1234/v1/models",
    "director":    "http://10.0.30.3:1234/v1/models",
    "worker":      "http://10.0.20.6:11434/v1/models",
}

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("dashboard_api")

app = FastAPI(title="NEXUS Dashboard API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Contract ABI registry — loaded at startup
# ---------------------------------------------------------------------------
_contracts: dict = {}  # name → {"address": ..., "abi": [...]}

def _load_contracts():
    if not CONTRACTS_DIR.exists():
        log.warning("Contracts dir not found: %s", CONTRACTS_DIR)
        return
    for path in CONTRACTS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            name = data.get("name", path.stem)
            _contracts[name] = {"address": data["address"], "abi": data["abi"]}
            log.info("Loaded contract: %s @ %s", name, data["address"])
        except Exception as exc:
            log.warning("Failed to load %s: %s", path.name, exc)

_load_contracts()

# ---------------------------------------------------------------------------
# Web3 setup
# ---------------------------------------------------------------------------
def _get_w3() -> Optional["Web3"]:
    if not HAS_WEB3:
        return None
    try:
        w3 = Web3(Web3.HTTPProvider(GETH_RPC, request_kwargs={"timeout": 5}))
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        return w3
    except Exception:
        return None

def _w3_contract(name: str):
    w3 = _get_w3()
    if not w3:
        return None, None
    info = _contracts.get(name)
    if not info:
        return w3, None
    try:
        addr = Web3.to_checksum_address(info["address"])
        return w3, w3.eth.contract(address=addr, abi=info["abi"])
    except Exception:
        return w3, None

# ---------------------------------------------------------------------------
# Simple in-memory cache
# ---------------------------------------------------------------------------
_cache: dict = {}

def _cache_get(key: str, ttl: float):
    entry = _cache.get(key)
    if entry and (time.monotonic() - entry["ts"]) < ttl:
        return entry["val"]
    return None

def _cache_set(key: str, val):
    _cache[key] = {"val": val, "ts": time.monotonic()}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _http_get(url: str, timeout: float = 5.0):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
        async with s.get(url) as r:
            return await r.json(content_type=None)

async def _http_post(url: str, body: dict, timeout: float = 10.0):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
        async with s.post(url, json=body) as r:
            return await r.json(content_type=None)

async def _run(cmd: list[str], cwd: str = None) -> tuple[str, str, int]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
    return stdout.decode(errors="replace"), stderr.decode(errors="replace"), proc.returncode

async def _ssh_run(host: str, cmd: str, timeout: float = 10.0) -> str:
    try:
        stdout, _, rc = await asyncio.wait_for(
            _run(["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
                  f"mhuraibi@{host}", cmd]),
            timeout=timeout,
        )
        return stdout.strip()
    except Exception as exc:
        return f"ssh error: {exc}"

# ---------------------------------------------------------------------------
# CLIENT CONFIG
# ---------------------------------------------------------------------------
@app.get("/api/config")
async def get_config():
    return {"gateway_ws": GATEWAY_WS}

# ---------------------------------------------------------------------------
# GATEWAY PROXY
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def get_health():
    try:
        return await _http_get(f"{GATEWAY_HTTP}/health", timeout=5)
    except Exception as exc:
        return {"error": "gateway unreachable", "detail": str(exc)}

@app.get("/api/nodes")
async def get_nodes():
    try:
        return await _http_get(f"{GATEWAY_HTTP}/nodes", timeout=5)
    except Exception as exc:
        return {"error": "gateway unreachable", "detail": str(exc)}

@app.get("/api/clients")
async def get_clients():
    try:
        return await _http_get(f"{GATEWAY_HTTP}/clients", timeout=5)
    except Exception as exc:
        return {"error": "gateway unreachable", "detail": str(exc)}

# ---------------------------------------------------------------------------
# BLOCKCHAIN
# ---------------------------------------------------------------------------
@app.get("/api/blockchain/summary")
async def blockchain_summary():
    cached = _cache_get("bc_summary", 15)
    if cached:
        return cached

    try:
        w3 = _get_w3()
        if not w3 or not w3.is_connected():
            return {"error": "blockchain unreachable"}

        block_number = w3.eth.block_number
        chain_id     = w3.eth.chain_id

        # Clique validators
        try:
            raw_signers = w3.manager.request_blocking("clique_getSigners", ["latest"])
            validators = []
            for addr in raw_signers:
                try:
                    bal_wei = w3.eth.get_balance(Web3.to_checksum_address(addr))
                    bal_eth = float(Web3.from_wei(bal_wei, "ether"))
                except Exception:
                    bal_eth = 0.0
                validators.append({"address": addr, "balance_eth": bal_eth})
        except Exception:
            validators = []

        # ReasoningLedger entry count
        reasoning_entries = 0
        _, rl = _w3_contract("ReasoningLedger")
        if rl:
            try:
                reasoning_entries = rl.functions.getEntryCount().call()
            except Exception:
                pass

        # ResourceManager node count
        registered_nodes = 0
        _, rm = _w3_contract("ResourceManager")
        if rm:
            try:
                registered_nodes = rm.functions.getNodeCount().call()
            except Exception:
                pass

        # MeshRegistry peer count
        mesh_peers = 0
        _, mr = _w3_contract("MeshRegistry")
        if mr:
            try:
                mesh_peers = mr.functions.getPeerCount().call()
            except Exception:
                pass

        result = {
            "block_number":       block_number,
            "chain_id":           chain_id,
            "validators":         validators,
            "reasoning_entries":  reasoning_entries,
            "registered_nodes":   registered_nodes,
            "mesh_peers":         mesh_peers,
        }
        _cache_set("bc_summary", result)
        return result

    except Exception as exc:
        return {"error": "blockchain unreachable", "detail": str(exc)}


@app.get("/api/blockchain/blocks")
async def blockchain_blocks(count: int = 20):
    try:
        w3 = _get_w3()
        if not w3 or not w3.is_connected():
            return {"error": "blockchain unreachable"}

        latest = w3.eth.block_number
        blocks = []
        for n in range(latest, max(0, latest - count), -1):
            try:
                b = w3.eth.get_block(n)
                blocks.append({
                    "number":    b["number"],
                    "timestamp": b["timestamp"],
                    "tx_count":  len(b["transactions"]),
                    "miner":     b["miner"],
                    "gas_used":  b["gasUsed"],
                })
            except Exception:
                break
        return blocks

    except Exception as exc:
        return {"error": "blockchain unreachable", "detail": str(exc)}


@app.get("/api/blockchain/transactions")
async def blockchain_transactions(block: int):
    try:
        w3 = _get_w3()
        if not w3 or not w3.is_connected():
            return {"error": "blockchain unreachable"}

        b = w3.eth.get_block(block, full_transactions=True)
        txns = []
        for tx in b["transactions"]:
            try:
                receipt = w3.eth.get_transaction_receipt(tx["hash"])
                gas_used = receipt["gasUsed"]
            except Exception:
                gas_used = 0
            input_data = tx.get("input", b"")
            if isinstance(input_data, (bytes, bytearray)):
                input_hex = input_data.hex()
            else:
                input_hex = str(input_data)
            txns.append({
                "hash":          tx["hash"].hex(),
                "from":          tx.get("from", ""),
                "to":            tx.get("to", ""),
                "value_eth":     float(Web3.from_wei(tx.get("value", 0), "ether")),
                "gas_used":      gas_used,
                "input_preview": input_hex[:64] + ("..." if len(input_hex) > 64 else ""),
            })
        return txns

    except Exception as exc:
        return {"error": "blockchain unreachable", "detail": str(exc)}


@app.get("/api/blockchain/contract/{name}")
async def blockchain_contract(name: str):
    w3, contract = _w3_contract(name)
    if not w3:
        return {"error": "blockchain unreachable"}
    if not contract:
        return {"error": f"contract '{name}' not found", "available": list(_contracts.keys())}

    info = _contracts[name]
    result = {"name": name, "address": info["address"], "data": {}}

    try:
        if name == "ReasoningLedger":
            result["data"]["entry_count"] = contract.functions.getEntryCount().call()
        elif name == "ResourceManager":
            result["data"]["node_count"] = contract.functions.getNodeCount().call()
            try:
                addrs = contract.functions.getAllNodes().call()
                nodes = []
                for addr in addrs[:20]:
                    try:
                        n = contract.functions.getNode(Web3.to_checksum_address(addr)).call()
                        nodes.append({
                            "wallet":    addr,
                            "hostname":  n[0],
                            "cpu_cores": n[1],
                            "memory_gb": n[2],
                            "storage_gb":n[3],
                            "ai_tops":   n[4],
                            "active":    n[5],
                        })
                    except Exception:
                        pass
                result["data"]["nodes"] = nodes
            except Exception:
                pass
        elif name == "MeshRegistry":
            result["data"]["peer_count"] = contract.functions.getPeerCount().call()
        elif name == "TokenManager":
            try:
                totals = contract.functions.getTotals().call()
                result["data"] = {
                    "ect_minted":  totals[0],
                    "ect_spent":   totals[1],
                    "rst_earned":  totals[2],
                    "rst_slashed": totals[3],
                }
            except Exception:
                pass
    except Exception as exc:
        result["error"] = str(exc)

    return result

# ---------------------------------------------------------------------------
# TASKS
# ---------------------------------------------------------------------------
_task_queue_cache_ts: float = 0
_task_queue_cache_val: dict = {}

@app.get("/api/tasks/queue")
async def tasks_queue():
    global _task_queue_cache_ts, _task_queue_cache_val
    if time.monotonic() - _task_queue_cache_ts < 5:
        return _task_queue_cache_val

    try:
        import websockets
        msg = {"type": "queue_status", "timestamp": datetime.now(timezone.utc).isoformat()}
        async with websockets.connect(GATEWAY_WS, open_timeout=3, close_timeout=3) as ws:
            await asyncio.wait_for(ws.send(json.dumps(msg)), timeout=3)
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(raw)
            _task_queue_cache_ts  = time.monotonic()
            _task_queue_cache_val = data
            return data
    except Exception as exc:
        return {"error": "gateway unreachable", "detail": str(exc)}


@app.get("/api/tasks/history")
async def tasks_history(limit: int = 100):
    if not TASK_LOG_FILE.exists():
        return []
    try:
        entries = []
        with open(TASK_LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
        return list(reversed(entries[-limit:]))
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/tasks/submit")
async def tasks_submit(body: dict):
    description = body.get("description", "")
    priority    = body.get("priority", "medium")
    if not description:
        return {"error": "description required"}
    try:
        import websockets
        msg = {
            "type":      "submit_task",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload":   {"description": description, "priority": priority},
        }
        async with websockets.connect(GATEWAY_WS, open_timeout=3, close_timeout=3) as ws:
            await asyncio.wait_for(ws.send(json.dumps(msg)), timeout=3)
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            return json.loads(raw)
    except Exception as exc:
        return {"error": "gateway unreachable", "detail": str(exc)}

# ---------------------------------------------------------------------------
# KNOWLEDGE (ChromaDB)
# ---------------------------------------------------------------------------
@app.get("/api/knowledge/collections")
async def knowledge_collections():
    try:
        data = await _http_get(f"{CHROMADB_V2}/collections")
        if isinstance(data, list):
            async def _count(col_id: str) -> int:
                try:
                    r = await _http_get(f"{CHROMADB_V2}/collections/{col_id}/count")
                    return r if isinstance(r, int) else 0
                except Exception:
                    return 0
            counts = await asyncio.gather(*[_count(c.get("id", "")) for c in data])
            result = []
            for col, cnt in zip(data, counts):
                result.append({
                    "name":     col.get("name"),
                    "id":       col.get("id"),
                    "count":    cnt,
                    "metadata": col.get("metadata", {}),
                })
            return result
        return data
    except Exception as exc:
        return {"error": "chromadb unreachable", "detail": str(exc)}


@app.post("/api/knowledge/search")
async def knowledge_search(body: dict):
    collection = body.get("collection")
    query      = body.get("query", "")
    n          = int(body.get("n", 5))
    if not collection or not query:
        return {"error": "collection and query required"}
    if not HAS_EMBEDDINGS:
        return {"error": "embedding model unavailable"}
    try:
        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(
            None, lambda: _embed_model.encode([query])[0].tolist()
        )
        # Get collection UUID first (ChromaDB v1.5.2 query requires UUID path)
        col_info = await _http_get(f"{CHROMADB_V2}/collections/{collection}")
        col_id   = col_info.get("id") if isinstance(col_info, dict) else None
        if not col_id:
            return {"error": f"collection '{collection}' not found"}
        results = await _http_post(
            f"{CHROMADB_V2}/collections/{col_id}/query",
            {"query_embeddings": [embedding], "n_results": n,
             "include": ["documents", "metadatas", "distances"]},
        )
        return results
    except Exception as exc:
        return {"error": "chromadb unreachable", "detail": str(exc)}

# ---------------------------------------------------------------------------
# AGENTS
# ---------------------------------------------------------------------------
@app.get("/api/agents/status")
async def agents_status():
    # LLM health checks
    llm_results = {}
    async def _check_llm(name: str, url: str):
        start = time.monotonic()
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4)) as s:
                async with s.get(url) as r:
                    latency_ms = int((time.monotonic() - start) * 1000)
                    ok = r.status == 200
                    llm_results[name] = {"ok": ok, "latency_ms": latency_ms, "url": url}
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            llm_results[name] = {"ok": False, "latency_ms": latency_ms, "url": url, "error": str(exc)}

    await asyncio.gather(*[_check_llm(k, v) for k, v in LLM_ENDPOINTS.items()])

    # Task success rate from log
    success_count = 0
    fail_count    = 0
    fail_cats: dict = {}
    if TASK_LOG_FILE.exists():
        try:
            with open(TASK_LOG_FILE) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("success"):
                            success_count += 1
                        else:
                            fail_count += 1
                            err = str(entry.get("error") or "unknown")[:80]
                            fail_cats[err] = fail_cats.get(err, 0) + 1
                    except Exception:
                        pass
        except Exception:
            pass

    total = success_count + fail_count
    return {
        "llm_endpoints":     llm_results,
        "task_success_rate": round(success_count / total, 3) if total else None,
        "total_tasks":       total,
        "failed_tasks":      fail_count,
        "failure_categories": dict(sorted(fail_cats.items(), key=lambda x: -x[1])[:10]),
    }

# ---------------------------------------------------------------------------
# GIT
# ---------------------------------------------------------------------------
@app.get("/api/git/log")
async def git_log(count: int = 30):
    import re
    # Use --shortstat: stat summary appears on its own line after each commit block,
    # separated by a blank line. Use \x1e as commit delimiter BEFORE the hash.
    fmt = "\x1e%H\x1f%an\x1f%aI\x1f%s"
    stdout, _, rc = await _run(
        ["git", "log", f"-{count}", f"--format=tformat:{fmt}", "--shortstat"],
        cwd=NEXUS_REPO,
    )
    if rc != 0:
        return {"error": "git log failed"}

    entries = []
    # Each chunk starts with \x1e and contains: HASH\x1fAUTHOR\x1fDATE\x1fSUBJECT\n\n[shortstat]
    for chunk in stdout.split("\x1e"):
        chunk = chunk.strip()
        if not chunk:
            continue
        lines = chunk.split("\n", 1)
        parts = lines[0].split("\x1f", 3)
        if len(parts) < 4:
            continue
        hash_, author, date, subject = parts
        # Parse files_changed from shortstat line if present
        files_changed = 0
        rest = lines[1] if len(lines) > 1 else ""
        m = re.search(r"(\d+) file", rest)
        if m:
            files_changed = int(m.group(1))
        entries.append({
            "hash":          hash_.strip(),
            "author":        author.strip(),
            "date":          date.strip(),
            "message":       subject.strip(),
            "files_changed": files_changed,
        })
    return entries


@app.get("/api/git/diff/{commit_hash}")
async def git_diff(commit_hash: str):
    # Validate: only hex chars and length
    if not all(c in "0123456789abcdefABCDEF" for c in commit_hash) or len(commit_hash) > 64:
        return {"error": "invalid commit hash"}
    stdout, stderr, rc = await _run(
        ["git", "show", "--stat", commit_hash],
        cwd=NEXUS_REPO,
    )
    if rc != 0:
        return {"error": f"git show failed: {stderr.strip()}"}
    return {"commit": commit_hash, "diff": stdout}


@app.get("/api/git/branches")
async def git_branches():
    stdout, _, rc = await _run(
        ["git", "branch", "-v", "--sort=-committerdate"],
        cwd=NEXUS_REPO,
    )
    if rc != 0:
        return {"error": "git branch failed"}
    branches = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        current = line.startswith("*")
        parts   = line.lstrip("* ").split(None, 2)
        branches.append({
            "name":         parts[0] if parts else "",
            "last_commit":  parts[1] if len(parts) > 1 else "",
            "message":      parts[2] if len(parts) > 2 else "",
            "current":      current,
        })
    return branches

# ---------------------------------------------------------------------------
# TOKENS
# ---------------------------------------------------------------------------
@app.get("/api/tokens/costs")
async def tokens_costs():
    # Import OPERATION_COSTS from token_hooks without running the module as __main__
    sys.path.insert(0, "/opt/nexus/agents")
    try:
        import importlib
        th = importlib.import_module("token_hooks")
        costs = dict(th.OPERATION_COSTS)
    except Exception as exc:
        costs = {"error": str(exc)}
    return {"operation_costs": costs, "currency": "ECT", "enforcement_enabled": False}


@app.get("/api/tokens/activity")
async def tokens_activity():
    # Read from TokenManager contract events if reachable, else return empty
    w3, tm = _w3_contract("TokenManager")
    if not tm:
        return {"events": [], "error": "TokenManager not accessible"}
    try:
        latest = w3.eth.block_number
        from_block = max(0, latest - 500)
        events = []

        ect_spent = tm.events.ECTSpent.get_logs(fromBlock=from_block, toBlock=latest)
        for e in list(ect_spent)[-50:]:
            events.append({
                "type":      "ECTSpent",
                "agent":     e["args"]["agent"],
                "amount":    e["args"]["amount"],
                "block":     e["blockNumber"],
                "tx":        e["transactionHash"].hex(),
            })

        rst_earned = tm.events.RSTEarned.get_logs(fromBlock=from_block, toBlock=latest)
        for e in list(rst_earned)[-50:]:
            events.append({
                "type":   "RSTEarned",
                "agent":  e["args"]["agent"],
                "amount": e["args"]["amount"],
                "reason": e["args"]["reason"],
                "block":  e["blockNumber"],
                "tx":     e["transactionHash"].hex(),
            })

        events.sort(key=lambda x: x["block"], reverse=True)
        return {"events": events[:100]}
    except Exception as exc:
        return {"events": [], "error": str(exc)}


@app.get("/api/tokens/summary")
async def tokens_summary():
    sys.path.insert(0, "/opt/nexus/agents")
    ops_count = 0
    enforcement_enabled = os.environ.get("ENFORCEMENT_ENABLED", "false").lower() == "true"
    try:
        import importlib
        th = importlib.import_module("token_hooks")
        ops_count = len(th.OPERATION_COSTS)
        enforcement_enabled = th.ENFORCEMENT_ENABLED
    except Exception:
        pass

    total_logged = 0
    if TASK_LOG_FILE.exists():
        try:
            with open(TASK_LOG_FILE) as f:
                total_logged = sum(1 for line in f if line.strip())
        except Exception:
            pass

    contract_address = None
    totals = {}
    registered_nodes = 0
    try:
        sys.path.insert(0, "/opt/nexus")
        from libnexus.token_client import TokenClient
        tc = TokenClient()
        contract_address = tc.address
        totals = tc.get_totals()
    except Exception:
        pass

    _, rm = _w3_contract("ResourceManager")
    if rm:
        try:
            registered_nodes = rm.functions.getNodeCount().call()
        except Exception:
            pass

    return {
        "enforcement_enabled":      enforcement_enabled,
        "operations_defined":       ops_count,
        "total_logged_operations":  total_logged,
        "contract_address":         contract_address,
        "totals":                   totals,
        "registered_nodes":         registered_nodes,
    }


@app.get("/api/tokens/balances")
async def tokens_balances():
    w3, rm = _w3_contract("ResourceManager")
    _, tm = _w3_contract("TokenManager")
    if not rm or not tm:
        return {"error": "blockchain unreachable", "nodes": [], "totals": {}}

    try:
        addresses = rm.functions.getAllNodes().call()
    except Exception as exc:
        return {"error": f"ResourceManager unavailable: {exc}", "nodes": [], "totals": {}}

    # Build hostname lookup from ResourceManager
    hostname_map = {}
    for addr in addresses:
        try:
            n = rm.functions.getNode(Web3.to_checksum_address(addr)).call()
            hostname_map[addr.lower()] = n[0]
        except Exception:
            pass

    nodes = []
    for addr in addresses:
        try:
            ect, rst = tm.functions.getBalances(Web3.to_checksum_address(addr)).call()
            nodes.append({
                "address":     addr,
                "hostname":    hostname_map.get(addr.lower(), ""),
                "ect_balance": ect,
                "rst_balance": rst,
            })
        except Exception:
            nodes.append({"address": addr, "hostname": hostname_map.get(addr.lower(), ""),
                          "ect_balance": None, "rst_balance": None})

    totals = {}
    try:
        em, es, re_, rs = tm.functions.getTotals().call()
        totals = {"ect_minted": em, "ect_spent": es, "rst_earned": re_, "rst_slashed": rs}
    except Exception:
        pass

    return {"nodes": nodes, "totals": totals}


@app.get("/api/tokens/balance/{address}")
async def tokens_balance_address(address: str):
    if not HAS_WEB3:
        return {"error": "web3 not available"}
    try:
        addr = Web3.to_checksum_address(address)
    except Exception:
        return {"error": f"invalid address: {address}"}

    w3, tm = _w3_contract("TokenManager")
    if not tm:
        return {"error": "TokenManager not accessible"}

    try:
        ect, rst = tm.functions.getBalances(addr).call()
    except Exception as exc:
        return {"error": str(exc)}

    # Spending history — last 50 entries
    spend_history = []
    try:
        latest = w3.eth.block_number
        amounts, task_ids, blocks, timestamps = tm.functions.getSpendingHistory(
            addr, 0, latest
        ).call()
        entries = list(zip(amounts, task_ids, blocks, timestamps))
        for a, t, b, ts in entries[-50:]:
            spend_history.append({"amount": a, "task_id": t.hex(), "block": b, "timestamp": ts})
        spend_history.reverse()
    except Exception:
        pass

    # RST history — last 20 entries
    rst_history = []
    try:
        count = tm.functions.getRSTHistoryCount(addr).call()
        start = max(0, count - 20)
        for i in range(start, count):
            amount, reason, block_num, timestamp = tm.functions.getRSTRecord(addr, i).call()
            rst_history.append({
                "amount": int(amount), "reason": reason,
                "block": block_num, "timestamp": timestamp,
            })
        rst_history.reverse()
    except Exception:
        pass

    return {
        "address":       addr,
        "ect_balance":   ect,
        "rst_balance":   rst,
        "spend_history": spend_history,
        "rst_history":   rst_history,
    }

# ---------------------------------------------------------------------------
# LOGS
# ---------------------------------------------------------------------------
async def _journalctl(unit: str, lines: int) -> list[str]:
    stdout, _, _ = await _run(
        ["journalctl", "-u", unit, "--no-pager", "-n", str(lines), "--output=short-iso"],
    )
    return stdout.splitlines()


@app.get("/api/logs/gateway")
async def logs_gateway(lines: int = 100):
    return {"lines": await _journalctl("nexus-gateway", lines)}


@app.get("/api/logs/dashboard-api")
async def logs_dashboard_api(lines: int = 100):
    return {"lines": await _journalctl("nexus-dashboard-api", lines)}


@app.get("/api/logs/node-agent")
async def logs_node_agent(lines: int = 100, node: str = "nexus-master"):
    node_ips = {
        "nexus-master":   "10.0.20.3",
        "nexus-ai":       "10.0.20.4",
        "nexus-storage":  "10.0.20.11",
        "nexus-ai2":      "10.0.20.6",
    }
    if node not in node_ips:
        return {"error": f"unknown node '{node}'", "known": list(node_ips.keys())}
    ip  = node_ips[node]
    cmd = f"journalctl -u nexus-node-agent --no-pager -n {lines} --output=short-iso 2>&1 || journalctl -u node-agent --no-pager -n {lines} --output=short-iso 2>&1"
    out = await _ssh_run(ip, cmd)
    return {"node": node, "lines": out.splitlines()}


@app.post("/api/logs/search")
async def logs_search(body: dict):
    service = body.get("service", "nexus-gateway")
    query   = body.get("query", "")
    lines   = int(body.get("lines", 200))
    if not query:
        return {"error": "query required"}
    raw_lines = await _journalctl(service, lines)
    matched = [l for l in raw_lines if query.lower() in l.lower()]
    return {"service": service, "query": query, "matches": matched, "total_searched": len(raw_lines)}

# ---------------------------------------------------------------------------
# SYSTEM HEALTH
# ---------------------------------------------------------------------------
@app.get("/api/health/timeline")
async def health_timeline():
    if not WORLD_MODEL_DB.exists():
        return {"error": "world_model.db not found", "events": []}
    try:
        conn = sqlite3.connect(str(WORLD_MODEL_DB))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT node_name, service_name, status, extra_json, timestamp "
            "FROM service_health ORDER BY timestamp DESC LIMIT 500"
        ).fetchall()
        conn.close()
        events = []
        for r in rows:
            extra = {}
            try:
                extra = json.loads(r["extra_json"])
            except Exception:
                pass
            events.append({
                "node":      r["node_name"],
                "service":   r["service_name"],
                "status":    r["status"],
                "extra":     extra,
                "timestamp": r["timestamp"],
            })
        return {"events": events}
    except Exception as exc:
        return {"error": str(exc), "events": []}


@app.get("/api/health/services")
async def health_services():
    local_services = ["nexus-gateway", "nexus-dashboard-api", "chromadb", "ipfs", "k3s-agent"]
    remote_services = {
        "10.0.20.3":  ["nexus-geth"],
        "10.0.20.4":  ["nexus-geth"],
        "10.0.20.11": ["nexus-geth"],
    }

    async def _check_local(svc: str) -> dict:
        stdout, _, rc = await _run(["systemctl", "is-active", svc])
        state = stdout.strip()
        return {"service": svc, "node": "nexus-admin", "active": state == "active", "state": state}

    async def _check_remote(host: str, svc: str) -> dict:
        out = await _ssh_run(host, f"systemctl is-active {svc}")
        state = out.strip()
        return {"service": svc, "node": host, "active": state == "active", "state": state}

    tasks = [_check_local(s) for s in local_services]
    for host, svcs in remote_services.items():
        for svc in svcs:
            tasks.append(_check_remote(host, svc))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    services = []
    for r in results:
        if isinstance(r, Exception):
            services.append({"error": str(r)})
        else:
            services.append(r)
    return {"services": services}

# ---------------------------------------------------------------------------
# MESH PEERS — on-chain + discovered
# ---------------------------------------------------------------------------
DISCOVERED_PEERS_FILE = Path("/opt/nexus/config/discovered_peers.json")

@app.get("/api/mesh/peers")
async def mesh_peers():
    """Return mesh peers from MeshRegistry (on-chain) + discovered_peers.json."""
    onchain_peers = []
    w3, contract = _w3_contract("MeshRegistry")
    if w3 and contract:
        try:
            count = contract.functions.getPeerCount().call()
            for i in range(count):
                addr = contract.functions.getPeerAddress(i).call()
                enode, wg_pub, mesh_ip, active = contract.functions.getPeer(addr).call()
                # enode stores "ip:port", wg_pub stores capabilities
                ip, port = "", 0
                if ":" in enode:
                    parts = enode.rsplit(":", 1)
                    ip = parts[0]
                    try:
                        port = int(parts[1])
                    except ValueError:
                        port = 0
                elif enode:
                    ip = enode
                onchain_peers.append({
                    "wallet": addr,
                    "ip": ip or mesh_ip,
                    "port": port,
                    "capabilities": wg_pub,
                    "mesh_ip": mesh_ip,
                    "active": active,
                    "source": "onchain",
                })
        except Exception as exc:
            log.warning("MeshRegistry read failed: %s", exc)

    discovered_peers = []
    if DISCOVERED_PEERS_FILE.exists():
        try:
            data = json.loads(DISCOVERED_PEERS_FILE.read_text())
            for wallet, info in data.items():
                discovered_peers.append({
                    "wallet": wallet,
                    "ip": info.get("ip", ""),
                    "port": info.get("port", 0),
                    "capabilities": info.get("capabilities", ""),
                    "last_seen": info.get("last_seen_iso", ""),
                    "source": info.get("source", "discovery"),
                })
        except Exception as exc:
            log.warning("discovered_peers.json read failed: %s", exc)

    # Merge: on-chain peers take priority, add any discovery-only peers
    seen_wallets = {p["wallet"] for p in onchain_peers}
    merged = list(onchain_peers)
    for dp in discovered_peers:
        if dp["wallet"] not in seen_wallets:
            merged.append(dp)

    return {"peers": merged, "onchain_count": len(onchain_peers), "discovered_count": len(discovered_peers)}

# ---------------------------------------------------------------------------
# DATA MINING — results from scheduled mining job
# ---------------------------------------------------------------------------
MINING_RESULTS_FILE = Path("/opt/nexus/logs/mining_results.json")

def _read_mining_results() -> dict:
    if not MINING_RESULTS_FILE.exists():
        return {"error": "no mining results yet", "timestamp": None}
    try:
        return json.loads(MINING_RESULTS_FILE.read_text())
    except Exception as exc:
        return {"error": str(exc), "timestamp": None}

@app.get("/api/mining/results")
async def mining_results():
    """Full mining results from latest run."""
    return _read_mining_results()

@app.get("/api/mining/patterns")
async def mining_patterns():
    """Association rules only."""
    data = _read_mining_results()
    return {"timestamp": data.get("timestamp"), "patterns": data.get("patterns", [])}

@app.get("/api/mining/clusters")
async def mining_clusters():
    """Node clustering only."""
    data = _read_mining_results()
    return {"timestamp": data.get("timestamp"), "node_clusters": data.get("node_clusters", [])}

@app.get("/api/mining/anomalies")
async def mining_anomalies():
    """Anomaly flags only."""
    data = _read_mining_results()
    return {"timestamp": data.get("timestamp"), "anomalies": data.get("anomalies", [])}

# ---------------------------------------------------------------------------
# TERMINAL — Command execution (Phase 11A)
# Mirrors COMMAND_ALLOWLIST / COMMAND_BLOCKLIST from node_agent.py
# ---------------------------------------------------------------------------
_TERM_ALLOWLIST = [
    "systemctl status",
    "df -h",
    "df -hT",
    "df",
    "free -m",
    "free",
    "uptime",
    "top -bn1",
    "ps aux",
    "ps",
    "ip addr",
    "ip a",
    "ip route",
    "ip link",
    "cat /proc/cpuinfo",
    "cat /proc/meminfo",
    "cat /proc/loadavg",
    "cat /opt/nexus/",
    "ls",
    "pwd",
    "whoami",
    "hostname",
    "uname",
    "date",
    "echo",
    "env",
    "printenv",
    "kubectl get",
    "kubectl describe",
    "kubectl logs",
    "kubectl top",
    "journalctl -u",
    "journalctl --no-pager",
    "ping -c",
    "python3 -c",
    "pip list",
    "pip show",
]

_TERM_BLOCKLIST = [
    "rm ",
    "dd ",
    "mkfs",
    "fdisk",
    "reboot",
    "shutdown",
    "halt",
    "poweroff",
    "chmod 777",
    "> /dev/",
    "curl|bash",
    "wget|bash",
    "; rm",
    "&& rm",
    "sudo su",
    "passwd",
    "useradd",
    "userdel",
    "chown",
    "mount ",
    "umount",
    ">/",
    "2>/dev/",
    "exec(",
    "__import__",
]


def _validate_term_cmd(cmd: str) -> tuple:
    cmd = cmd.strip()
    if not cmd:
        return False, "empty command"
    for blocked in _TERM_BLOCKLIST:
        if blocked in cmd:
            return False, f"blocked pattern: {blocked!r}"
    for prefix in _TERM_ALLOWLIST:
        if cmd.startswith(prefix):
            return True, ""
    return False, "not in allowlist — type 'help' to see permitted commands"


class TerminalExecRequest(BaseModel):
    command: str


@app.post("/api/terminal/exec")
async def terminal_exec(req: TerminalExecRequest):
    cmd = req.command.strip()
    allowed, reason = _validate_term_cmd(cmd)
    if not allowed:
        return {
            "stdout":      "",
            "stderr":      f"Permission denied: {reason}",
            "return_code": 126,
            "allowed":     False,
        }
    try:
        parts = shlex.split(cmd)
        proc  = await asyncio.create_subprocess_exec(
            *parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd="/opt/nexus",
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
        except asyncio.TimeoutError:
            proc.kill()
            return {
                "stdout":      "",
                "stderr":      "Command timed out (15 s limit)",
                "return_code": 124,
                "allowed":     True,
            }
        return {
            "stdout":      stdout.decode(errors="replace"),
            "stderr":      stderr.decode(errors="replace"),
            "return_code": proc.returncode,
            "allowed":     True,
        }
    except Exception as exc:
        return {"stdout": "", "stderr": str(exc), "return_code": 1, "allowed": True}


# ---------------------------------------------------------------------------
# TERMINAL — WebSocket placeholder (Phase 11B — real PTY)
# ---------------------------------------------------------------------------
@app.websocket("/api/terminal/{hostname}")
async def terminal_ws(websocket: WebSocket, hostname: str):
    await websocket.accept()
    await websocket.send_text(json.dumps({
        "type": "error",
        "message": f"Terminal proxy for '{hostname}' not implemented yet (Phase 11A Part 3)",
    }))
    await websocket.close()

# ---------------------------------------------------------------------------
# TRAINING
# ---------------------------------------------------------------------------

@app.post("/api/training/log")
async def training_log(body: dict):
    prompt      = (body.get("prompt") or "").strip()
    outcome     = body.get("outcome", "unknown")
    commit_hash = (body.get("commit_hash") or "").strip()
    notes       = (body.get("notes") or "").strip()
    if not prompt:
        return {"error": "prompt required"}
    entry = {
        "prompt":      prompt,
        "outcome":     outcome,
        "commit_hash": commit_hash,
        "notes":       notes,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
    }
    try:
        TRAINING_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TRAINING_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return {"status": "logged"}
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/training/sessions")
async def training_sessions(limit: int = 50):
    if not TRAINING_LOG_FILE.exists():
        return []
    try:
        entries = []
        with open(TRAINING_LOG_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
        return list(reversed(entries[-limit:]))
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/training/stats")
async def training_stats():
    if not TRAINING_LOG_FILE.exists():
        return {"total_sessions": 0, "success_count": 0, "fail_count": 0,
                "partial_count": 0, "success_rate": 0}
    try:
        total = success = fail = partial = 0
        with open(TRAINING_LOG_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    total += 1
                    o = entry.get("outcome", "")
                    if o == "success":
                        success += 1
                    elif o == "failed":
                        fail += 1
                    elif o == "partial":
                        partial += 1
                except Exception:
                    pass
        return {
            "total_sessions": total,
            "success_count":  success,
            "fail_count":     fail,
            "partial_count":  partial,
            "success_rate":   round(success / total * 100) if total else 0,
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/training/export/pairs")
async def training_export_pairs():
    entries = []
    if TRAINING_LOG_FILE.exists():
        try:
            with open(TRAINING_LOG_FILE, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except Exception:
                            pass
        except Exception:
            pass

    pairs = []
    for entry in entries:
        response_text = entry.get("outcome", "unknown")
        commit = (entry.get("commit_hash") or "").strip()
        if commit and all(c in "0123456789abcdefABCDEF" for c in commit) and len(commit) <= 64:
            try:
                stdout, _, rc = await _run(["git", "show", "--stat", commit], cwd=NEXUS_REPO)
                if rc == 0 and stdout:
                    response_text = stdout.strip()
            except Exception:
                pass
        pairs.append(json.dumps({
            "instruction": entry.get("prompt", ""),
            "response":    response_text,
            "outcome":     entry.get("outcome", "unknown"),
            "notes":       entry.get("notes", ""),
        }))

    content = "\n".join(pairs) + ("\n" if pairs else "")
    return StreamingResponse(
        io.BytesIO(content.encode()),
        media_type="application/x-jsonlines",
        headers={"Content-Disposition": "attachment; filename=training_pairs.jsonl"},
    )


@app.get("/api/training/export/raw")
async def training_export_raw():
    content = ""
    if TRAINING_LOG_FILE.exists():
        try:
            content = TRAINING_LOG_FILE.read_text(encoding="utf-8")
        except Exception:
            pass
    return StreamingResponse(
        io.BytesIO(content.encode()),
        media_type="application/x-jsonlines",
        headers={"Content-Disposition": "attachment; filename=training_log.jsonl"},
    )


# ---------------------------------------------------------------------------
# TEMPORAL SCHEDULER
# ---------------------------------------------------------------------------

def _bin_id_from_hex(hex_str: str) -> bytes:
    """Convert hex string (with or without 0x) to bytes32."""
    s = hex_str.strip()
    if s.startswith(("0x", "0X")):
        s = s[2:]
    return bytes.fromhex(s.zfill(64))


@app.get("/api/temporal/summary")
async def temporal_summary():
    w3, ts = _w3_contract("TemporalScheduler")
    if not w3 or not w3.is_connected():
        return {"error": "blockchain unreachable"}
    if not ts:
        return {"error": "TemporalScheduler not deployed"}
    try:
        total_assignments = ts.functions.totalAssignments().call()
        total_bins_used   = ts.functions.totalBinsUsed().call()
        now = datetime.now(timezone.utc)
        iso_year, iso_week, iso_day = now.isocalendar()
        dow  = iso_day - 1
        hour = now.hour
        bin_id = ts.functions.computeBinId(iso_year, iso_week, dow, hour).call()
        return {
            "total_assignments": total_assignments,
            "total_bins_used":   total_bins_used,
            "current_bin": {
                "year":   iso_year,
                "week":   iso_week,
                "dow":    dow,
                "hour":   hour,
                "bin_id": "0x" + bin_id.hex(),
            },
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/temporal/heatmap")
async def temporal_heatmap(year: int = 0, weeks: int = 4):
    from datetime import timedelta
    w3, ts = _w3_contract("TemporalScheduler")
    if not w3 or not w3.is_connected():
        return {"error": "blockchain unreachable", "data": []}
    if not ts:
        return {"error": "TemporalScheduler not deployed", "data": []}

    weeks = max(1, min(weeks, 52))

    # Build list of (iso_year, iso_week) for the last N weeks ending this week
    now    = datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())  # Monday of current week
    week_list = []
    for i in range(weeks - 1, -1, -1):
        d = monday - timedelta(weeks=i)
        wy, ww, _ = d.isocalendar()
        week_list.append((wy, ww))

    # Compute all bin IDs: N weeks × 7 days × 24 hours
    bin_keys = []  # (dow, hour) for aggregation
    bin_ids  = []  # bytes32 values
    try:
        for wy, ww in week_list:
            for dow in range(7):
                for hour in range(24):
                    bid = ts.functions.computeBinId(wy, ww, dow, hour).call()
                    bin_keys.append((dow, hour))
                    bin_ids.append(bid)
    except Exception as exc:
        return {"error": f"bin ID computation failed: {exc}", "data": []}

    # Batch query all bins at once
    try:
        counts, ects = ts.functions.getBinUtilization(bin_ids).call()
    except Exception as exc:
        return {"error": f"getBinUtilization failed: {exc}", "data": []}

    # Aggregate across weeks into (dow, hour) buckets
    agg: dict = {}
    for (dow, hour), count, ect in zip(bin_keys, counts, ects):
        key = (dow, hour)
        if key not in agg:
            agg[key] = {"task_count": 0, "ect_spent": 0}
        agg[key]["task_count"] += count
        agg[key]["ect_spent"]  += ect

    data = []
    for dow in range(7):
        for hour in range(24):
            v = agg.get((dow, hour), {"task_count": 0, "ect_spent": 0})
            data.append({
                "day":        dow,
                "hour":       hour,
                "task_count": v["task_count"],
                "ect_spent":  v["ect_spent"],
            })

    return {
        "weeks_covered": weeks,
        "week_range":    [f"{wy}W{ww:02d}" for wy, ww in week_list],
        "data":          data,
    }


@app.get("/api/temporal/bin/{bin_id}")
async def temporal_bin(bin_id: str):
    w3, ts = _w3_contract("TemporalScheduler")
    if not w3 or not w3.is_connected():
        return {"error": "blockchain unreachable"}
    if not ts:
        return {"error": "TemporalScheduler not deployed"}
    try:
        bid_bytes = _bin_id_from_hex(bin_id)
    except Exception:
        return {"error": f"invalid bin_id: {bin_id!r}"}
    try:
        year, week, dow, hour, task_count, ect_spent, created_at, exists = \
            ts.functions.getBin(bid_bytes).call()
        if not exists:
            return {"error": "bin not found", "bin_id": bin_id}
        tasks = ts.functions.getBinTasks(bid_bytes).call()
        return {
            "bin_id":         bin_id if bin_id.startswith("0x") else "0x" + bin_id,
            "year":           year,
            "week":           week,
            "day_of_week":    dow,
            "hour":           hour,
            "task_count":     task_count,
            "total_ect_spent":ect_spent,
            "created_at":     created_at,
            "exists":         exists,
            "tasks":          ["0x" + t.hex() for t in tasks],
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/temporal/recent")
async def temporal_recent(limit: int = 20):
    w3, ts = _w3_contract("TemporalScheduler")
    if not w3 or not w3.is_connected():
        return {"error": "blockchain unreachable"}
    if not ts:
        return {"error": "TemporalScheduler not deployed"}
    try:
        total = ts.functions.totalAssignments().call()
        stop  = max(0, total - limit)
        assignments = []
        for i in range(total - 1, stop - 1, -1):
            bid, task_hash, assigned_by, ect_cost, timestamp = \
                ts.functions.getAssignment(i).call()
            year = week = dow = hour = None
            try:
                year, week, dow, hour, _, _, _, _ = ts.functions.getBin(bid).call()
            except Exception:
                pass
            assignments.append({
                "index":       i,
                "bin_id":      "0x" + bid.hex(),
                "task_hash":   "0x" + task_hash.hex(),
                "assigned_by": assigned_by,
                "ect_cost":    ect_cost,
                "timestamp":   timestamp,
                "bin_params":  {"year": year, "week": week, "day_of_week": dow, "hour": hour},
            })
        return {"total_assignments": total, "assignments": assignments}
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Temporal Scoring (TemporalScorer — offline analysis)
# ---------------------------------------------------------------------------

def _get_temporal_scorer():
    try:
        sys.path.insert(0, "/opt/nexus")
        from modules.temporal_scoring import TemporalScorer
        return TemporalScorer()
    except Exception as exc:
        log.warning("TemporalScorer unavailable: %s", exc)
        return None


@app.get("/api/temporal/heatmap/scored")
async def temporal_heatmap_scored(days: int = 30):
    scorer = _get_temporal_scorer()
    if not scorer:
        return {"error": "TemporalScorer module unavailable"}
    try:
        hm = scorer.generate_heatmap_data(days=max(1, min(days, 365)))
        # Convert numpy arrays to nested lists for JSON
        data = []
        for hour in range(24):
            for dow in range(7):
                data.append({
                    "hour": hour,
                    "day": dow,
                    "utilization": round(float(hm["utilization"][hour, dow]), 4),
                    "success_rate": round(float(hm["success_rate"][hour, dow]), 4),
                })
        return {
            "period_days": hm["period_days"],
            "total_entries": hm["total_entries"],
            "data": data,
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/temporal/stats")
async def temporal_stats():
    w3, ts = _w3_contract("TemporalScheduler")
    scorer = _get_temporal_scorer()

    result = {}

    # On-chain stats
    if w3 and w3.is_connected() and ts:
        try:
            result["total_assignments"] = ts.functions.totalAssignments().call()
            result["total_bins_used"] = ts.functions.totalBinsUsed().call()
        except Exception as exc:
            result["chain_error"] = str(exc)
    else:
        result["chain_error"] = "TemporalScheduler not available"

    # Scorer heatmap summary
    if scorer:
        try:
            hm = scorer.generate_heatmap_data(days=30)
            util = hm["utilization"]
            sr = hm["success_rate"]
            # Busiest cell
            max_idx = util.argmax()
            busiest_hour = int(max_idx // 7)
            busiest_dow = int(max_idx % 7)
            dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            result["busiest_bin"] = f"{dow_names[busiest_dow]} {busiest_hour:02d}:00"
            result["avg_success_rate"] = round(float(sr.mean()), 4)
            result["total_log_entries"] = hm["total_entries"]
        except Exception as exc:
            result["scorer_error"] = str(exc)

    return result


@app.get("/api/temporal/current")
async def temporal_current():
    w3, ts = _w3_contract("TemporalScheduler")
    now = datetime.now(timezone.utc)
    iso_year, iso_week, iso_day = now.isocalendar()
    dow = iso_day - 1
    hour = now.hour
    dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    result = {
        "label": f"{iso_year}-W{iso_week:02d}-{dow_names[dow]}-{hour:02d}:00",
        "year": iso_year,
        "week": iso_week,
        "day_of_week": dow,
        "hour": hour,
    }

    if w3 and w3.is_connected() and ts:
        try:
            bin_id = ts.functions.computeBinId(iso_year, iso_week, dow, hour).call()
            result["bin_id"] = "0x" + bin_id.hex()
            year, week, d, h, task_count, ect_spent, created_at, exists = \
                ts.functions.getBin(bin_id).call()
            result["task_count"] = task_count if exists else 0
            result["ect_spent"] = ect_spent if exists else 0
            result["exists"] = exists
            if exists:
                tasks = ts.functions.getBinTasks(bin_id).call()
                result["tasks"] = ["0x" + t.hex() for t in tasks]
            else:
                result["tasks"] = []
        except Exception as exc:
            result["error"] = str(exc)
    else:
        result["error"] = "TemporalScheduler not available"
        result["task_count"] = 0
        result["tasks"] = []

    return result


# ---------------------------------------------------------------------------
# Tournament endpoints
# ---------------------------------------------------------------------------

DEPLOYER_WALLET = '0x817B0842B208B76A7665948F8D1A0592F9b1e958'


def _tournament_contract():
    """Return (w3, contract) for TournamentManager."""
    return _w3_contract("TournamentManager")


@app.get("/api/tournaments")
async def list_tournaments():
    w3, tm = _tournament_contract()
    if not w3 or not w3.is_connected():
        return {"error": "blockchain unreachable", "tournaments": []}
    if not tm:
        return {"error": "TournamentManager not deployed", "tournaments": []}
    try:
        count = tm.functions.tournamentCount().call()
        tournaments = []
        for i in range(count):
            t = tm.functions.tournaments(i).call()
            sub_count = tm.functions.getSubmissionCount(i).call()
            now = int(time.time())
            end_epoch = t[5]
            remaining = max(0, end_epoch - now)
            tournaments.append({
                "id": t[0],
                "name": t[1],
                "description": t[2],
                "prize_pool": t[3],
                "start_epoch": t[4],
                "end_epoch": end_epoch,
                "validation_data_hash": "0x" + t[6].hex(),
                "finalized": t[7],
                "winner": t[8],
                "winner_score": t[9],
                "submission_count": sub_count,
                "time_remaining": remaining,
            })
        return {
            "count": count,
            "total_prize_distributed": tm.functions.totalPrizeDistributed().call(),
            "tournaments": tournaments,
        }
    except Exception as exc:
        return {"error": str(exc), "tournaments": []}


@app.get("/api/tournaments/{tournament_id}/leaderboard")
async def tournament_leaderboard(tournament_id: int):
    w3, tm = _tournament_contract()
    if not w3 or not w3.is_connected():
        return {"error": "blockchain unreachable"}
    if not tm:
        return {"error": "TournamentManager not deployed"}
    try:
        count = tm.functions.tournamentCount().call()
        if tournament_id >= count:
            return {"error": "Invalid tournament ID"}
        contributors, pred_hashes, scores, timestamps = \
            tm.functions.getLeaderboard(tournament_id).call()
        leaderboard = []
        for i in range(len(contributors)):
            leaderboard.append({
                "rank": i + 1,
                "contributor": contributors[i],
                "prediction_hash": "0x" + pred_hashes[i].hex(),
                "score": scores[i],
                "timestamp": timestamps[i],
            })
        return {"tournament_id": tournament_id, "leaderboard": leaderboard}
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/tournaments/causes")
async def get_cause_allocations():
    w3, tm = _tournament_contract()
    if not w3 or not w3.is_connected():
        return {"error": "blockchain unreachable", "allocations": []}
    if not tm:
        return {"error": "TournamentManager not deployed", "allocations": []}
    try:
        contributors, cause_names, percentages = \
            tm.functions.getCauseAllocations().call()
        allocations = []
        for i in range(len(contributors)):
            allocations.append({
                "contributor": contributors[i],
                "cause_name": cause_names[i],
                "percentage_bps": percentages[i],
            })

        # Get RST totals for contribution weight calculation
        rst_total = 0
        user_rst = 0
        w3_tok, tok = _w3_contract("TokenManager")
        if tok:
            try:
                _, _, rst_earned, rst_slashed = tok.functions.getTotals().call()
                rst_total = rst_earned - rst_slashed
                user_rst_raw = tok.functions.rstBalances(
                    Web3.to_checksum_address(DEPLOYER_WALLET)
                ).call()
                user_rst = user_rst_raw
            except Exception:
                pass

        return {
            "allocations": allocations,
            "rst_total": rst_total,
            "user_rst": user_rst,
        }
    except Exception as exc:
        return {"error": str(exc), "allocations": []}


class CauseRequest(BaseModel):
    cause: str
    percentage: int


@app.post("/api/tournaments/causes")
async def set_cause_allocation(req: CauseRequest):
    w3, tm = _tournament_contract()
    if not w3 or not w3.is_connected():
        return {"error": "blockchain unreachable"}
    if not tm:
        return {"error": "TournamentManager not deployed"}
    try:
        percentage = max(0, min(req.percentage, 10000))
        tx_hash = tm.functions.setCauseAllocation(
            req.cause, percentage
        ).transact({
            'from': Web3.to_checksum_address(DEPLOYER_WALLET),
            'gas': 500000,
        })
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
        return {
            "success": True,
            "cause": req.cause,
            "percentage_bps": percentage,
            "tx_hash": tx_hash.hex(),
            "block": receipt['blockNumber'],
        }
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Circuit Breakers
# ---------------------------------------------------------------------------

def _get_circuit_breaker():
    try:
        sys.path.insert(0, "/opt/nexus")
        from modules.circuit_breaker import get_circuit_breaker
        return get_circuit_breaker(log_on_chain=False)
    except Exception as exc:
        log.warning("CircuitBreaker unavailable: %s", exc)
        return None


@app.get("/api/circuit-breakers")
async def circuit_breakers_status():
    cb = _get_circuit_breaker()
    if not cb:
        return {"error": "CircuitBreaker module unavailable", "breakers": {}}
    return {"breakers": cb.get_status()}


class BreakerActionRequest(BaseModel):
    reason: str = ""


@app.post("/api/circuit-breakers/{name}/pause")
async def circuit_breaker_pause(name: str, req: BreakerActionRequest):
    cb = _get_circuit_breaker()
    if not cb:
        return {"error": "CircuitBreaker module unavailable"}
    changed = cb.pause(name, req.reason or "Paused via dashboard", "dashboard")
    return {"success": True, "changed": changed, "breaker": name, "action": "paused"}


@app.post("/api/circuit-breakers/{name}/resume")
async def circuit_breaker_resume(name: str, req: BreakerActionRequest):
    cb = _get_circuit_breaker()
    if not cb:
        return {"error": "CircuitBreaker module unavailable"}
    changed = cb.resume(name, req.reason or "Resumed via dashboard", "dashboard")
    return {"success": True, "changed": changed, "breaker": name, "action": "resumed"}


# ---------------------------------------------------------------------------
# Behavioral Intelligence (proxy to port 8769)
# ---------------------------------------------------------------------------

@app.get("/api/behavioral/summary")
async def behavioral_summary():
    """Proxy to behavioral API for dashboard integration."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://localhost:8769/api/behavioral/stats/summary", timeout=3) as r:
            return json.loads(r.read())
    except:
        return {"consent_active": False, "total_actions": 0, "total_compounds": 0,
                "privacy_budget_pct": 0, "debug_mode": False, "available": False}

@app.get("/api/behavioral/channels")
async def behavioral_channels():
    """Proxy channel stats for dashboard."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://localhost:8769/api/behavioral/stats", timeout=3) as r:
            return json.loads(r.read())
    except:
        return {"channels": {}, "available": False}


# ---------------------------------------------------------------------------
# Local Insight endpoints (always available — not debug-mode dependent)
# ---------------------------------------------------------------------------

@app.get("/api/insight/current")
async def get_current_pattern():
    from modules.local_insight import LocalInsightEngine
    engine = LocalInsightEngine()
    return engine.current_pattern()

@app.get("/api/insight/summary")
async def get_daily_insight_summary():
    from modules.local_insight import LocalInsightEngine
    engine = LocalInsightEngine()
    return engine.daily_summary()

@app.get("/api/insight/typing")
async def get_typing_trend():
    from modules.local_insight import LocalInsightEngine
    engine = LocalInsightEngine()
    return engine.typing_speed_trend()

@app.get("/api/insight/compare")
async def get_now_vs_average():
    from modules.local_insight import LocalInsightEngine
    engine = LocalInsightEngine()
    return engine.now_vs_average()

@app.get("/api/insight/all")
async def get_all_insights():
    from modules.local_insight import LocalInsightEngine
    engine = LocalInsightEngine()
    return engine.get_all_insights()


# ---------------------------------------------------------------------------
# Serve frontend
# ---------------------------------------------------------------------------
DIST_DIR = Path(__file__).parent.parent / "dist"
if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(DIST_DIR / "assets")), name="static-assets")

    @app.get("/manifest.json")
    async def serve_manifest():
        manifest = DIST_DIR / "manifest.json"
        if manifest.exists():
            return FileResponse(str(manifest), media_type="application/manifest+json")
        return {"error": "manifest not found"}

    @app.get("/sw.js")
    async def serve_sw():
        sw = DIST_DIR / "sw.js"
        if sw.exists():
            return FileResponse(str(sw), media_type="application/javascript")
        return {"error": "sw not found"}

    @app.get("/favicon.svg")
    async def serve_favicon():
        fav = DIST_DIR / "favicon.svg"
        if fav.exists():
            return FileResponse(str(fav), media_type="image/svg+xml")
        return {"error": "favicon not found"}

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """Serve the React SPA for any non-API route."""
        index = DIST_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"error": "Frontend not built"}

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("dashboard_api:app", host="0.0.0.0", port=8768, reload=True)
