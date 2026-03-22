#!/usr/bin/env python3
"""NEXUS Gateway Daemon — WebSocket + HTTP server for multi-channel agent access.

Provides a unified entry point for Discord adapters, CLI clients, and future
web/mobile channels. Runs alongside dev_assistant.py during migration.

Usage:
    python3 nexus_gateway.py
"""

import asyncio
import json
import logging
import os
import signal
import pathlib
import time
import uuid

import yaml

try:
    import websockets
    import websockets.server
except ImportError:
    raise SystemExit(
        "ERROR: 'websockets' package not installed. Run: pip3 install websockets"
    )

try:
    import aiohttp.web
except ImportError:
    raise SystemExit(
        "ERROR: 'aiohttp' package not installed. Run: pip3 install aiohttp"
    )

from gateway_protocol import (
    MSG_CONNECTED, MSG_COMMAND_RESPONSE, MSG_QUEUE_RESPONSE,
    MSG_NODE_REGISTER, MSG_NODE_HEARTBEAT, MSG_NODE_REGISTERED, MSG_NODE_LIST,
    MSG_NODE_COMMAND, MSG_NODE_RESPONSE,
    MSG_NODE_COMMAND_REQUEST, MSG_NODE_COMMAND_RESULT,
    make_message, make_error, make_event,
)
from session_manager import SessionManager
from task_queue import TaskQueue
from queue_commands import handle_queue_command
from health_monitor import HealthMonitor
from blockchain_logger import get_blockchain_logger
from llm_router_v2 import LLMRouter
from token_hooks import cost_check, record_reputation

log = logging.getLogger("nexus_gateway")


def _resolve_env_vars(value: str) -> str:
    """Expand ${VAR} placeholders from environment."""
    import re
    def replacer(m):
        return os.environ.get(m.group(1), "")
    return re.sub(r"\$\{(\w+)\}", replacer, value) if isinstance(value, str) else value


class NexusGateway:
    def __init__(self, config_path: str = "/opt/nexus/agents/gateway_config.yaml"):
        # Load config
        cfg_path = pathlib.Path(config_path)
        if not cfg_path.exists():
            raise FileNotFoundError(f"Gateway config not found: {config_path}")
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)

        gw = cfg["gateway"]
        self.host = gw["host"]
        self.ws_port = int(gw["ws_port"])
        self.http_port = int(gw["http_port"])
        self.auth_token = _resolve_env_vars(gw.get("auth_token", ""))

        sessions_cfg = cfg.get("sessions", {})
        store_path = sessions_cfg.get("store_path", "/opt/nexus/agents/sessions/")

        log_cfg = cfg.get("logging", {})
        log_level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
        log_file = log_cfg.get("file")

        logging.basicConfig(
            level=log_level,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
            handlers=[
                logging.StreamHandler(),
                *([] if not log_file else [logging.FileHandler(log_file)]),
            ],
        )

        # Core components
        self.sessions = SessionManager(store_path)
        self.sessions.load_all()
        self.queue = TaskQueue("/opt/nexus/agents/task_queue.yaml")
        self.router = LLMRouter()
        self.blockchain = get_blockchain_logger()

        # Connected clients: websocket → {user_id, channel, session_id}
        self._clients: dict = {}
        # Connected nodes: wallet_address → {ws, hostname, capabilities, models, resources, last_heartbeat}
        self.nodes: dict = {}
        # In-flight node commands: request_id → {requester_ws, timestamp, hostname, command}
        self._pending_requests: dict = {}
        self._running = False

        log.info("NexusGateway initialised (ws=%s:%d, http=%s:%d)",
                 self.host, self.ws_port, self.host, self.http_port)

    # ── Startup ────────────────────────────────────────────────────────────────

    async def start(self):
        """Start WS server + HTTP server."""
        self._running = True
        ws_server = websockets.server.serve(self._handle_ws, self.host, self.ws_port)
        http_runner = await self._start_http()
        log.info("Gateway started: ws=%s:%d http=%s:%d",
                 self.host, self.ws_port, self.host, self.http_port)
        await asyncio.gather(
            ws_server,
            asyncio.ensure_future(self._timeout_sweep()),
            asyncio.Future(),   # run forever
        )

    # ── WebSocket handler ──────────────────────────────────────────────────────

    async def _handle_ws(self, websocket, path=None):
        """Handle a single WebSocket connection lifecycle."""
        client_info = {"user_id": None, "channel": None, "session_id": None}
        self._clients[websocket] = client_info
        try:
            async for raw_msg in websocket:
                try:
                    msg = json.loads(raw_msg)
                except json.JSONDecodeError:
                    await websocket.send(json.dumps(make_error("Invalid JSON")))
                    continue
                response = await self._route_message(websocket, msg, client_info)
                if response:
                    await websocket.send(json.dumps(response))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.pop(websocket, None)
            if client_info.get("role") == "node":
                wallet = client_info.get("wallet", "")
                hostname = client_info.get("hostname", "unknown")
                self.nodes.pop(wallet, None)
                log.info("Node disconnected: %s", hostname)
            else:
                log.debug("Client disconnected: %s", client_info.get("user_id"))

    async def _route_message(self, ws, msg: dict, client_info: dict) -> dict | None:
        """Route an incoming message to the appropriate handler."""
        msg_type = msg.get("type")
        payload = msg.get("payload", {})
        request_id = msg.get("request_id")

        if msg_type == "connect":
            token = payload.get("auth_token", "")
            if self.auth_token and token != self.auth_token:
                return make_error("Authentication failed", request_id)
            user_id = payload.get("user_id", "anonymous")
            channel = payload.get("channel", "unknown")
            session = self.sessions.get_or_create(user_id, channel)
            client_info.update(user_id=user_id, channel=channel,
                               session_id=session.session_id)
            log.info("Client connected: user=%s channel=%s session=%s",
                     user_id, channel, session.session_id)
            return make_message(MSG_CONNECTED, {"session_id": session.session_id},
                                request_id)

        if msg_type == MSG_NODE_REGISTER:
            token = payload.get("auth_token", "")
            if self.auth_token and token != self.auth_token:
                return make_error("Authentication failed", request_id)
            wallet = payload.get("wallet_address", "")
            hostname = payload.get("hostname", "unknown")
            capabilities = payload.get("capabilities", [])
            models = payload.get("models", [])
            resources = payload.get("resources", {})
            node_key = wallet or hostname
            self.nodes[node_key] = {
                "ws": ws,
                "hostname": hostname,
                "capabilities": capabilities,
                "models": models,
                "resources": resources,
                "last_heartbeat": time.time(),
            }
            client_info["role"] = "node"
            client_info["wallet"] = node_key
            client_info["hostname"] = hostname
            log.info("Node registered: %s (%s...) capabilities: %s",
                     hostname, wallet[:10] if wallet else "?", capabilities)
            return make_message(MSG_NODE_REGISTERED, {"status": "ok"}, request_id)

        if msg_type == MSG_NODE_HEARTBEAT:
            wallet = client_info.get("wallet", "")
            if wallet and wallet in self.nodes:
                self.nodes[wallet]["last_heartbeat"] = time.time()
                if "resources" in payload:
                    self.nodes[wallet]["resources"].update(payload["resources"])
                active_tasks = payload.get("active_tasks")
                if active_tasks is not None:
                    self.nodes[wallet]["resources"]["active_tasks"] = active_tasks
            return None

        if msg_type == MSG_NODE_RESPONSE and client_info.get("role") == "node":
            req_id = msg.get("request_id") or payload.get("request_id")
            pending = self._pending_requests.pop(req_id, None)
            if pending:
                result_msg = make_message(MSG_NODE_COMMAND_RESULT, {
                    "request_id": req_id,
                    "node":       pending["hostname"],
                    "command":    pending["command"],
                    "status":     payload.get("status"),
                    "result":     payload.get("result"),
                })
                try:
                    await pending["requester_ws"].send(json.dumps(result_msg))
                except Exception:
                    pass
                # Record reputation for the node that handled the command
                success     = payload.get("status") == "ok"
                duration_ms = int((time.time() - pending["timestamp"]) * 1000)
                record_reputation(
                    pending.get("node_wallet", ""),
                    pending.get("operation", pending["command"]),
                    success,
                    duration_ms,
                )
            else:
                log.warning("node_response for unknown request_id: %s", req_id)
            return None

        if not client_info.get("user_id"):
            return make_error("Not connected. Send 'connect' first.", request_id)

        if msg_type == "submit_task":
            description = payload.get("description", "")
            priority = payload.get("priority", "P2")
            if not description:
                return make_error("Missing task description", request_id)
            task_id = self.queue.add(description, priority=priority)
            await ws.send(json.dumps(make_message(MSG_COMMAND_RESPONSE,
                                                  {"task_id": task_id, "status": "queued"},
                                                  request_id)))
            await self._broadcast_event("task_added",
                                        {"task_id": task_id, "description": description})
            return None

        if msg_type == "queue_status":
            handled, response = handle_queue_command("show queue", self.queue)
            return make_message(MSG_QUEUE_RESPONSE,
                                {"text": response or "Queue empty"}, request_id)

        if msg_type == "command":
            cmd = payload.get("command", "")
            handled, response = handle_queue_command(cmd, self.queue)
            if handled:
                return make_message(MSG_COMMAND_RESPONSE,
                                    {"text": response or ""}, request_id)
            return make_error(f"Unknown command: {cmd}", request_id)

        if msg_type == MSG_NODE_COMMAND_REQUEST:
            target = payload.get("target_node", "")
            command = payload.get("command", "")
            args = payload.get("args", {})
            node_wallet, node_info = self._find_node(target)
            if node_info is None:
                return make_error(f"Node not connected: {target}", request_id)
            # Derive operation name (storage sub-actions get their own cost bucket)
            operation = (f"storage_{args.get('action', '')}"
                         if command == "storage" else command)
            requester_wallet = client_info.get("user_id", "unknown")
            allowed, cost = cost_check(requester_wallet, operation, node_wallet)
            if not allowed:
                return make_message(MSG_NODE_COMMAND_RESULT, {
                    "request_id": request_id,
                    "node":       node_info["hostname"],
                    "command":    command,
                    "status":     "error",
                    "result":     {"message": "insufficient ECT", "cost": cost},
                }, request_id)
            req_id = str(uuid.uuid4())
            self._pending_requests[req_id] = {
                "requester_ws":   ws,
                "timestamp":      time.time(),
                "hostname":       node_info["hostname"],
                "command":        command,
                "node_wallet":    node_wallet,
                "operation":      operation,
            }
            fwd = make_message(MSG_NODE_COMMAND, {
                "command":    command,
                "args":       args,
                "request_id": req_id,
            })
            try:
                await node_info["ws"].send(json.dumps(fwd))
            except Exception as exc:
                self._pending_requests.pop(req_id, None)
                return make_error(f"Failed to reach node {target}: {exc}", request_id)
            log.info("Routed %s → node %s (req=%s)", command, node_info["hostname"], req_id)
            return make_message(MSG_COMMAND_RESPONSE,
                                {"status": "pending", "request_id": req_id}, request_id)

        if msg_type == MSG_NODE_LIST:
            nodes = [
                {
                    "hostname": v["hostname"],
                    "wallet_address": k,
                    "capabilities": v["capabilities"],
                    "models": v["models"],
                    "resources": v["resources"],
                    "last_heartbeat": v["last_heartbeat"],
                    "connected": True,
                }
                for k, v in self.nodes.items()
            ]
            return make_message(MSG_COMMAND_RESPONSE, {"nodes": nodes}, request_id)

        return make_error(f"Unknown message type: {msg_type}", request_id)

    def _find_node(self, target: str):
        """Return (wallet, node_info) matching target by wallet_address or hostname."""
        if target in self.nodes:
            return target, self.nodes[target]
        for wallet, info in self.nodes.items():
            if info["hostname"] == target:
                return wallet, info
        return None, None

    async def _timeout_sweep(self):
        """Every 60 s, expire pending node commands older than 120 s."""
        while self._running:
            await asyncio.sleep(60)
            cutoff = time.time() - 120
            expired = [rid for rid, p in self._pending_requests.items()
                       if p["timestamp"] < cutoff]
            for rid in expired:
                pending = self._pending_requests.pop(rid, None)
                if not pending:
                    continue
                log.warning("node command timed out: req=%s node=%s cmd=%s",
                            rid, pending["hostname"], pending["command"])
                timeout_msg = make_message(MSG_NODE_COMMAND_RESULT, {
                    "request_id": rid,
                    "node":       pending["hostname"],
                    "command":    pending["command"],
                    "status":     "error",
                    "result":     {"message": "node command timed out"},
                })
                try:
                    await pending["requester_ws"].send(json.dumps(timeout_msg))
                except Exception:
                    pass

    async def _broadcast_event(self, event_name: str, data: dict):
        """Send an event to all connected clients."""
        msg = json.dumps(make_event(event_name, data))
        for ws in list(self._clients):
            try:
                await ws.send(msg)
            except Exception:
                pass

    # ── HTTP server ────────────────────────────────────────────────────────────

    async def _start_http(self):
        """Start aiohttp server for health endpoint."""
        app = aiohttp.web.Application()
        app.router.add_get("/health", self._health_handler)
        app.router.add_get("/nodes", self._nodes_handler)
        app.router.add_static("/chat", "/opt/nexus/webchat")
        app.router.add_get("/dashboard", self._dashboard_redirect)
        app.router.add_get("/dashboard/", self._dashboard_redirect)
        app.router.add_static("/dashboard", "/opt/nexus/dashboard/dist")
        runner = aiohttp.web.AppRunner(app)
        await runner.setup()
        site = aiohttp.web.TCPSite(runner, self.host, self.http_port)
        await site.start()
        return runner

    async def _dashboard_redirect(self, request):
        """Redirect bare /dashboard and /dashboard/ to the React app index."""
        raise aiohttp.web.HTTPFound("/dashboard/index.html")

    async def _health_handler(self, request):
        """HTTP GET /health — returns cluster health status."""
        health_data = {
            "status": "ok",
            "connected_clients": len(self._clients),
            "queue_size": len(self.queue.list_pending()),
        }
        return aiohttp.web.json_response(health_data)

    async def _nodes_handler(self, request):
        """HTTP GET /nodes — returns list of connected cluster nodes."""
        nodes = [
            {
                "hostname": v["hostname"],
                "wallet_address": k,
                "capabilities": v["capabilities"],
                "models": v["models"],
                "resources": v["resources"],
                "last_heartbeat": v["last_heartbeat"],
                "connected": True,
            }
            for k, v in self.nodes.items()
        ]
        return aiohttp.web.json_response(nodes)

    # ── Shutdown ───────────────────────────────────────────────────────────────

    async def stop(self):
        self._running = False
        log.info("Gateway stopping.")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv("/opt/nexus/agents/.env")
    except ImportError:
        pass

    gateway = NexusGateway()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(gateway.stop()))

    try:
        loop.run_until_complete(gateway.start())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()
