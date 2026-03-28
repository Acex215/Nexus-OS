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
from collections import defaultdict

import yaml

try:
    from eth_account.messages import encode_defunct
    from web3 import Web3
    _w3 = Web3()
    _HAS_WEB3 = True
except ImportError:
    _HAS_WEB3 = False

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

        # Connected channel clients: websocket → {user_id, channel, session_id}
        self._clients: dict = {}
        # Connected host nodes: wallet_address → {ws, hostname, capabilities, models, resources, last_heartbeat}
        self.nodes: dict = {}
        # Connected client nodes: wallet → {ws, hostname, capabilities, resources, last_heartbeat, connected_at}
        self.client_nodes: dict = {}
        # In-flight node commands: request_id → {requester_ws, timestamp, hostname, command}
        self._pending_requests: dict = {}
        # Rate limiting: wallet → list of message timestamps
        self._client_msg_times: dict = defaultdict(list)
        # Gradient submission tracking: wallet → last epoch submission timestamp
        self._gradient_submissions: dict = {}
        self._running = False

        _CLIENT_MAX_MSGS_PER_MIN = 10
        self._client_rate_limit = _CLIENT_MAX_MSGS_PER_MIN
        # Epoch duration for gradient rate limiting (default 1 hour)
        self._epoch_duration = 3600

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

    # ── Client wallet authentication ──────────────────────────────────────────

    def _verify_wallet_signature(self, wallet: str, signature: str, message: str) -> bool:
        """Verify that `signature` over `message` was produced by `wallet`.

        Message format expected: "nexus-auth-{timestamp}"
        Rejects messages older than 5 minutes.
        """
        if not _HAS_WEB3:
            log.warning("web3 not installed — wallet signature verification disabled")
            return True  # permissive fallback during development

        try:
            # Reject stale auth messages (> 5 min)
            parts = message.split("-")
            if len(parts) >= 3:
                try:
                    msg_ts = int(parts[-1])
                    if abs(time.time() - msg_ts) > 300:
                        log.warning("Auth message too old: %s", message)
                        return False
                except (ValueError, IndexError):
                    pass

            msg_obj = encode_defunct(text=message)
            recovered = _w3.eth.account.recover_message(msg_obj, signature=signature)
            if recovered.lower() == wallet.lower():
                return True
            log.warning("Signature mismatch: expected %s, recovered %s",
                        wallet, recovered)
            return False
        except Exception as exc:
            log.warning("Signature verification failed: %s", exc)
            return False

    def _check_client_rate_limit(self, wallet: str) -> bool:
        """Return True if the client is within the message rate limit (10/min)."""
        now = time.time()
        times = self._client_msg_times[wallet]
        # Prune entries older than 60 seconds
        self._client_msg_times[wallet] = [t for t in times if now - t < 60]
        if len(self._client_msg_times[wallet]) >= self._client_rate_limit:
            return False
        self._client_msg_times[wallet].append(now)
        return True

    def _check_gradient_rate(self, wallet: str) -> bool:
        """Return True if the client hasn't submitted a gradient this epoch."""
        now = time.time()
        last = self._gradient_submissions.get(wallet, 0)
        # Same epoch = same epoch_duration window
        if now - last < self._epoch_duration:
            return False
        return True

    # ── WebSocket handler ──────────────────────────────────────────────────────

    async def _handle_ws(self, websocket, path=None):
        """Handle a single WebSocket connection lifecycle."""
        # Auth check for remote connections
        remote_ip = websocket.remote_address[0] if hasattr(websocket, 'remote_address') else '127.0.0.1'
        if remote_ip not in ('127.0.0.1', '::1', 'localhost'):
            # Remote connection — require auth token
            try:
                auth_msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                token_path = "/opt/nexus/config/gateway_auth_token"
                if os.path.exists(token_path):
                    with open(token_path) as f:
                        expected = f.read().strip()
                    if auth_msg.strip() != expected:
                        await websocket.close(4001, "Invalid auth token")
                        return
                else:
                    await websocket.close(4002, "No auth token configured")
                    return
            except asyncio.TimeoutError:
                await websocket.close(4003, "Auth timeout")
                return

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
            role = client_info.get("role")
            wallet = client_info.get("wallet", "")
            hostname = client_info.get("hostname", "unknown")
            if role == "node":
                self.nodes.pop(wallet, None)
                log.info("Node disconnected: %s", hostname)
            elif role == "client":
                self.client_nodes.pop(wallet, None)
                self._client_msg_times.pop(wallet, None)
                log.info("Client node disconnected: %s (%s)", hostname, wallet[:10])
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
            role = payload.get("role", "node")
            wallet = payload.get("wallet_address", "")
            hostname = payload.get("hostname", "unknown")
            capabilities = payload.get("capabilities", [])
            models = payload.get("models", [])
            resources = payload.get("resources", {})

            if role == "client":
                # ── Client node: wallet signature authentication ──
                signature = payload.get("signature", "")
                auth_message = payload.get("auth_message", "")
                if not wallet:
                    return make_error("Client registration requires wallet_address", request_id)
                if not self._verify_wallet_signature(wallet, signature, auth_message):
                    log.warning("Client auth failed for wallet %s", wallet[:10])
                    try:
                        await ws.close(4001, "Authentication failed: invalid wallet signature")
                    except Exception:
                        pass
                    return None
                # Reject duplicate connections from same wallet
                if wallet in self.client_nodes:
                    return make_error("Wallet already connected as client", request_id)
                self.client_nodes[wallet] = {
                    "ws": ws,
                    "hostname": hostname,
                    "capabilities": capabilities,
                    "models": models,
                    "resources": resources,
                    "last_heartbeat": time.time(),
                    "connected_at": time.time(),
                }
                client_info["role"] = "client"
                client_info["wallet"] = wallet
                client_info["hostname"] = hostname
                log.info("Client node registered: %s (%s...) capabilities: %s",
                         hostname, wallet[:10], capabilities)
                return make_message(MSG_NODE_REGISTERED,
                                    {"status": "ok", "role": "client"}, request_id)
            else:
                # ── Host node: token authentication (existing behaviour) ──
                token = payload.get("auth_token", "")
                if self.auth_token and token != self.auth_token:
                    return make_error("Authentication failed", request_id)
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
            role = client_info.get("role")
            if role == "client" and wallet and wallet in self.client_nodes:
                if not self._check_client_rate_limit(wallet):
                    return None  # silently drop rate-limited heartbeats
                self.client_nodes[wallet]["last_heartbeat"] = time.time()
                for k in ("cpu_percent", "memory_percent", "disk_percent", "uptime_seconds"):
                    if k in payload:
                        self.client_nodes[wallet]["resources"][k] = payload[k]
            elif wallet and wallet in self.nodes:
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

        # ── Rate limiting for client nodes ──
        if client_info.get("role") == "client":
            wallet = client_info.get("wallet", "")
            if not self._check_client_rate_limit(wallet):
                return make_error("Rate limit exceeded (max 10 messages/minute)", request_id)

        # ── Gradient submission from client nodes ──
        if msg_type == "gradient_submit":
            if client_info.get("role") != "client":
                return make_error("gradient_submit is only available to client nodes", request_id)
            wallet = client_info.get("wallet", "")
            if not self._check_gradient_rate(wallet):
                return make_error("Gradient already submitted this epoch", request_id)
            gradient = payload.get("gradient", [])
            dim = payload.get("dim", 0)
            if not gradient or not dim:
                return make_error("Missing gradient data", request_id)
            self._gradient_submissions[wallet] = time.time()
            log.info("Gradient received from client %s (%d dim)",
                     wallet[:10], dim)
            return make_message(MSG_COMMAND_RESPONSE,
                                {"status": "accepted", "dim": dim}, request_id)

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
            # Check both host nodes and client nodes
            node_wallet, node_info = self._find_node(target)
            is_target_client = node_wallet in self.client_nodes if node_wallet else False
            if node_info is None:
                return make_error(f"Node not connected: {target}", request_id)
            # Permission check: commands TO client nodes are restricted
            if is_target_client and command != "health":
                return make_error(
                    f"Command '{command}' not allowed on client nodes (only 'health' permitted)",
                    request_id,
                )
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
                    "role": "node",
                    "capabilities": v["capabilities"],
                    "models": v["models"],
                    "resources": v["resources"],
                    "last_heartbeat": v["last_heartbeat"],
                    "connected": True,
                }
                for k, v in self.nodes.items()
            ]
            clients = [
                {
                    "hostname": v["hostname"],
                    "wallet_address": k,
                    "role": "client",
                    "capabilities": v["capabilities"],
                    "models": v.get("models", []),
                    "resources": v["resources"],
                    "last_heartbeat": v["last_heartbeat"],
                    "connected": True,
                }
                for k, v in self.client_nodes.items()
            ]
            return make_message(MSG_COMMAND_RESPONSE,
                                {"nodes": nodes, "clients": clients}, request_id)

        return make_error(f"Unknown message type: {msg_type}", request_id)

    def _find_node(self, target: str):
        """Return (wallet, node_info) matching target by wallet_address or hostname.

        Searches host nodes first, then client nodes.
        """
        if target in self.nodes:
            return target, self.nodes[target]
        for wallet, info in self.nodes.items():
            if info["hostname"] == target:
                return wallet, info
        # Also search client nodes (for health queries)
        if target in self.client_nodes:
            return target, self.client_nodes[target]
        for wallet, info in self.client_nodes.items():
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
        app.router.add_get("/clients", self._clients_handler)
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
            "node_count": len(self.nodes),
            "client_count": len(self.client_nodes),
            "queue_size": len(self.queue.list_pending()),
        }
        return aiohttp.web.json_response(health_data)

    async def _nodes_handler(self, request):
        """HTTP GET /nodes — returns list of connected host nodes (excludes clients)."""
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

    async def _clients_handler(self, request):
        """HTTP GET /clients — returns connected client nodes."""
        # Aggregate capabilities across all clients
        all_caps = {}
        for v in self.client_nodes.values():
            for cap in v.get("capabilities", []):
                all_caps[cap] = all_caps.get(cap, 0) + 1

        clients = [
            {
                "hostname": v["hostname"],
                "wallet_address": k,
                "capabilities": v["capabilities"],
                "resources": v["resources"],
                "last_heartbeat": v["last_heartbeat"],
                "connected_at": v.get("connected_at"),
            }
            for k, v in self.client_nodes.items()
        ]
        return aiohttp.web.json_response({
            "count": len(clients),
            "capability_summary": all_caps,
            "clients": clients,
        })

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
