# Using NEXUS MCP Server with Claude Code

The NEXUS MCP server exposes the Gateway's task queue, node management, and
knowledge base as MCP tools and resources, letting Claude Code interact with
your cluster directly from the chat interface.

---

## Setup

Add to your Claude Code MCP config. Use the **project-level** file for this
repo (`.mcp.json` in the project root) or the **user-level** file for
system-wide access (`~/.claude/mcp.json`):

```json
{
  "mcpServers": {
    "nexus": {
      "command": "python3",
      "args": ["/opt/nexus/mcp/nexus_mcp_server.py"],
      "env": {
        "GATEWAY_URL": "ws://localhost:8766/ws",
        "GATEWAY_AUTH_TOKEN": "<your token from /opt/nexus/agents/.env>"
      }
    }
  }
}
```

> **Note on GATEWAY_AUTH_TOKEN:** The Gateway reads the token from the
> `GATEWAY_AUTH_TOKEN` environment variable (set in
> `/opt/nexus/agents/.env`).  If your Gateway runs with an empty token
> (default during development), you can omit the `GATEWAY_AUTH_TOKEN` line
> from the config above.

The server runs in **stdio mode** by default, which is what Claude Code
expects.  No daemon or port is required — Claude Code launches and manages
the process automatically.

### Optional env vars

| Variable | Default | Purpose |
|---|---|---|
| `GATEWAY_URL` | `ws://localhost:8766/ws` | Gateway WebSocket endpoint |
| `GATEWAY_AUTH_TOKEN` | _(empty)_ | Auth token for Gateway handshake |
| `GATEWAY_HTTP_URL` | `http://localhost:8766` | Gateway HTTP endpoint (health/nodes) |
| `CHROMA_HOST` | `localhost` | ChromaDB host for knowledge search |
| `CHROMA_PORT` | `8000` | ChromaDB port |

---

## Available Tools

### `nexus_submit_task`
Submit a new task to the NEXUS agent queue.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `description` | string | required | Natural language task description |
| `priority` | string | `"P2"` | P0 (critical) · P1 (high) · P2 (normal) · P3 (low) |

Returns the assigned task ID and initial status.

```
"Submit a task to add structured logging to blockchain_logger.py, priority P1"
```

---

### `nexus_queue_status`
Show the current state of the agent task queue.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `status_filter` | string | _(none)_ | Filter by: `pending` `analyzing` `planning` `executing` `done` `failed` `blocked_human` `cancelled` |

Returns task IDs, descriptions, priorities, statuses, and timestamps.

```
"Show me all pending tasks in the queue"
"What tasks are currently executing?"
```

---

### `nexus_health`
Check Gateway health over HTTP (fast, no WS round-trip).

No parameters.  Returns `status`, `connected_clients`, and `queue_size`.

```
"Is the NEXUS Gateway healthy?"
```

---

### `nexus_node_list`
List all compute nodes currently connected to the Gateway.

No parameters.  Returns hostname, wallet address, capabilities, available
models, and hardware resources for each node.

```
"Which nodes have inference capability?"
"Show me all connected cluster nodes and their resources"
```

---

### `nexus_node_command`
Send a command to a specific node and return the result.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `target_node` | string | required | Hostname (e.g. `nexus-master`, `AI`, `Storage`, `nexus-ai2`) |
| `command` | string | required | `health` · `exec` · `inference` · `storage` |
| `args` | dict | `{}` | Command arguments (see below) |

**Command args:**
- `health` — no args required
- `exec` — `{"cmd": "<shell command>"}`
- `inference` — `{"prompt": "<text>"}` (uses 120 s timeout)
- `storage` — `{"action": "list|pin|unpin", "cid": "<CID>", "path": "<local path>"}`

```
"Run a health check on nexus-ai2"
"Execute 'df -h' on nexus-storage"
"Ask nexus-ai2 to summarise the last 10 blockchain transactions"
```

---

### `nexus_search_knowledge`
Search the ChromaDB knowledge base for past task outcomes.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `query` | string | required | Natural language search query |
| `n_results` | int | `5` | Number of results (1–20) |

Returns matching documents with relevance scores and metadata.
Returns a graceful error if ChromaDB is unavailable.

```
"Search past tasks for anything related to ChromaDB errors"
"Find previous solutions for IPFS bootstrap problems"
```

---

## Available Resources

Resources let Claude Code read files and data from the cluster directly.
Reference them in chat or Claude Code will fetch them automatically when
context is needed.

### `nexus://workspace/{filename}`
Workspace documents that define agent identity and guidelines.

Available files: `AGENTS.md`, `SOUL.md`, `TOOLS.md`, `IDENTITY.md`, `USER.md`

```
nexus://workspace/AGENTS.md
nexus://workspace/SOUL.md
nexus://workspace/TOOLS.md
```

---

### `nexus://workspace/skills/{skill_name}`
Skill definition documents (`SKILL.md`) that guide agent behaviour.

Available skills: `code-review`, `deploy`, `documentation`, `security-audit`

```
nexus://workspace/skills/code-review
nexus://workspace/skills/security-audit
```

---

### `nexus://agents/{filename}`
Python source files from `/opt/nexus/agents/`.
Only `.py` files are served (no `.env`, `.yaml`, secrets).

```
nexus://agents/dev_assistant.py
nexus://agents/task_queue.py
nexus://agents/gateway_protocol.py
```

---

### `nexus://tasks/history`
The last 50 entries from the task audit log (`task_log.jsonl`).
Each entry includes task ID, description, status (done/failed), commit hash,
blockchain TX, and timestamps.

```
nexus://tasks/history
```

---

### `nexus://config/gateway`
The Gateway configuration file (`gateway_config.yaml`).
Auth tokens and secrets are automatically redacted before returning.

```
nexus://config/gateway
```

---

## Example Usage in Claude Code

```
# Task management
"Submit a task to add logging to blockchain_logger.py"
"Submit a P0 task: the IPFS bootstrap is broken on nexus-storage"
"Show me the current task queue"
"Are there any blocked_human tasks waiting for approval?"

# Node operations
"Which nodes have inference capability?"
"Run a health check on all nodes"
"Execute 'free -h' on nexus-master to check memory"
"Ask nexus-ai2: what are the key risks in this smart contract?"

# Knowledge and history
"Search past tasks for ChromaDB issues"
"Show me the task history — what did the agent do yesterday?"
"Find previous solutions for Geth clique validator problems"

# Reading cluster context
"Read nexus://workspace/AGENTS.md to understand the agent hierarchy"
"Show me the gateway config"
"Read the dev_assistant source so I can understand how tasks are executed"
```

---

## Running in HTTP mode (optional, for remote clients)

```bash
python3 /opt/nexus/mcp/nexus_mcp_server.py --http
# Starts streamable-HTTP server on port 8767
```

For remote MCP clients, use `http://localhost:8767` as the endpoint.
The stdio mode (default) is preferred for Claude Code local use.
