#!/usr/bin/env python3
"""NEXUS MCP Server — exposes Gateway capabilities as MCP tools.

Run modes:
  stdio (default, for Claude Code):  python3 nexus_mcp_server.py
  HTTP (for remote clients):         python3 nexus_mcp_server.py --http
"""

import asyncio
import json
import logging
import os
import re
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

import httpx
import websockets
from mcp.server.fastmcp import FastMCP, Context
from mcp.types import ToolAnnotations
from pydantic import Field

try:
    import chromadb as _chromadb
    _CHROMADB_AVAILABLE = True
except ImportError:
    _CHROMADB_AVAILABLE = False

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("nexus_mcp")

# ── Env / config ──────────────────────────────────────────────────────────────

def _load_env_file(path: str) -> None:
    """Load key=value pairs from a .env file into os.environ (no-override)."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except FileNotFoundError:
        pass

_load_env_file("/opt/nexus/agents/.env")

GATEWAY_URL        = os.environ.get("GATEWAY_URL", "ws://localhost:8766/ws")
GATEWAY_AUTH_TOKEN = os.environ.get("GATEWAY_AUTH_TOKEN", "")

# ── Wire-protocol helpers ─────────────────────────────────────────────────────

def _make_message(
    msg_type: str,
    payload: dict | None = None,
    request_id: str | None = None,
) -> dict:
    msg: dict[str, Any] = {
        "type": msg_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if payload is not None:
        msg["payload"] = payload
    if request_id is not None:
        msg["request_id"] = request_id
    return msg

# ── Gateway client ────────────────────────────────────────────────────────────

CONNECT_TIMEOUT      = 10   # seconds — initial WS open + handshake
REQUEST_TIMEOUT      = 30   # seconds — per send_and_receive call
NODE_COMMAND_TIMEOUT = 120  # seconds — node commands (inference can be slow)


class GatewayClient:
    """Async WebSocket client for the NEXUS Gateway.

    Usage
    -----
    client = GatewayClient(url, token)
    await client.connect()

    resp = await client.send_and_receive(msg)          # single-response ops
    ack, result = await client.send_and_receive_two(msg)  # node commands

    await client.close()
    """

    def __init__(
        self,
        url: str,
        auth_token: str,
        user_id: str = "mcp-server",
    ) -> None:
        self.url = url
        self.auth_token = auth_token
        self.user_id = user_id
        self._ws: websockets.WebSocketClientProtocol | None = None
        # Serialise all WS traffic; prevents interleaved sends/recvs when
        # multiple MCP tools are invoked concurrently.
        self._lock = asyncio.Lock()

    # ── Connection management ─────────────────────────────────────────────────

    async def connect(self) -> None:
        """Open WS connection and perform Gateway handshake."""
        log.info("Connecting to Gateway at %s", self.url)
        self._ws = await asyncio.wait_for(
            websockets.connect(self.url),
            timeout=CONNECT_TIMEOUT,
        )
        auth_msg = _make_message(
            "connect",
            {
                "auth_token": self.auth_token,
                "user_id": self.user_id,
                "channel": "mcp",
            },
            "mcp-connect-1",
        )
        await self._ws.send(json.dumps(auth_msg))
        resp = json.loads(
            await asyncio.wait_for(self._ws.recv(), timeout=CONNECT_TIMEOUT)
        )
        if resp.get("type") == "error":
            err = resp.get("payload", {}).get("error", repr(resp))
            raise RuntimeError(f"Gateway auth rejected: {err}")
        log.info("Gateway handshake OK (type=%s)", resp.get("type"))

    async def _reconnect(self) -> None:
        """Close the stale socket and reconnect."""
        log.warning("Gateway connection lost — reconnecting")
        try:
            if self._ws:
                await self._ws.close()
        except Exception:
            pass
        self._ws = None
        await self.connect()

    async def close(self) -> None:
        """Cleanly close the WS connection."""
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        log.info("Gateway connection closed")

    # ── Message exchange ──────────────────────────────────────────────────────

    async def send_and_receive(self, message: dict) -> dict:
        """Send *message* and return the single Gateway response.

        Automatically reconnects once if the connection was dropped.
        Raises asyncio.TimeoutError after REQUEST_TIMEOUT seconds.
        """
        async with self._lock:
            return await asyncio.wait_for(
                self._do_send_recv(message),
                timeout=REQUEST_TIMEOUT,
            )

    async def send_and_receive_two(
        self,
        message: dict,
        timeout: float = REQUEST_TIMEOUT,
    ) -> tuple[dict, dict]:
        """Send *message* and return two Gateway responses.

        Used for node commands where the Gateway emits an ack first and then
        the actual node_command_result.  Both receives are held under the same
        lock so that concurrent tool calls cannot interleave their frames.
        Pass a longer *timeout* for slow operations (e.g. inference).
        """
        async with self._lock:
            return await asyncio.wait_for(
                self._do_send_recv_two(message),
                timeout=timeout,
            )

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _do_send_recv(self, message: dict) -> dict:
        try:
            await self._ws.send(json.dumps(message))
            return json.loads(await self._ws.recv())
        except (websockets.ConnectionClosed, AttributeError):
            await self._reconnect()
            await self._ws.send(json.dumps(message))
            return json.loads(await self._ws.recv())

    async def _do_send_recv_two(self, message: dict) -> tuple[dict, dict]:
        try:
            await self._ws.send(json.dumps(message))
            ack    = json.loads(await self._ws.recv())
            result = json.loads(await self._ws.recv())
            return ack, result
        except (websockets.ConnectionClosed, AttributeError):
            await self._reconnect()
            await self._ws.send(json.dumps(message))
            ack    = json.loads(await self._ws.recv())
            result = json.loads(await self._ws.recv())
            return ack, result

# ── FastMCP lifespan ──────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(server):
    """Create GatewayClient on startup; close it on shutdown.

    The client is available to tools via:
        ctx.request_context.lifespan_context["gateway"]
    """
    client = GatewayClient(GATEWAY_URL, GATEWAY_AUTH_TOKEN)
    try:
        await client.connect()
    except Exception as exc:
        # Start anyway — tools will surface connection errors at call time.
        log.error("Could not connect to Gateway on startup: %s", exc)

    try:
        yield {"gateway": client}
    finally:
        await client.close()

# ── FastMCP server ────────────────────────────────────────────────────────────

mcp = FastMCP("nexus_mcp", lifespan=lifespan)

# ── Tool helpers ─────────────────────────────────────────────────────────────

GATEWAY_HTTP_URL = os.environ.get("GATEWAY_HTTP_URL", "http://localhost:8766")
CHROMA_HOST      = os.environ.get("CHROMA_HOST", "localhost")
CHROMA_PORT      = int(os.environ.get("CHROMA_PORT", "8000"))


def _gw(ctx: Context) -> GatewayClient:
    """Extract the GatewayClient from the lifespan context."""
    return ctx.request_context.lifespan_context["gateway"]


def _err_resp(msg: str) -> str:
    return json.dumps({"error": msg}, indent=2)


# ── Tool 1: submit task ───────────────────────────────────────────────────────

@mcp.tool(annotations=ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
))
async def nexus_submit_task(
    description: Annotated[str, Field(
        description="Natural language description of the task for the NEXUS agent to execute.",
    )],
    priority: Annotated[str, Field(
        description="Task priority: P0 (critical / immediate), P1 (high), P2 (normal, default), P3 (low / background).",
    )] = "P2",
    ctx: Context = None,
) -> str:
    """Submit a new task to the NEXUS agent queue via the Gateway.

    The task is persisted in the YAML queue and picked up by the next available
    agent cycle.  Returns the assigned task ID and initial status so the caller
    can track progress with nexus_queue_status.

    Priority guide:
      P0 — critical, process immediately (use sparingly)
      P1 — high priority, next available slot
      P2 — normal (default)
      P3 — low / background, processed when queue is quiet
    """
    if priority not in ("P0", "P1", "P2", "P3"):
        return _err_resp(f"Invalid priority '{priority}'. Must be P0, P1, P2, or P3.")

    msg = _make_message(
        "submit_task",
        {"description": description, "priority": priority},
        "mcp-submit-1",
    )
    try:
        resp = await _gw(ctx).send_and_receive(msg)
    except Exception as exc:
        return _err_resp(f"Gateway error: {exc}")

    if resp.get("type") == "error":
        return _err_resp(resp.get("payload", {}).get("error", "unknown gateway error"))

    payload = resp.get("payload", {})
    return json.dumps({
        "task_id":  payload.get("task_id") or payload.get("id"),
        "status":   payload.get("status", "queued"),
        "priority": priority,
        "message":  payload.get("text") or payload.get("message", "Task submitted to queue."),
    }, indent=2)


# ── Tool 2: queue status ──────────────────────────────────────────────────────

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def nexus_queue_status(
    status_filter: Annotated[str | None, Field(
        description=(
            "Optional status filter. One of: pending, analyzing, planning, executing, "
            "done, failed, blocked_human, cancelled. Omit to see all tasks."
        ),
    )] = None,
    ctx: Context = None,
) -> str:
    """Return the current state of the NEXUS agent task queue.

    Queries the Gateway for all queued tasks and returns a structured summary
    including task IDs, descriptions, priorities, statuses, and timestamps.
    Use status_filter to narrow results (e.g. 'pending' to see what's waiting,
    'executing' to see what's actively running).
    """
    msg = _make_message("queue_status", {}, "mcp-queue-1")
    try:
        resp = await _gw(ctx).send_and_receive(msg)
    except Exception as exc:
        return _err_resp(f"Gateway error: {exc}")

    if resp.get("type") == "error":
        return _err_resp(resp.get("payload", {}).get("error", "unknown gateway error"))

    payload = resp.get("payload", {})

    # Gateway may return a pre-formatted text summary or a raw task list.
    if "text" in payload and isinstance(payload["text"], str):
        # Pre-formatted — wrap in JSON for consistent return type.
        return json.dumps({"summary": payload["text"]}, indent=2)

    tasks = payload.get("tasks", [])
    if not tasks and "queue" in payload:
        tasks = payload["queue"]

    if status_filter:
        tasks = [t for t in tasks if t.get("status") == status_filter]

    if not tasks:
        label = f" with status '{status_filter}'" if status_filter else ""
        return json.dumps({"tasks": [], "message": f"No tasks{label} in queue."}, indent=2)

    formatted = []
    for t in tasks:
        formatted.append({
            "id":          t.get("id"),
            "priority":    t.get("priority", "P2"),
            "status":      t.get("status", "unknown"),
            "description": t.get("description", ""),
            "created_at":  t.get("created_at", ""),
            "updated_at":  t.get("updated_at", ""),
        })

    return json.dumps({"task_count": len(formatted), "tasks": formatted}, indent=2)


# ── Tool 3: gateway health ────────────────────────────────────────────────────

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def nexus_health(ctx: Context = None) -> str:
    """Return the NEXUS Gateway health status.

    Issues an HTTP GET to the Gateway's /health endpoint (faster and more
    reliable than a WS round-trip for health checks).  Reports connected
    clients, queue depth, and overall status.
    """
    url = f"{GATEWAY_HTTP_URL}/health"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)
    except httpx.HTTPStatusError as exc:
        return _err_resp(f"Gateway returned HTTP {exc.response.status_code}")
    except Exception as exc:
        return _err_resp(f"Could not reach Gateway at {url}: {exc}")


# ── Tool 4: node list ─────────────────────────────────────────────────────────

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def nexus_node_list(ctx: Context = None) -> str:
    """List all NEXUS compute nodes currently connected to the Gateway.

    Returns each node's hostname, wallet address, capabilities (e.g. inference,
    storage, exec), available models, and hardware resources (CPU cores, memory,
    storage).  An empty list means no nodes have registered — check that the
    node agent service is running on each host.
    """
    url = f"{GATEWAY_HTTP_URL}/nodes"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            nodes = r.json()
    except httpx.HTTPStatusError as exc:
        return _err_resp(f"Gateway returned HTTP {exc.response.status_code}")
    except Exception as exc:
        return _err_resp(f"Could not reach Gateway at {url}: {exc}")

    if not nodes:
        return json.dumps({"nodes": [], "message": "No nodes currently connected."}, indent=2)

    formatted = []
    for n in nodes:
        res = n.get("resources", {})
        formatted.append({
            "hostname":       n.get("hostname"),
            "wallet_address": n.get("wallet_address"),
            "capabilities":   n.get("capabilities", []),
            "models":         [m.get("name") for m in n.get("models", [])],
            "resources": {
                "cpu_cores":  res.get("cpu_cores"),
                "memory_gb":  res.get("memory_gb"),
                "storage_gb": res.get("storage_gb"),
            },
        })

    return json.dumps({"node_count": len(formatted), "nodes": formatted}, indent=2)


# ── Tool 5: node command ──────────────────────────────────────────────────────

@mcp.tool(annotations=ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
))
async def nexus_node_command(
    target_node: Annotated[str, Field(
        description="Hostname of the target node as reported by nexus_node_list (e.g. nexus-master, AI, Storage, nexus-ai2).",
    )],
    command: Annotated[str, Field(
        description="Command to run on the node. One of: health, exec, inference, storage.",
    )],
    args: Annotated[dict | None, Field(
        description=(
            "Command arguments dict. "
            "health: {} or omit. "
            "exec: {\"cmd\": \"<shell command>\"}. "
            "inference: {\"prompt\": \"<text>\"}. "
            "storage: {\"action\": \"list|pin|unpin\", \"cid\": \"<CID>\", \"path\": \"<local path>\"}."
        ),
    )] = None,
    ctx: Context = None,
) -> str:
    """Send a command to a specific NEXUS node via the Gateway and return the result.

    The Gateway routes the command to the target node and relays the response.
    Supported commands:

      health    — node resource snapshot (CPU, memory, disk, services)
      exec      — run a shell command on the node (args: {cmd: "..."})
      inference — run a local LLM prompt on nexus-ai2 (args: {prompt: "..."})
      storage   — IPFS operations: list pins, pin/unpin a CID (args: {action, cid?, path?})

    Note: inference commands may take up to 120 seconds on large prompts.
    """
    valid_commands = ("health", "exec", "inference", "storage")
    if command not in valid_commands:
        return _err_resp(
            f"Unknown command '{command}'. Must be one of: {', '.join(valid_commands)}."
        )

    node_args: dict = args or {}

    # Basic arg validation — surface obvious mistakes early.
    if command == "exec" and not node_args.get("cmd"):
        return _err_resp("exec command requires args: {\"cmd\": \"<shell command>\"}")
    if command == "inference" and not node_args.get("prompt"):
        return _err_resp("inference command requires args: {\"prompt\": \"<text>\"}")
    if command == "storage" and not node_args.get("action"):
        return _err_resp("storage command requires args: {\"action\": \"list|pin|unpin\", ...}")

    msg = _make_message(
        "node_command_request",
        {
            "target_node": target_node,
            "command":     command,
            "args":        node_args,
        },
        "mcp-node-1",
    )

    # Inference can be slow; use the extended timeout.
    timeout = NODE_COMMAND_TIMEOUT if command == "inference" else REQUEST_TIMEOUT

    try:
        ack, result_msg = await _gw(ctx).send_and_receive_two(msg, timeout=timeout)
    except asyncio.TimeoutError:
        return _err_resp(
            f"Timed out waiting for node '{target_node}' to respond "
            f"(command={command}, timeout={timeout}s)."
        )
    except Exception as exc:
        return _err_resp(f"Gateway error: {exc}")

    # Check ack for immediate errors (e.g. node not found).
    ack_payload = ack.get("payload", {})
    if ack.get("type") == "error" or ack_payload.get("status") == "error":
        err = (
            ack_payload.get("error")
            or ack_payload.get("result", {}).get("message")
            or "node command rejected"
        )
        return _err_resp(err)

    # Parse the node_command_result frame.
    res_payload = result_msg.get("payload", {})
    status      = res_payload.get("status", "")
    result      = res_payload.get("result", {})

    if status == "error":
        return _err_resp(result.get("message", "node returned an error"))

    return json.dumps({
        "node":    target_node,
        "command": command,
        "status":  status,
        "result":  result,
    }, indent=2)


# ── Tool 6: search knowledge ──────────────────────────────────────────────────

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def nexus_search_knowledge(
    query: Annotated[str, Field(
        description="Natural language query to search past task outcomes, agent decisions, and accumulated knowledge.",
    )],
    n_results: Annotated[int, Field(
        description="Number of results to return (1–20).",
        ge=1,
        le=20,
    )] = 5,
    ctx: Context = None,
) -> str:
    """Search the NEXUS knowledge base for past task outcomes and agent decisions.

    Queries the ChromaDB vector store's 'task_outcomes' collection using semantic
    similarity.  Useful for:
      - Finding how similar tasks were solved before
      - Retrieving relevant context before submitting a new task
      - Auditing past agent decisions for a given topic

    Returns the top-N most relevant documents with their metadata and distances.
    Returns an error if ChromaDB is unavailable (non-fatal — submit tasks normally).
    """
    if not _CHROMADB_AVAILABLE:
        return _err_resp("knowledge search unavailable: chromadb package not installed")

    import chromadb  # noqa: PLC0415 — guarded by _CHROMADB_AVAILABLE

    def _sync_query() -> dict:
        client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        try:
            collection = client.get_collection("task_outcomes")
        except Exception as exc:
            raise RuntimeError(f"Collection 'task_outcomes' not found: {exc}") from exc
        return collection.query(query_texts=[query], n_results=n_results)

    try:
        raw = await asyncio.get_event_loop().run_in_executor(None, _sync_query)
    except Exception as exc:
        return _err_resp(f"knowledge search unavailable: {exc}")

    # Unpack ChromaDB's columnar result format into a list of records.
    ids        = (raw.get("ids")        or [[]])[0]
    documents  = (raw.get("documents")  or [[]])[0]
    metadatas  = (raw.get("metadatas")  or [[]])[0]
    distances  = (raw.get("distances")  or [[]])[0]

    if not ids:
        return json.dumps({"results": [], "message": "No matching knowledge found."}, indent=2)

    results = []
    for doc_id, doc, meta, dist in zip(ids, documents, metadatas, distances):
        results.append({
            "id":       doc_id,
            "score":    round(1.0 - dist, 4) if dist is not None else None,
            "document": doc,
            "metadata": meta or {},
        })

    return json.dumps({"query": query, "result_count": len(results), "results": results}, indent=2)

# ── Resource helpers ─────────────────────────────────────────────────────────

_WORKSPACE_DIR = Path("/opt/nexus/workspace")
_AGENTS_DIR    = Path("/opt/nexus/agents")
_TASK_LOG      = Path("/opt/nexus/agents/logs/task_log.jsonl")
_GW_CONFIG     = Path("/opt/nexus/agents/gateway_config.yaml")

# Regex that matches common secret-adjacent YAML keys; replaces their values.
_SECRET_RE = re.compile(
    r'(?m)^(\s*(?:auth_token|token|password|secret|api_key|private_key)\s*:\s*).*$'
)


def _safe_name(name: str) -> bool:
    """Return True only if *name* is a plain filename with no path traversal."""
    return bool(name) and ".." not in name and not name.startswith("/") and "/" not in name


def _read_file(path: Path) -> str | None:
    """Return file contents as a string, or None if the file does not exist."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _redact_secrets(text: str) -> str:
    """Replace values of secret-adjacent YAML keys with [REDACTED]."""
    return _SECRET_RE.sub(r'\1[REDACTED]', text)


# ── Resource 1: workspace files ───────────────────────────────────────────────

@mcp.resource(
    "nexus://workspace/{filename}",
    description=(
        "Read a workspace document from /opt/nexus/workspace/. "
        "Available files include AGENTS.md, SOUL.md, TOOLS.md, IDENTITY.md, USER.md. "
        "Returns the raw Markdown content."
    ),
)
async def workspace_file(filename: str) -> str:
    """Serve a top-level workspace document (Markdown).

    These files define agent identity, tooling, and operating guidelines for
    the NEXUS system.  Typical files: AGENTS.md, SOUL.md, TOOLS.md, IDENTITY.md,
    USER.md.  Only files directly inside /opt/nexus/workspace/ are served —
    subdirectory paths are rejected.

    URI example: nexus://workspace/AGENTS.md
    """
    if not _safe_name(filename):
        return f"Error: invalid filename '{filename}' — path traversal not permitted."

    content = _read_file(_WORKSPACE_DIR / filename)
    if content is None:
        available = sorted(
            p.name for p in _WORKSPACE_DIR.iterdir()
            if p.is_file()
        )
        return (
            f"File not found: {filename}\n"
            f"Available workspace files: {', '.join(available) or '(none)'}"
        )
    return content


# ── Resource 2: workspace skill files ────────────────────────────────────────

@mcp.resource(
    "nexus://workspace/skills/{skill_name}",
    description=(
        "Read a skill definition (SKILL.md) from /opt/nexus/workspace/skills/. "
        "Available skills: code-review, deploy, documentation, security-audit. "
        "Returns the raw Markdown content of the skill's SKILL.md file."
    ),
)
async def workspace_skill(skill_name: str) -> str:
    """Serve a NEXUS agent skill definition document.

    Each skill lives in its own subdirectory under /opt/nexus/workspace/skills/
    and contains a SKILL.md that describes how the agent should approach that
    type of task.

    URI example: nexus://workspace/skills/code-review
    """
    if not _safe_name(skill_name):
        return f"Error: invalid skill name '{skill_name}' — path traversal not permitted."

    skill_dir = _WORKSPACE_DIR / "skills" / skill_name
    content = _read_file(skill_dir / "SKILL.md")
    if content is None:
        try:
            available = sorted(p.name for p in (_WORKSPACE_DIR / "skills").iterdir() if p.is_dir())
        except FileNotFoundError:
            available = []
        return (
            f"Skill not found: {skill_name}\n"
            f"Available skills: {', '.join(available) or '(none)'}"
        )
    return content


# ── Resource 3: agent source files ───────────────────────────────────────────

@mcp.resource(
    "nexus://agents/{filename}",
    description=(
        "Read a Python source file from /opt/nexus/agents/. "
        "Only .py files are served. "
        "URI example: nexus://agents/dev_assistant.py"
    ),
)
async def agent_source_file(filename: str) -> str:
    """Serve a NEXUS agent Python source file.

    Exposes agent implementation files for inspection and debugging.
    Security constraints enforced:
      - Only .py files are served (no .env, .yaml, .json, etc.)
      - Filenames with '..' or leading '/' are rejected
      - Only files directly inside /opt/nexus/agents/ are served

    URI example: nexus://agents/dev_assistant.py
    """
    # Reject traversal attempts and non-.py files.
    if not _safe_name(filename):
        return f"Error: invalid filename '{filename}' — path traversal not permitted."
    if not filename.endswith(".py"):
        return (
            f"Error: only .py files may be served via this resource "
            f"(requested: '{filename}')."
        )

    content = _read_file(_AGENTS_DIR / filename)
    if content is None:
        available = sorted(p.name for p in _AGENTS_DIR.iterdir() if p.suffix == ".py")
        return (
            f"File not found: {filename}\n"
            f"Available agent source files: {', '.join(available) or '(none)'}"
        )
    return content


# ── Resource 4: task history ──────────────────────────────────────────────────

@mcp.resource(
    "nexus://tasks/history",
    description=(
        "Read the last 50 task log entries from the NEXUS task audit log "
        "(/opt/nexus/agents/logs/task_log.jsonl). "
        "Returns a JSON array of task outcome records."
    ),
)
async def task_history() -> str:
    """Return the most recent task execution history from the audit log.

    Reads the JSONL task log and returns the last 50 entries as a JSON array.
    Each entry includes task ID, description, priority, status (done/failed),
    affected files, commit hash, blockchain TX, and timestamps.

    Useful for:
      - Auditing what the agent has done recently
      - Debugging failed tasks (check the 'error' field)
      - Correlating on-chain transactions with task outcomes

    Returns an empty array if the log does not exist yet.
    """
    if not _TASK_LOG.exists():
        return json.dumps({"entries": [], "message": "Task log does not exist yet."}, indent=2)

    try:
        raw_lines = _TASK_LOG.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return json.dumps({"error": f"Could not read task log: {exc}"}, indent=2)

    # Take the last 50 non-empty lines.
    recent = [l for l in raw_lines if l.strip()][-50:]

    entries = []
    for line in recent:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            entries.append({"raw": line, "parse_error": True})

    return json.dumps(
        {"entry_count": len(entries), "source": str(_TASK_LOG), "entries": entries},
        indent=2,
    )


# ── Resource 5: gateway config ────────────────────────────────────────────────

@mcp.resource(
    "nexus://config/gateway",
    description=(
        "Read the NEXUS Gateway configuration (gateway_config.yaml). "
        "Auth tokens and secrets are redacted before returning. "
        "Shows ports, session settings, enabled channels, and log paths."
    ),
)
async def gateway_config() -> str:
    """Return the Gateway configuration with secrets redacted.

    Reads /opt/nexus/agents/gateway_config.yaml and strips any values whose
    key matches common secret patterns (auth_token, token, password, secret,
    api_key, private_key) before returning the content.

    Safe to call — no credentials are ever exposed.
    """
    content = _read_file(_GW_CONFIG)
    if content is None:
        return f"Error: gateway config not found at {_GW_CONFIG}"
    return _redact_secrets(content)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="NEXUS MCP Server — exposes NEXUS Gateway as MCP tools",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Run as streamable-HTTP server on port 8767 (default: stdio for Claude Code)",
    )
    args = parser.parse_args()

    if args.http:
        mcp.run(transport="streamable-http", port=8767)
    else:
        mcp.run()  # stdio — default for Claude Code
