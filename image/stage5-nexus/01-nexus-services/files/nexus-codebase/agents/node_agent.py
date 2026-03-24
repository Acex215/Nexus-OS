#!/usr/bin/env python3
"""NEXUS Node Agent — connects to the Gateway WS and exposes node capabilities.

Runs on each Pi cluster node. Handles registration, heartbeats, and command
dispatch from the Gateway.

Usage:
    python3 node_agent.py [--gateway-url WS_URL] [--heartbeat-interval SECS]
    python3 node_agent.py --help
"""

import argparse
import asyncio
import json
import logging
import os
import shlex
import signal
import socket
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import psutil

try:
    import websockets
    import websockets.client
    import websockets.exceptions
except ImportError:
    raise SystemExit("ERROR: 'websockets' not installed. Run: pip install websockets")

try:
    import aiohttp
except ImportError:
    raise SystemExit("ERROR: 'aiohttp' not installed. Run: pip install aiohttp")

sys.path.insert(0, str(Path(__file__).parent))
from gateway_protocol import (
    MSG_NODE_REGISTER, MSG_NODE_HEARTBEAT, MSG_NODE_COMMAND, MSG_NODE_RESPONSE,
    MSG_NODE_REGISTERED,
    make_message,
)

log = logging.getLogger("node_agent")

_BOOT_TIME = psutil.boot_time()
# Initialise cpu_percent baseline so first heartbeat isn't 0.0
psutil.cpu_percent(interval=None)

# ── Exec sandbox ───────────────────────────────────────────────────────────────

COMMAND_ALLOWLIST = [
    "systemctl status",
    "df -h",
    "free -m",
    "uptime",
    "top -bn1",
    "ps aux",
    "ip addr",
    "cat /proc/cpuinfo",
    "cat /proc/meminfo",
    "docker ps",
    "kubectl get pods",
    "ls /opt/nexus/",
    "cat /opt/nexus/",
    "python3 -c",
    "pip list",
]

COMMAND_BLOCKLIST = [
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
    "mount",
    "umount",
]

_EXEC_LOG_PATH = "/opt/nexus/logs/node_exec.log"
_EXEC_TIMEOUT  = 30


def _validate_command(cmd: str) -> tuple:
    """Return (allowed: bool, reason: str).

    Blocklist is checked first; any substring match is an immediate reject.
    Then the command must start with at least one allowlist prefix.
    """
    for blocked in COMMAND_BLOCKLIST:
        if blocked in cmd:
            return False, f"blocked: {blocked!r}"
    for prefix in COMMAND_ALLOWLIST:
        if cmd.startswith(prefix):
            return True, ""
    return False, "command not in allowlist"


def _log_exec(cmd: str, return_code: int, duration_ms: int) -> None:
    """Append one audit line to node_exec.log."""
    try:
        os.makedirs(os.path.dirname(_EXEC_LOG_PATH), exist_ok=True)
        ts   = datetime.now(timezone.utc).isoformat()
        line = f"{ts}\trc={return_code}\t{duration_ms}ms\t{cmd}\n"
        with open(_EXEC_LOG_PATH, "a") as fh:
            fh.write(line)
    except OSError as exc:
        log.warning("Failed to write exec log: %s", exc)


async def _check_port(host: str, port: int, timeout: float = 1.0) -> bool:
    """Return True if a TCP connection to host:port succeeds within timeout."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


# ── Keystore helper ────────────────────────────────────────────────────────────

def _read_wallet_from_keystore(keystore_dir: str = "/opt/nexus/keystore") -> str:
    """Return the address from the first Geth keystore file found."""
    ks = Path(keystore_dir)
    if not ks.is_dir():
        return ""
    for f in sorted(ks.iterdir()):
        if f.is_file():
            try:
                data = json.loads(f.read_text())
                addr = data.get("address", "")
                if addr:
                    return "0x" + addr if not addr.startswith("0x") else addr
            except (json.JSONDecodeError, OSError):
                continue
    return ""


# ── Model detection ────────────────────────────────────────────────────────────

async def _detect_models(timeout: float = 2.0) -> list:
    """Probe local LLM endpoints: LM Studio (port 1234) and Ollama (port 11434)."""
    models = []
    probes = [
        ("lmstudio", "http://localhost:1234/v1/models"),
        ("ollama",   "http://localhost:11434/api/tags"),
    ]
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            for model_type, url in probes:
                try:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json(content_type=None)
                        if model_type == "lmstudio":
                            for m in data.get("data", []):
                                models.append({
                                    "name": m.get("id", "unknown"),
                                    "endpoint": "http://localhost:1234",
                                    "type": "lmstudio",
                                })
                        elif model_type == "ollama":
                            for m in data.get("models", []):
                                models.append({
                                    "name": m.get("name", "unknown"),
                                    "endpoint": "http://localhost:11434",
                                    "type": "ollama",
                                })
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    pass
    except Exception:
        pass
    if models:
        log.info("Detected %d local model(s): %s",
                 len(models), [m["name"] for m in models])
    return models


# ── Resource snapshots ─────────────────────────────────────────────────────────

def _static_resources() -> dict:
    """One-time hardware snapshot sent at registration."""
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "cpu_cores":  psutil.cpu_count(logical=True),
        "memory_gb":  round(mem.total / (1024 ** 3), 1),
        "storage_gb": round(disk.total / (1024 ** 3), 1),
        "ai_tops":    None,
    }


def _live_resources() -> dict:
    """Current utilisation snapshot for heartbeats and health commands."""
    mem  = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "cpu_percent":    psutil.cpu_percent(interval=None),
        "memory_percent": mem.percent,
        "disk_percent":   disk.percent,
        "gpu_percent":    None,
        "uptime_seconds": int(time.time() - _BOOT_TIME),
    }


# ── NodeAgent ──────────────────────────────────────────────────────────────────

class NodeAgent:
    def __init__(self, cfg: argparse.Namespace):
        self.gateway_url        = cfg.gateway_url
        self.auth_token         = cfg.auth_token
        self.hostname           = cfg.hostname
        self.wallet             = cfg.wallet
        self.capabilities       = [c.strip() for c in cfg.capabilities.split(",") if c.strip()]
        self.heartbeat_interval = cfg.heartbeat_interval

        self.no_blockchain = getattr(cfg, "no_blockchain", False)

        self._ws: object = None
        self._active_tasks: int = 0
        self._models: list = []   # populated on each connect from _detect_models()
        # Pending heartbeat payloads buffered while offline (oldest dropped when full)
        self._pending_hb: deque = deque(maxlen=10)
        self._shutdown = asyncio.Event()

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def run(self):
        """Connect, register, and run forever — with exponential backoff reconnect."""
        backoff = 1
        while not self._shutdown.is_set():
            try:
                await self._connect_and_run()
                backoff = 1  # clean disconnect — reset backoff
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.warning("Connection lost: %s — retrying in %ds", exc, backoff)

            if not self._shutdown.is_set():
                try:
                    await asyncio.wait_for(
                        asyncio.shield(self._shutdown.wait()), timeout=backoff
                    )
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 60)

    async def _connect_and_run(self):
        log.info("Connecting to Gateway: %s", self.gateway_url)
        async with websockets.client.connect(self.gateway_url) as ws:
            self._ws = ws
            wallet_display = (self.wallet[:10] + "...") if self.wallet else "no-wallet"
            log.info("Connected — registering as %s (%s)", self.hostname, wallet_display)

            models    = await _detect_models()
            self._models = models
            resources = _static_resources()

            await ws.send(json.dumps(make_message(MSG_NODE_REGISTER, {
                "auth_token":     self.auth_token,
                "hostname":       self.hostname,
                "wallet_address": self.wallet,
                "capabilities":   self.capabilities,
                "models":         models,
                "resources":      resources,
            })))

            # Wait for "registered" ack before starting loops
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            ack = json.loads(raw)
            if ack.get("type") != MSG_NODE_REGISTERED:
                raise RuntimeError(
                    f"Unexpected registration response: {ack.get('type')} — {ack}"
                )
            log.info("Registered — status: %s", (ack.get("payload") or {}).get("status", "?"))

            # Fire-and-forget on-chain registration (non-blocking — Geth can take 5+ s)
            asyncio.ensure_future(self._register_on_chain(resources))

            # Drain any heartbeats that buffered while we were offline
            while self._pending_hb:
                payload = self._pending_hb.popleft()
                await ws.send(json.dumps(make_message(MSG_NODE_HEARTBEAT, payload)))
                log.debug("Drained buffered heartbeat")

            # Run heartbeat producer and message receiver concurrently
            try:
                await asyncio.gather(
                    self._heartbeat_loop(ws),
                    self._receive_loop(ws),
                )
            finally:
                self._ws = None

    # ── Heartbeat loop ─────────────────────────────────────────────────────────

    async def _heartbeat_loop(self, ws):
        while not self._shutdown.is_set():
            await asyncio.sleep(self.heartbeat_interval)
            payload = {**_live_resources(), "active_tasks": self._active_tasks}
            try:
                await ws.send(json.dumps(make_message(MSG_NODE_HEARTBEAT, payload)))
                log.debug("Heartbeat: cpu=%.1f%% mem=%.1f%% disk=%.1f%%",
                          payload["cpu_percent"],
                          payload["memory_percent"],
                          payload["disk_percent"])
            except websockets.exceptions.ConnectionClosed:
                self._pending_hb.append(payload)
                raise

    # ── Receive loop ───────────────────────────────────────────────────────────

    async def _receive_loop(self, ws):
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                log.warning("Received non-JSON message, skipping")
                continue
            if msg.get("type") == MSG_NODE_COMMAND:
                asyncio.ensure_future(self._handle_command(msg))
            else:
                log.debug("Unhandled message type: %s", msg.get("type"))

    # ── Command dispatch ───────────────────────────────────────────────────────

    async def _handle_command(self, msg: dict):
        payload    = msg.get("payload", {})
        command    = payload.get("command", "")
        args       = payload.get("args", {})
        request_id = payload.get("request_id")

        log.info("Command: %s (req=%s)", command, request_id)
        try:
            if command == "health":
                health_out = await self._health_command()
                response   = make_message(
                    MSG_NODE_RESPONSE,
                    {"request_id": request_id, **health_out},
                    request_id,
                )
            elif command == "exec":
                cmd_str  = args.get("command", "").strip()
                if not cmd_str:
                    exec_out = {"status": "error",
                                "result": {"message": "missing args.command"}}
                else:
                    exec_out = await self._exec_command(cmd_str)
                response = make_message(
                    MSG_NODE_RESPONSE,
                    {"request_id": request_id, **exec_out},
                    request_id,
                )
            elif command == "inference":
                inf_out  = await self._inference_command(args)
                response = make_message(
                    MSG_NODE_RESPONSE,
                    {"request_id": request_id, **inf_out},
                    request_id,
                )
            elif command == "storage":
                stor_out = await self._storage_command(args)
                response = make_message(
                    MSG_NODE_RESPONSE,
                    {"request_id": request_id, **stor_out},
                    request_id,
                )
            else:
                response = make_message(
                    MSG_NODE_RESPONSE,
                    {"request_id": request_id, "status": "error",
                     "result": {"message": "command not implemented"}},
                    request_id,
                )
            await self._send_raw(response)
        except Exception as exc:
            log.error("Error handling command '%s': %s", command, exc)
            try:
                await self._send_raw(make_message(
                    MSG_NODE_RESPONSE,
                    {"request_id": request_id, "status": "error",
                     "result": {"message": str(exc)}},
                    request_id,
                ))
            except Exception:
                pass

    async def _register_on_chain(self, resources: dict):
        """Register this node in the ResourceManager contract. Non-blocking."""
        if self.no_blockchain:
            log.info("On-chain: skipped (--no-blockchain)")
            return
        if not self.wallet:
            log.info("On-chain: skipped (no wallet configured)")
            return

        hostname   = self.hostname
        wallet     = self.wallet
        cpu_cores  = int(resources.get("cpu_cores") or 0)
        memory_gb  = int(resources.get("memory_gb")  or 0)
        storage_gb = int(resources.get("storage_gb") or 0)
        ai_tops    = int(resources.get("ai_tops")    or 0)

        def _blocking_register():
            # Lazy import — keeps node_agent importable without web3 installed
            import sys as _sys
            _libnexus_root = "/opt/nexus"
            if _libnexus_root not in _sys.path:
                _sys.path.insert(0, _libnexus_root)
            from libnexus.kernel import NexusKernel
            kernel = NexusKernel(rpc_url="http://10.0.20.3:8545", wallet=wallet)
            return kernel.register_node(hostname, cpu_cores, memory_gb, storage_gb, ai_tops)

        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, _blocking_register)
            log.info("On-chain registration: tx=%s block=%s",
                     result.get("tx_hash"), result.get("block"))
        except ConnectionError as exc:
            log.warning("On-chain: skipped (blockchain unreachable — %s)", exc)
        except Exception as exc:
            if "already" in str(exc).lower():
                log.info("On-chain: already registered")
            else:
                log.warning("On-chain registration failed: %s", exc)

    async def _health_command(self) -> dict:
        """Return comprehensive node health including services reachability."""
        mem  = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        net  = psutil.net_io_counters()
        load = os.getloadavg()

        services = {
            "ipfs":      await _check_port("localhost", 5001),
            "ollama":    await _check_port("localhost", 11434),
            "lm_studio": await _check_port("localhost", 1234),
            "geth":      await _check_port("localhost", 8545),
            "k3s":       await _check_port("localhost", 6443),
        }

        return {
            "status": "ok",
            "result": {
                "hostname":       self.hostname,
                "wallet_address": self.wallet,
                "uptime_seconds": int(time.time() - _BOOT_TIME),
                "cpu": {
                    "cores":    psutil.cpu_count(logical=True),
                    "percent":  psutil.cpu_percent(interval=None),
                    "load_avg": list(load),
                },
                "memory": {
                    "total_gb": round(mem.total / (1024 ** 3), 2),
                    "used_gb":  round(mem.used  / (1024 ** 3), 2),
                    "percent":  mem.percent,
                },
                "disk": {
                    "total_gb": round(disk.total / (1024 ** 3), 2),
                    "used_gb":  round(disk.used  / (1024 ** 3), 2),
                    "percent":  disk.percent,
                    "mount":    "/",
                },
                "gpu": {
                    "available": False,
                    "percent":   None,
                },
                "network": {
                    "bytes_sent": net.bytes_sent,
                    "bytes_recv": net.bytes_recv,
                },
                "services": services,
            },
        }

    async def _storage_command(self, args: dict) -> dict:
        """Execute an IPFS operation via the local Kubo HTTP API (port 5001)."""
        action = args.get("action", "").strip()
        cid    = args.get("cid",    "").strip()

        if not await _check_port("localhost", 5001):
            return {"status": "error",
                    "result": {"message": "IPFS not available on this node"}}
        if not action:
            return {"status": "error", "result": {"message": "missing args.action"}}

        _IPFS = "http://localhost:5001"

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            ) as session:

                if action in ("pin", "unpin", "cat", "stat", "ls"):
                    if not cid:
                        return {"status": "error",
                                "result": {"message": "missing args.cid"}}

                if action == "pin":
                    async with session.post(f"{_IPFS}/api/v0/pin/add",
                                            params={"arg": cid}) as resp:
                        if resp.status != 200:
                            err = await resp.text()
                            return {"status": "error",
                                    "result": {"message": f"pin failed: {err[:200]}"}}
                        return {"status": "ok", "result": {"pinned": cid}}

                elif action == "unpin":
                    async with session.post(f"{_IPFS}/api/v0/pin/rm",
                                            params={"arg": cid}) as resp:
                        if resp.status != 200:
                            err = await resp.text()
                            return {"status": "error",
                                    "result": {"message": f"unpin failed: {err[:200]}"}}
                        return {"status": "ok", "result": {"unpinned": cid}}

                elif action == "cat":
                    async with session.post(f"{_IPFS}/api/v0/cat",
                                            params={"arg": cid}) as resp:
                        if resp.status != 200:
                            err = await resp.text()
                            return {"status": "error",
                                    "result": {"message": f"cat failed: {err[:200]}"}}
                        raw       = await resp.read()
                        truncated = len(raw) > 10240
                        return {
                            "status": "ok",
                            "result": {
                                "data":      raw[:10240].decode("utf-8", errors="replace"),
                                "size":      len(raw),
                                "truncated": truncated,
                            },
                        }

                elif action == "stat":
                    async with session.post(f"{_IPFS}/api/v0/object/stat",
                                            params={"arg": cid}) as resp:
                        if resp.status != 200:
                            err = await resp.text()
                            return {"status": "error",
                                    "result": {"message": f"stat failed: {err[:200]}"}}
                        data = await resp.json(content_type=None)
                        return {
                            "status": "ok",
                            "result": {
                                "hash":       data.get("Hash"),
                                "size":       data.get("CumulativeSize"),
                                "block_size": data.get("BlockSize"),
                                "data_size":  data.get("DataSize"),
                                "num_links":  data.get("NumLinks"),
                            },
                        }

                elif action == "ls":
                    async with session.post(f"{_IPFS}/api/v0/ls",
                                            params={"arg": cid}) as resp:
                        if resp.status != 200:
                            err = await resp.text()
                            return {"status": "error",
                                    "result": {"message": f"ls failed: {err[:200]}"}}
                        data  = await resp.json(content_type=None)
                        links = [
                            {"name": lnk.get("Name"),
                             "hash": lnk.get("Hash"),
                             "size": lnk.get("Size")}
                            for obj in data.get("Objects", [])
                            for lnk in obj.get("Links", [])
                        ]
                        return {"status": "ok", "result": {"links": links}}

                else:
                    return {"status": "error",
                            "result": {"message": f"unknown storage action: {action!r}"}}

        except asyncio.TimeoutError:
            return {"status": "error",
                    "result": {"message": "IPFS operation timed out after 30s"}}
        except aiohttp.ClientError as exc:
            return {"status": "error",
                    "result": {"message": f"IPFS request failed: {exc}"}}

    async def _inference_command(self, args: dict) -> dict:
        """Forward an inference request to the local LLM endpoint.

        Supports Ollama (port 11434) and LM Studio (port 1234).
        Returns {"status": "ok|error", "result": {...}}.
        """
        model_name  = args.get("model", "").strip()
        prompt      = args.get("prompt", "").strip()
        max_tokens  = int(args.get("max_tokens", 512))
        temperature = float(args.get("temperature", 0.7))

        if not prompt:
            return {"status": "error", "result": {"message": "missing args.prompt"}}
        if not model_name:
            if not self._models:
                return {"status": "error", "result": {"message": "missing args.model"}}
            model_name = self._models[0]["name"]

        if not self._models:
            return {"status": "error", "result": {"message": "no inference endpoint available"}}

        matched = [m for m in self._models if m["name"] == model_name]
        if not matched:
            available = [m["name"] for m in self._models]
            return {"status": "error",
                    "result": {"message": "model not available",
                               "available_models": available}}

        model_info    = matched[0]
        endpoint_type = model_info["type"]
        log.info("inference: model=%s endpoint=%s max_tokens=%d",
                 model_name, endpoint_type, max_tokens)

        start = time.monotonic()
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=120)
            ) as session:
                if endpoint_type == "ollama":
                    url  = "http://localhost:11434/api/generate"
                    body = {
                        "model":   model_name,
                        "prompt":  prompt,
                        "stream":  False,
                        "options": {
                            "num_predict": max_tokens,
                            "temperature": temperature,
                        },
                    }
                    async with session.post(url, json=body) as resp:
                        duration_ms = int((time.monotonic() - start) * 1000)
                        if resp.status != 200:
                            err = await resp.text()
                            return {"status": "error",
                                    "result": {"message": f"ollama error {resp.status}: {err[:200]}"}}
                        data = await resp.json(content_type=None)
                        return {
                            "status": "ok",
                            "result": {
                                "text":             data.get("response", ""),
                                "model":            model_name,
                                "tokens_generated": data.get("eval_count"),
                                "duration_ms":      duration_ms,
                            },
                        }

                elif endpoint_type == "lmstudio":
                    url  = "http://localhost:1234/v1/completions"
                    body = {
                        "model":       model_name,
                        "prompt":      prompt,
                        "max_tokens":  max_tokens,
                        "temperature": temperature,
                        "stream":      False,
                    }
                    async with session.post(url, json=body) as resp:
                        duration_ms = int((time.monotonic() - start) * 1000)
                        if resp.status != 200:
                            err = await resp.text()
                            return {"status": "error",
                                    "result": {"message": f"lmstudio error {resp.status}: {err[:200]}"}}
                        data    = await resp.json(content_type=None)
                        choices = data.get("choices", [])
                        return {
                            "status": "ok",
                            "result": {
                                "text":             choices[0].get("text", "") if choices else "",
                                "model":            model_name,
                                "tokens_generated": (data.get("usage") or {}).get("completion_tokens"),
                                "duration_ms":      duration_ms,
                            },
                        }

                else:
                    return {"status": "error",
                            "result": {"message": f"unknown endpoint type: {endpoint_type}"}}

        except asyncio.TimeoutError:
            duration_ms = int((time.monotonic() - start) * 1000)
            log.warning("inference timeout: model=%s duration=%dms", model_name, duration_ms)
            return {"status": "error", "result": {"message": "inference timeout after 120s"}}
        except aiohttp.ClientError as exc:
            return {"status": "error", "result": {"message": f"inference request failed: {exc}"}}

    async def _exec_command(self, cmd: str) -> dict:
        """Validate and execute a sandboxed shell command.

        Uses asyncio.create_subprocess_exec (NOT shell=True) so shell
        metacharacters in arguments are never interpreted by a shell.
        Returns {"status": "ok|error", "result": {...}}.
        """
        allowed, reason = _validate_command(cmd)
        if not allowed:
            log.warning("exec rejected: %s — %s", cmd, reason)
            _log_exec(cmd, -2, 0)
            return {"status": "error", "result": {"message": reason}}

        try:
            args = shlex.split(cmd)
        except ValueError as exc:
            return {"status": "error", "result": {"message": f"invalid command syntax: {exc}"}}

        log.info("exec: %s", cmd)
        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return {"status": "error", "result": {"message": f"command not found: {args[0]}"}}
        except PermissionError as exc:
            return {"status": "error", "result": {"message": f"permission denied: {exc}"}}

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=_EXEC_TIMEOUT
            )
            duration_ms  = int((time.monotonic() - start) * 1000)
            return_code  = proc.returncode
            _log_exec(cmd, return_code, duration_ms)
            return {
                "status": "ok",
                "result": {
                    "stdout":      stdout_b.decode("utf-8", errors="replace"),
                    "stderr":      stderr_b.decode("utf-8", errors="replace"),
                    "return_code": return_code,
                    "duration_ms": duration_ms,
                },
            }
        except asyncio.TimeoutError:
            duration_ms = int((time.monotonic() - start) * 1000)
            try:
                proc.kill()
                await proc.communicate()
            except Exception:
                pass
            _log_exec(cmd, -1, duration_ms)
            log.warning("exec timeout: %s", cmd)
            return {"status": "error",
                    "result": {"message": f"timeout after {_EXEC_TIMEOUT}s"}}

    async def _send_raw(self, msg: dict):
        if self._ws:
            await self._ws.send(json.dumps(msg))

    # ── Shutdown ───────────────────────────────────────────────────────────────

    def request_shutdown(self):
        log.info("Shutdown requested.")
        self._shutdown.set()


# ── Argument parsing ───────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="NEXUS Node Agent — registers this node with the Gateway.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--gateway-url",
        default=os.environ.get("GATEWAY_URL", "ws://10.0.20.1:8766/ws"),
        metavar="URL",
        help="Gateway WebSocket URL  (env: GATEWAY_URL)",
    )
    p.add_argument(
        "--auth-token",
        default=os.environ.get("GATEWAY_AUTH_TOKEN", ""),
        metavar="TOKEN",
        help="Gateway auth token  (env: GATEWAY_AUTH_TOKEN)",
    )
    p.add_argument(
        "--hostname",
        default=os.environ.get("NODE_HOSTNAME", socket.gethostname()),
        help="Node hostname  (env: NODE_HOSTNAME)",
    )
    p.add_argument(
        "--wallet",
        default=os.environ.get("NODE_WALLET", _read_wallet_from_keystore()),
        metavar="ADDRESS",
        help="Node wallet address  (env: NODE_WALLET)",
    )
    p.add_argument(
        "--capabilities",
        default=os.environ.get("NODE_CAPABILITIES", "compute"),
        metavar="CAP1,CAP2,...",
        help="Comma-separated capabilities  (env: NODE_CAPABILITIES)",
    )
    p.add_argument(
        "--heartbeat-interval",
        type=int,
        default=int(os.environ.get("HEARTBEAT_INTERVAL", "30")),
        metavar="SECS",
        help="Heartbeat interval in seconds  (env: HEARTBEAT_INTERVAL)",
    )
    p.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity",
    )
    p.add_argument(
        "--no-blockchain",
        action="store_true",
        default=False,
        help="Skip on-chain registration (useful when Geth is down or during testing)",
    )
    return p.parse_args()


# ── Entry point ────────────────────────────────────────────────────────────────

async def main():
    cfg = _parse_args()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    log.info("NEXUS Node Agent starting — hostname=%s capabilities=%s",
             cfg.hostname, cfg.capabilities)

    agent = NodeAgent(cfg)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, agent.request_shutdown)

    await agent.run()
    log.info("Node Agent stopped.")


if __name__ == "__main__":
    asyncio.run(main())
