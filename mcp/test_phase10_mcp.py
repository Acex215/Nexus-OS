#!/usr/bin/env python3
"""Phase 10 MCP server tests.

Covers GatewayClient init, all six tools, and all five resources.
All Gateway WS and HTTP calls are mocked — no running Gateway required.
"""

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure the mcp directory is importable when run from any cwd.
sys.path.insert(0, str(Path(__file__).parent))

import nexus_mcp_server as srv


# ── Test helpers ───────────────────────────────────────────────────────────────

def _make_ctx(gateway=None) -> MagicMock:
    """Return a mock MCP Context whose lifespan holds *gateway*."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"gateway": gateway or AsyncMock()}
    return ctx


def _httpx_mock(json_payload, status_code=200):
    """Return a (mock_acm, mock_client, mock_response) triple for httpx.AsyncClient."""
    mock_response = MagicMock()
    mock_response.json.return_value = json_payload
    mock_response.raise_for_status = MagicMock()
    mock_response.status_code = status_code

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    mock_acm = AsyncMock()
    mock_acm.__aenter__.return_value = mock_client
    mock_acm.__aexit__.return_value = False

    return mock_acm, mock_client, mock_response


# ── Test suite ─────────────────────────────────────────────────────────────────

class TestPhase10MCP(unittest.IsolatedAsyncioTestCase):

    # ── 1. GatewayClient init ──────────────────────────────────────────────────

    def test_gateway_client_init(self):
        """GatewayClient stores url, auth_token, user_id; _ws starts as None."""
        client = srv.GatewayClient("ws://host:9999/ws", "tok-abc", "test-user")

        self.assertEqual(client.url, "ws://host:9999/ws")
        self.assertEqual(client.auth_token, "tok-abc")
        self.assertEqual(client.user_id, "test-user")
        self.assertIsNone(client._ws)
        self.assertIsInstance(client._lock, asyncio.Lock)

        # Module-level env-var defaults must be non-empty and well-formed.
        self.assertIsInstance(srv.GATEWAY_URL, str)
        self.assertTrue(srv.GATEWAY_URL.startswith("ws://"),
                        f"Unexpected GATEWAY_URL: {srv.GATEWAY_URL!r}")
        # Default user_id when omitted
        default_client = srv.GatewayClient("ws://x/ws", "")
        self.assertEqual(default_client.user_id, "mcp-server")

    # ── 2. nexus_submit_task ───────────────────────────────────────────────────

    async def test_submit_task_tool(self):
        """Correct submit_task message format is sent; response is parsed."""
        mock_gw = AsyncMock()
        mock_gw.send_and_receive.return_value = {
            "type": "task_update",
            "payload": {
                "task_id": "task-20260321-abc123",
                "status":  "pending",
                "message": "Task queued.",
            },
        }

        result = await srv.nexus_submit_task(
            description="Write a health check for dev_assistant",
            priority="P1",
            ctx=_make_ctx(mock_gw),
        )

        mock_gw.send_and_receive.assert_called_once()
        sent = mock_gw.send_and_receive.call_args[0][0]
        self.assertEqual(sent["type"], "submit_task")
        self.assertEqual(sent["payload"]["description"], "Write a health check for dev_assistant")
        self.assertEqual(sent["payload"]["priority"], "P1")
        self.assertIn("timestamp", sent)

        parsed = json.loads(result)
        self.assertEqual(parsed["task_id"], "task-20260321-abc123")
        self.assertEqual(parsed["status"], "pending")
        self.assertEqual(parsed["priority"], "P1")

    async def test_submit_task_invalid_priority(self):
        """An unknown priority returns an error without touching the Gateway."""
        result = await srv.nexus_submit_task(
            description="test", priority="P9", ctx=_make_ctx()
        )
        parsed = json.loads(result)
        self.assertIn("error", parsed)
        self.assertIn("P9", parsed["error"])

    async def test_submit_task_gateway_error(self):
        """Gateway error payload is surfaced cleanly."""
        mock_gw = AsyncMock()
        mock_gw.send_and_receive.return_value = {
            "type":    "error",
            "payload": {"error": "queue is paused"},
        }
        result = await srv.nexus_submit_task(
            description="test", priority="P2", ctx=_make_ctx(mock_gw)
        )
        parsed = json.loads(result)
        self.assertIn("error", parsed)
        self.assertIn("queue is paused", parsed["error"])

    # ── 3. nexus_queue_status ──────────────────────────────────────────────────

    async def test_queue_status_tool(self):
        """queue_status message is sent; task list in response is parsed."""
        mock_gw = AsyncMock()
        mock_gw.send_and_receive.return_value = {
            "type": "queue_response",
            "payload": {
                "tasks": [
                    {
                        "id":          "task-001",
                        "priority":    "P1",
                        "status":      "pending",
                        "description": "Fix IPFS bootstrap config",
                        "created_at":  "2026-03-21T10:00:00+00:00",
                        "updated_at":  "2026-03-21T10:00:00+00:00",
                    }
                ]
            },
        }

        result = await srv.nexus_queue_status(ctx=_make_ctx(mock_gw))

        sent = mock_gw.send_and_receive.call_args[0][0]
        self.assertEqual(sent["type"], "queue_status")

        parsed = json.loads(result)
        self.assertEqual(parsed["task_count"], 1)
        self.assertEqual(parsed["tasks"][0]["id"], "task-001")
        self.assertEqual(parsed["tasks"][0]["status"], "pending")

    async def test_queue_status_filter(self):
        """status_filter correctly drops non-matching tasks before return."""
        mock_gw = AsyncMock()
        mock_gw.send_and_receive.return_value = {
            "type": "queue_response",
            "payload": {
                "tasks": [
                    {"id": "t1", "status": "pending",  "priority": "P2",
                     "description": "a", "created_at": "", "updated_at": ""},
                    {"id": "t2", "status": "done",     "priority": "P2",
                     "description": "b", "created_at": "", "updated_at": ""},
                    {"id": "t3", "status": "executing", "priority": "P1",
                     "description": "c", "created_at": "", "updated_at": ""},
                ]
            },
        }

        result = await srv.nexus_queue_status(
            status_filter="pending", ctx=_make_ctx(mock_gw)
        )
        parsed = json.loads(result)
        self.assertEqual(parsed["task_count"], 1)
        self.assertEqual(parsed["tasks"][0]["id"], "t1")

    async def test_queue_status_preformatted_text(self):
        """Gateway may return a pre-formatted text summary; wrap it in JSON."""
        mock_gw = AsyncMock()
        mock_gw.send_and_receive.return_value = {
            "type":    "queue_response",
            "payload": {"text": "Queue: 3 tasks (2 pending, 1 executing)"},
        }

        result = await srv.nexus_queue_status(ctx=_make_ctx(mock_gw))
        parsed = json.loads(result)
        self.assertIn("summary", parsed)
        self.assertIn("3 tasks", parsed["summary"])

    # ── 4. nexus_health ────────────────────────────────────────────────────────

    async def test_health_tool(self):
        """HTTP GET /health is called; JSON response is returned verbatim."""
        health_data = {"status": "ok", "connected_clients": 2, "queue_size": 3}
        mock_acm, mock_client, _ = _httpx_mock(health_data)

        with patch("nexus_mcp_server.httpx.AsyncClient", return_value=mock_acm):
            result = await srv.nexus_health(ctx=_make_ctx())

        mock_client.get.assert_called_once_with(f"{srv.GATEWAY_HTTP_URL}/health")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "ok")
        self.assertEqual(parsed["connected_clients"], 2)
        self.assertEqual(parsed["queue_size"], 3)

    async def test_health_tool_unreachable(self):
        """Connection error returns a descriptive error string."""
        mock_acm = AsyncMock()
        mock_acm.__aenter__.side_effect = Exception("Connection refused")
        mock_acm.__aexit__.return_value = False

        with patch("nexus_mcp_server.httpx.AsyncClient", return_value=mock_acm):
            result = await srv.nexus_health(ctx=_make_ctx())

        parsed = json.loads(result)
        self.assertIn("error", parsed)

    # ── 5. nexus_node_list ─────────────────────────────────────────────────────

    async def test_node_list_tool(self):
        """HTTP GET /nodes is called; node data is structured correctly."""
        nodes_data = [
            {
                "hostname":       "nexus-master",
                "wallet_address": "0x817B0842B208B76A7665948F8D1A0592F9b1e958",
                "capabilities":   ["exec", "storage"],
                "models":         [],
                "resources":      {"cpu_cores": 4, "memory_gb": 8, "storage_gb": 235},
            }
        ]
        mock_acm, mock_client, _ = _httpx_mock(nodes_data)

        with patch("nexus_mcp_server.httpx.AsyncClient", return_value=mock_acm):
            result = await srv.nexus_node_list(ctx=_make_ctx())

        mock_client.get.assert_called_once_with(f"{srv.GATEWAY_HTTP_URL}/nodes")
        parsed = json.loads(result)
        self.assertEqual(parsed["node_count"], 1)
        node = parsed["nodes"][0]
        self.assertEqual(node["hostname"], "nexus-master")
        self.assertIn("exec", node["capabilities"])
        self.assertEqual(node["resources"]["cpu_cores"], 4)
        self.assertEqual(node["resources"]["storage_gb"], 235)

    async def test_node_list_empty(self):
        """Empty /nodes response returns friendly message."""
        mock_acm, _, _ = _httpx_mock([])

        with patch("nexus_mcp_server.httpx.AsyncClient", return_value=mock_acm):
            result = await srv.nexus_node_list(ctx=_make_ctx())

        parsed = json.loads(result)
        self.assertEqual(parsed["nodes"], [])
        self.assertIn("No nodes", parsed["message"])

    async def test_node_list_models_extracted(self):
        """Model names are extracted from the models list."""
        nodes_data = [
            {
                "hostname": "nexus-ai2",
                "wallet_address": "0xABCD",
                "capabilities": ["inference"],
                "models": [{"name": "SmolLM2-1.7B-Q4_K_M"}, {"name": "llama-3"}],
                "resources": {"cpu_cores": 4, "memory_gb": 16, "storage_gb": 128},
            }
        ]
        mock_acm, _, _ = _httpx_mock(nodes_data)

        with patch("nexus_mcp_server.httpx.AsyncClient", return_value=mock_acm):
            result = await srv.nexus_node_list(ctx=_make_ctx())

        parsed = json.loads(result)
        self.assertEqual(parsed["nodes"][0]["models"], ["SmolLM2-1.7B-Q4_K_M", "llama-3"])

    # ── 6. nexus_node_command ──────────────────────────────────────────────────

    async def test_node_command_tool(self):
        """node_command_request sent with correct fields; result forwarded."""
        mock_gw = AsyncMock()
        mock_gw.send_and_receive_two.return_value = (
            {"type": "node_command_result", "payload": {"status": "pending"}},
            {
                "type": "node_command_result",
                "payload": {
                    "status": "ok",
                    "result": {"return_code": 0, "stdout": "Hello nexus-master\n"},
                },
            },
        )

        result = await srv.nexus_node_command(
            target_node="nexus-master",
            command="exec",
            args={"cmd": "echo Hello nexus-master"},
            ctx=_make_ctx(mock_gw),
        )

        mock_gw.send_and_receive_two.assert_called_once()
        call_args = mock_gw.send_and_receive_two.call_args
        sent = call_args[0][0]
        self.assertEqual(sent["type"], "node_command_request")
        self.assertEqual(sent["payload"]["target_node"], "nexus-master")
        self.assertEqual(sent["payload"]["command"], "exec")
        self.assertEqual(sent["payload"]["args"]["cmd"], "echo Hello nexus-master")
        # exec uses REQUEST_TIMEOUT, not NODE_COMMAND_TIMEOUT
        self.assertEqual(call_args.kwargs["timeout"], srv.REQUEST_TIMEOUT)

        parsed = json.loads(result)
        self.assertEqual(parsed["node"], "nexus-master")
        self.assertEqual(parsed["command"], "exec")
        self.assertEqual(parsed["status"], "ok")
        self.assertEqual(parsed["result"]["return_code"], 0)

    async def test_node_command_inference_uses_long_timeout(self):
        """inference command passes NODE_COMMAND_TIMEOUT (120 s) to the client."""
        mock_gw = AsyncMock()
        mock_gw.send_and_receive_two.return_value = (
            {"type": "node_command_result", "payload": {"status": "pending"}},
            {"type": "node_command_result",
             "payload": {"status": "ok", "result": {"text": "4"}}},
        )

        await srv.nexus_node_command(
            target_node="nexus-ai2",
            command="inference",
            args={"prompt": "What is 2+2?"},
            ctx=_make_ctx(mock_gw),
        )

        call_args = mock_gw.send_and_receive_two.call_args
        self.assertEqual(call_args.kwargs["timeout"], srv.NODE_COMMAND_TIMEOUT)
        self.assertEqual(srv.NODE_COMMAND_TIMEOUT, 120)

    async def test_node_command_invalid_command(self):
        """Unknown command returns error before any WS call."""
        mock_gw = AsyncMock()
        result = await srv.nexus_node_command(
            target_node="nexus-master", command="reboot", args={},
            ctx=_make_ctx(mock_gw),
        )
        parsed = json.loads(result)
        self.assertIn("error", parsed)
        self.assertIn("reboot", parsed["error"])
        mock_gw.send_and_receive_two.assert_not_called()

    async def test_node_command_exec_missing_cmd(self):
        """exec without 'cmd' in args returns error before WS call."""
        mock_gw = AsyncMock()
        result = await srv.nexus_node_command(
            target_node="nexus-master", command="exec", args={},
            ctx=_make_ctx(mock_gw),
        )
        parsed = json.loads(result)
        self.assertIn("error", parsed)
        mock_gw.send_and_receive_two.assert_not_called()

    async def test_node_command_ack_error_surfaced(self):
        """If the ack frame is an error (node not found), it is surfaced."""
        mock_gw = AsyncMock()
        mock_gw.send_and_receive_two.return_value = (
            {"type": "error",    "payload": {"error": "node 'bad-host' not connected"}},
            {"type": "node_command_result", "payload": {"status": "ok", "result": {}}},
        )
        result = await srv.nexus_node_command(
            target_node="bad-host", command="health", args={},
            ctx=_make_ctx(mock_gw),
        )
        parsed = json.loads(result)
        self.assertIn("error", parsed)
        self.assertIn("bad-host", parsed["error"])

    # ── 7. nexus_search_knowledge ──────────────────────────────────────────────

    async def test_search_knowledge_tool(self):
        """ChromaDB is queried with correct args; columnar results are unpacked."""
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids":       [["id-001", "id-002"]],
            "documents": [["Updated health check endpoint", "Fixed IPFS peering"]],
            "metadatas": [[{"task_id": "t1", "status": "done"},
                           {"task_id": "t2", "status": "done"}]],
            "distances": [[0.12, 0.35]],
        }

        mock_chroma = MagicMock()
        mock_chroma.get_collection.return_value = mock_collection

        with patch("chromadb.HttpClient", return_value=mock_chroma):
            result = await srv.nexus_search_knowledge(
                query="health check", n_results=2, ctx=_make_ctx()
            )

        mock_chroma.get_collection.assert_called_once_with("task_outcomes")
        mock_collection.query.assert_called_once_with(
            query_texts=["health check"], n_results=2
        )

        parsed = json.loads(result)
        self.assertEqual(parsed["query"], "health check")
        self.assertEqual(parsed["result_count"], 2)
        self.assertEqual(parsed["results"][0]["id"], "id-001")
        self.assertAlmostEqual(parsed["results"][0]["score"], 0.88, places=2)
        self.assertEqual(parsed["results"][1]["id"], "id-002")
        self.assertAlmostEqual(parsed["results"][1]["score"], 0.65, places=2)

    # ── 8. nexus_search_knowledge unavailable ──────────────────────────────────

    async def test_search_knowledge_flag_unavailable(self):
        """If _CHROMADB_AVAILABLE is False, return graceful error without import."""
        with patch.object(srv, "_CHROMADB_AVAILABLE", False):
            result = await srv.nexus_search_knowledge(
                query="anything", n_results=5, ctx=_make_ctx()
            )
        parsed = json.loads(result)
        self.assertIn("error", parsed)
        self.assertIn("unavailable", parsed["error"])

    async def test_search_knowledge_connection_error(self):
        """ChromaDB connection failure returns a graceful error, not an exception."""
        mock_chroma = MagicMock()
        mock_chroma.get_collection.side_effect = ConnectionRefusedError(
            "ChromaDB not running on port 8000"
        )

        with patch("chromadb.HttpClient", return_value=mock_chroma):
            result = await srv.nexus_search_knowledge(
                query="test", n_results=5, ctx=_make_ctx()
            )

        parsed = json.loads(result)
        self.assertIn("error", parsed)
        self.assertIn("unavailable", parsed["error"])

    # ── 9. nexus://workspace/{filename} resource ───────────────────────────────

    async def test_workspace_resource(self):
        """Workspace files are served verbatim; missing file lists available ones."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "AGENTS.md").write_text("# NEXUS Agents\nAgent definitions.")
            (ws / "SOUL.md").write_text("# Soul document")

            with patch.object(srv, "_WORKSPACE_DIR", ws):
                # Existing file — full content returned
                content = await srv.workspace_file("AGENTS.md")
                self.assertEqual(content, "# NEXUS Agents\nAgent definitions.")

                # Non-existent file — error lists what IS available
                missing = await srv.workspace_file("MISSING.md")
                self.assertIn("not found", missing.lower())
                self.assertIn("AGENTS.md", missing)
                self.assertIn("SOUL.md", missing)

    async def test_workspace_resource_rejects_traversal(self):
        """Path traversal in filename is rejected."""
        result = await srv.workspace_file("../agents/.env")
        self.assertIn("Error", result)
        self.assertIn("traversal", result.lower())

    # ── 10. nexus://agents/{filename} resource ─────────────────────────────────

    async def test_agents_resource_serves_py_file(self):
        """Python source files are served verbatim."""
        with tempfile.TemporaryDirectory() as tmp:
            agents_dir = Path(tmp)
            (agents_dir / "my_agent.py").write_text('"""My agent."""\nprint("hello")\n')

            with patch.object(srv, "_AGENTS_DIR", agents_dir):
                content = await srv.agent_source_file("my_agent.py")
                self.assertIn('"""My agent."""', content)
                self.assertIn('print("hello")', content)

    async def test_agents_resource_rejects_traversal(self):
        """Filenames containing '..' are rejected."""
        result = await srv.agent_source_file("../agents/.env")
        self.assertIn("Error", result)
        self.assertIn("traversal", result.lower())

    async def test_agents_resource_rejects_non_py(self):
        """Only .py files are served; other extensions are rejected."""
        for bad in ("gateway_config.yaml", ".env", "task_log.jsonl", "Makefile"):
            with self.subTest(filename=bad):
                result = await srv.agent_source_file(bad)
                self.assertIn("Error", result)
                self.assertIn(".py", result)

    async def test_agents_resource_rejects_absolute_path(self):
        """Filenames starting with '/' are rejected."""
        result = await srv.agent_source_file("/etc/passwd")
        self.assertIn("Error", result)

    async def test_agents_resource_missing_file_lists_available(self):
        """Missing .py file lists available .py files in the agents dir."""
        with tempfile.TemporaryDirectory() as tmp:
            agents_dir = Path(tmp)
            (agents_dir / "foo.py").write_text("")
            (agents_dir / "bar.py").write_text("")

            with patch.object(srv, "_AGENTS_DIR", agents_dir):
                result = await srv.agent_source_file("nonexistent.py")
                self.assertIn("not found", result.lower())
                self.assertIn("foo.py", result)
                self.assertIn("bar.py", result)

    # ── 11. nexus://config/gateway resource ────────────────────────────────────

    async def test_config_resource_strips_secrets(self):
        """auth_token, password, and api_key values are redacted; other fields kept."""
        yaml_content = (
            "gateway:\n"
            "  host: 0.0.0.0\n"
            "  ws_port: 8765\n"
            '  auth_token: "supersecretvalue"\n'
            "  http_port: 8766\n"
            "database:\n"
            '  password: "db-pass-123"\n'
            '  api_key: "should-be-gone"\n'
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            tmp_cfg = Path(f.name)

        try:
            with patch.object(srv, "_GW_CONFIG", tmp_cfg):
                result = await srv.gateway_config()

            # Secrets must be gone
            self.assertNotIn("supersecretvalue", result)
            self.assertNotIn("db-pass-123", result)
            self.assertNotIn("should-be-gone", result)
            # Redaction marker must be present
            self.assertIn("[REDACTED]", result)
            # Non-secret fields must survive
            self.assertIn("0.0.0.0", result)
            self.assertIn("8765", result)
            self.assertIn("8766", result)
        finally:
            tmp_cfg.unlink(missing_ok=True)

    async def test_config_resource_missing_file(self):
        """Missing config file returns a descriptive error string."""
        with patch.object(srv, "_GW_CONFIG", Path("/nonexistent/gateway_config.yaml")):
            result = await srv.gateway_config()
        self.assertIn("Error", result)

    # ── 12. nexus://tasks/history resource ─────────────────────────────────────

    async def test_task_history_resource(self):
        """Returns last 50 of N entries; entries are parsed from JSONL."""
        entries = [
            {
                "id":          f"log-{i:04d}",
                "task_id":     f"task-{i:04d}",
                "description": f"Task number {i}",
                "status":      "done" if i % 2 == 0 else "failed",
                "timestamp":   "2026-03-21T10:00:00+00:00",
            }
            for i in range(60)
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")
            tmp_log = Path(f.name)

        try:
            with patch.object(srv, "_TASK_LOG", tmp_log):
                result = await srv.task_history()

            parsed = json.loads(result)
            # 60 entries written — must return exactly 50 (the most recent)
            self.assertEqual(parsed["entry_count"], 50)
            # First returned = entry index 10 (60 - 50)
            self.assertEqual(parsed["entries"][0]["id"], "log-0010")
            # Last returned = entry index 59
            self.assertEqual(parsed["entries"][-1]["id"], "log-0059")
            self.assertIn("source", parsed)
        finally:
            tmp_log.unlink(missing_ok=True)

    async def test_task_history_fewer_than_50(self):
        """If fewer than 50 entries exist all of them are returned."""
        entries = [{"id": f"log-{i}", "status": "done"} for i in range(5)]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
            tmp_log = Path(f.name)

        try:
            with patch.object(srv, "_TASK_LOG", tmp_log):
                result = await srv.task_history()
            parsed = json.loads(result)
            self.assertEqual(parsed["entry_count"], 5)
        finally:
            tmp_log.unlink(missing_ok=True)

    async def test_task_history_missing_log(self):
        """Missing JSONL file returns empty entries list, not an exception."""
        with patch.object(srv, "_TASK_LOG", Path("/nonexistent/task_log.jsonl")):
            result = await srv.task_history()
        parsed = json.loads(result)
        self.assertIn("entries", parsed)
        self.assertEqual(parsed["entries"], [])


if __name__ == "__main__":
    unittest.main()
