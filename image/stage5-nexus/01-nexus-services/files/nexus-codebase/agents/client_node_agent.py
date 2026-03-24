#!/usr/bin/env python3
"""NEXUS Client Node Agent — lightweight agent for public client nodes.

Connects to the Gateway with role="client" and exposes a restricted
capability set: health queries, read-only IPFS, inference (if detected),
and hourly gradient submission for federated learning.

Compared to the host node_agent.py:
  - No exec command (clients cannot run arbitrary code)
  - No storage write (read-only IPFS: cat, stat, ls only)
  - 60s heartbeat (not 30s)
  - Hourly feature extraction with obfuscated gradient submission
  - Capabilities auto-detected from hardware

Usage:
    python3 client_node_agent.py [--gateway-url WS_URL]
    python3 client_node_agent.py --help
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import random
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

log = logging.getLogger("client_agent")

_BOOT_TIME = psutil.boot_time()
psutil.cpu_percent(interval=None)

KEYSTORE_DIR = "/opt/nexus/blockchain/keystore"
GRADIENT_QUEUE_PATH = "/opt/nexus/config/pending_gradients.json"
FEATURE_INTERVAL = 3600  # 1 hour
FEATURE_VECTOR_DIM = 64


# ── Keystore helper ──────────────────────────────────────────────────────────

def _read_wallet_from_keystore(keystore_dir: str = KEYSTORE_DIR) -> str:
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


# ── Capability auto-detection ────────────────────────────────────────────────

async def _check_port(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


async def _detect_models(timeout: float = 2.0) -> list:
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
    return models


def _has_hailo() -> bool:
    return Path("/dev/hailo0").exists()


async def _auto_detect_capabilities() -> list:
    caps = ["compute"]
    disk = psutil.disk_usage("/")
    free_gb = (disk.total - disk.used) / (1024 ** 3)
    if free_gb > 10:
        caps.append("storage")
    if _has_hailo():
        caps.append("inference")
    elif await _detect_models():
        caps.append("inference")
    return caps


def _static_resources() -> dict:
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "cpu_cores":  psutil.cpu_count(logical=True),
        "memory_gb":  round(mem.total / (1024 ** 3), 1),
        "storage_gb": round(disk.total / (1024 ** 3), 1),
        "ai_tops":    40 if _has_hailo() else None,
    }


def _live_resources() -> dict:
    mem  = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "cpu_percent":    psutil.cpu_percent(interval=None),
        "memory_percent": mem.percent,
        "disk_percent":   disk.percent,
        "uptime_seconds": int(time.time() - _BOOT_TIME),
    }


# ── Feature extraction (federated learning stub) ────────────────────────────

def _daily_salt() -> bytes:
    """Deterministic daily salt — in production, fetched from FlockCoordinator."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return hashlib.sha256(f"nexus-flock-salt-{day}".encode()).digest()


def _extract_features() -> list:
    """Stub: collect behavioural metrics and return a feature vector.

    In production this would collect real metrics (inference latency
    distributions, storage I/O patterns, network throughput, etc.).
    Currently returns random vectors as a placeholder.
    """
    rng = random.Random()
    return [round(rng.gauss(0, 1), 6) for _ in range(FEATURE_VECTOR_DIM)]


def _obfuscate_gradient(features: list, salt: bytes) -> list:
    """Apply differential-privacy-style noise seeded by daily salt."""
    rng = random.Random(salt)
    noise_scale = 0.1
    return [
        round(f + rng.gauss(0, noise_scale), 6)
        for f in features
    ]


def _queue_gradient(wallet: str, gradient: list):
    """Save gradient to disk for submission at epoch end."""
    entry = {
        "wallet": wallet,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gradient": gradient,
        "dim": len(gradient),
    }
    path = Path(GRADIENT_QUEUE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    pending = []
    if path.exists():
        try:
            pending = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pending = []

    pending.append(entry)
    # Keep at most 24 entries (one day of hourly submissions)
    pending = pending[-24:]

    path.write_text(json.dumps(pending, indent=2))
    log.info("Gradient queued (%d dim, %d pending)", len(gradient), len(pending))


# ── ClientNodeAgent ──────────────────────────────────────────────────────────

class ClientNodeAgent:
    """Lightweight agent for NEXUS client nodes.

    Differences from NodeAgent:
      - role="client" in registration
      - No exec command handler
      - Storage is read-only (cat, stat, ls only)
      - Heartbeat interval 60s
      - Hourly feature extraction loop
    """

    def __init__(self, cfg: argparse.Namespace):
        self.gateway_url        = cfg.gateway_url
        self.auth_token         = cfg.auth_token
        self.hostname           = cfg.hostname
        self.wallet             = cfg.wallet
        self.heartbeat_interval = cfg.heartbeat_interval
        self.no_blockchain      = getattr(cfg, "no_blockchain", False)

        self._ws: object = None
        self._models: list = []
        self._capabilities: list = []
        self._pending_hb: deque = deque(maxlen=10)
        self._shutdown = asyncio.Event()

    async def run(self):
        backoff = 1
        while not self._shutdown.is_set():
            try:
                await self._connect_and_run()
                backoff = 1
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
            log.info("Connected — registering as %s (%s) role=client",
                     self.hostname, wallet_display)

            self._models = await _detect_models()
            self._capabilities = await _auto_detect_capabilities()
            resources = _static_resources()

            await ws.send(json.dumps(make_message(MSG_NODE_REGISTER, {
                "auth_token":     self.auth_token,
                "hostname":       self.hostname,
                "wallet_address": self.wallet,
                "role":           "client",
                "capabilities":   self._capabilities,
                "models":         self._models,
                "resources":      resources,
            })))

            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            ack = json.loads(raw)
            if ack.get("type") != MSG_NODE_REGISTERED:
                raise RuntimeError(
                    f"Unexpected registration response: {ack.get('type')} — {ack}"
                )
            log.info("Registered — status: %s, capabilities: %s",
                     (ack.get("payload") or {}).get("status", "?"),
                     self._capabilities)

            asyncio.ensure_future(self._register_on_chain(resources))

            while self._pending_hb:
                payload = self._pending_hb.popleft()
                await ws.send(json.dumps(make_message(MSG_NODE_HEARTBEAT, payload)))

            try:
                await asyncio.gather(
                    self._heartbeat_loop(ws),
                    self._receive_loop(ws),
                    self._feature_extraction_loop(),
                )
            finally:
                self._ws = None

    # ── Heartbeat ────────────────────────────────────────────────────────────

    async def _heartbeat_loop(self, ws):
        while not self._shutdown.is_set():
            await asyncio.sleep(self.heartbeat_interval)
            payload = _live_resources()
            try:
                await ws.send(json.dumps(make_message(MSG_NODE_HEARTBEAT, payload)))
                log.debug("Heartbeat: cpu=%.1f%% mem=%.1f%%",
                          payload["cpu_percent"], payload["memory_percent"])
            except websockets.exceptions.ConnectionClosed:
                self._pending_hb.append(payload)
                raise

    # ── Receive ──────────────────────────────────────────────────────────────

    async def _receive_loop(self, ws):
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == MSG_NODE_COMMAND:
                asyncio.ensure_future(self._handle_command(msg))

    # ── Command dispatch (restricted) ────────────────────────────────────────

    async def _handle_command(self, msg: dict):
        payload    = msg.get("payload", {})
        command    = payload.get("command", "")
        args       = payload.get("args", {})
        request_id = payload.get("request_id")

        log.info("Command: %s (req=%s)", command, request_id)
        try:
            if command == "health":
                result = await self._health_command()
            elif command == "inference":
                result = await self._inference_command(args)
            elif command == "storage":
                result = await self._storage_read_command(args)
            elif command == "exec":
                result = {
                    "status": "error",
                    "result": {"message": "exec not available on client nodes"},
                }
            else:
                result = {
                    "status": "error",
                    "result": {"message": f"command not supported: {command}"},
                }
            response = make_message(
                MSG_NODE_RESPONSE,
                {"request_id": request_id, **result},
                request_id,
            )
            await self._send_raw(response)
        except Exception as exc:
            log.error("Error handling '%s': %s", command, exc)
            try:
                await self._send_raw(make_message(
                    MSG_NODE_RESPONSE,
                    {"request_id": request_id, "status": "error",
                     "result": {"message": str(exc)}},
                    request_id,
                ))
            except Exception:
                pass

    # ── On-chain registration ────────────────────────────────────────────────

    async def _register_on_chain(self, resources: dict):
        if self.no_blockchain:
            log.info("On-chain: skipped (--no-blockchain)")
            return
        if not self.wallet:
            log.info("On-chain: skipped (no wallet)")
            return

        hostname   = self.hostname
        wallet     = self.wallet
        cpu_cores  = int(resources.get("cpu_cores") or 0)
        memory_gb  = int(resources.get("memory_gb")  or 0)
        storage_gb = int(resources.get("storage_gb") or 0)
        ai_tops    = int(resources.get("ai_tops")    or 0)

        def _blocking_register():
            _libnexus_root = "/opt/nexus"
            if _libnexus_root not in sys.path:
                sys.path.insert(0, _libnexus_root)
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

    # ── Health ───────────────────────────────────────────────────────────────

    async def _health_command(self) -> dict:
        mem  = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        load = os.getloadavg()

        services = {
            "ipfs":      await _check_port("localhost", 5001),
            "ollama":    await _check_port("localhost", 11434),
            "lm_studio": await _check_port("localhost", 1234),
        }

        return {
            "status": "ok",
            "result": {
                "hostname":       self.hostname,
                "wallet_address": self.wallet,
                "role":           "client",
                "uptime_seconds": int(time.time() - _BOOT_TIME),
                "capabilities":   self._capabilities,
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
                },
                "services": services,
            },
        }

    # ── Storage (read-only) ──────────────────────────────────────────────────

    async def _storage_read_command(self, args: dict) -> dict:
        """Read-only IPFS access: cat, stat, ls. No pin/unpin."""
        action = args.get("action", "").strip()
        cid    = args.get("cid",    "").strip()

        if action in ("pin", "unpin", "add", "rm"):
            return {"status": "error",
                    "result": {"message": f"write operation '{action}' not allowed on client nodes"}}

        if not await _check_port("localhost", 5001):
            return {"status": "error",
                    "result": {"message": "IPFS not available on this node"}}

        if action not in ("cat", "stat", "ls"):
            return {"status": "error",
                    "result": {"message": f"unsupported storage action: {action!r} (client allows: cat, stat, ls)"}}

        if not cid:
            return {"status": "error",
                    "result": {"message": "missing args.cid"}}

        _IPFS = "http://localhost:5001"

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            ) as session:

                if action == "cat":
                    async with session.post(f"{_IPFS}/api/v0/cat",
                                            params={"arg": cid}) as resp:
                        if resp.status != 200:
                            err = await resp.text()
                            return {"status": "error",
                                    "result": {"message": f"cat failed: {err[:200]}"}}
                        raw = await resp.read()
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

        except asyncio.TimeoutError:
            return {"status": "error",
                    "result": {"message": "IPFS operation timed out after 30s"}}
        except aiohttp.ClientError as exc:
            return {"status": "error",
                    "result": {"message": f"IPFS request failed: {exc}"}}

    # ── Inference ────────────────────────────────────────────────────────────

    async def _inference_command(self, args: dict) -> dict:
        model_name  = args.get("model", "").strip()
        prompt      = args.get("prompt", "").strip()
        max_tokens  = int(args.get("max_tokens", 512))
        temperature = float(args.get("temperature", 0.7))

        if not prompt:
            return {"status": "error", "result": {"message": "missing args.prompt"}}
        if not self._models:
            return {"status": "error", "result": {"message": "no inference endpoint available"}}
        if not model_name:
            model_name = self._models[0]["name"]

        matched = [m for m in self._models if m["name"] == model_name]
        if not matched:
            return {"status": "error",
                    "result": {"message": "model not available",
                               "available_models": [m["name"] for m in self._models]}}

        model_info    = matched[0]
        endpoint_type = model_info["type"]
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
            return {"status": "error", "result": {"message": "inference timeout after 120s"}}
        except aiohttp.ClientError as exc:
            return {"status": "error", "result": {"message": f"inference request failed: {exc}"}}

    # ── Feature extraction loop ──────────────────────────────────────────────

    async def _feature_extraction_loop(self):
        """Hourly: extract features, obfuscate, queue gradient for submission."""
        while not self._shutdown.is_set():
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._shutdown.wait()),
                    timeout=FEATURE_INTERVAL,
                )
                break  # shutdown was set
            except asyncio.TimeoutError:
                pass  # interval elapsed, do work

            try:
                features = _extract_features()
                salt = _daily_salt()
                gradient = _obfuscate_gradient(features, salt)
                _queue_gradient(self.wallet or "unknown", gradient)

                # Submit via Gateway if connected
                if self._ws:
                    try:
                        await self._ws.send(json.dumps(make_message(
                            "gradient_submit",
                            {
                                "wallet": self.wallet,
                                "gradient": gradient,
                                "dim": len(gradient),
                            },
                        )))
                        log.info("Gradient submitted to Gateway")
                    except websockets.exceptions.ConnectionClosed:
                        log.debug("Gradient queued (Gateway offline)")
            except Exception as exc:
                log.warning("Feature extraction failed: %s", exc)

    # ── Helpers ──────────────────────────────────────────────────────────────

    async def _send_raw(self, msg: dict):
        if self._ws:
            await self._ws.send(json.dumps(msg))

    def request_shutdown(self):
        log.info("Shutdown requested.")
        self._shutdown.set()


# ── Argument parsing ─────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="NEXUS Client Node Agent — lightweight agent for public client nodes.",
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
        "--heartbeat-interval",
        type=int,
        default=int(os.environ.get("HEARTBEAT_INTERVAL", "60")),
        metavar="SECS",
        help="Heartbeat interval in seconds  (env: HEARTBEAT_INTERVAL)",
    )
    p.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "WARNING"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default WARNING for minimal output)",
    )
    p.add_argument(
        "--no-blockchain",
        action="store_true",
        default=False,
        help="Skip on-chain registration",
    )
    return p.parse_args()


# ── Entry point ──────────────────────────────────────────────────────────────

async def main():
    cfg = _parse_args()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    log.info("NEXUS Client Agent starting — hostname=%s", cfg.hostname)

    agent = ClientNodeAgent(cfg)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, agent.request_shutdown)

    await agent.run()
    log.info("Client Agent stopped.")


if __name__ == "__main__":
    asyncio.run(main())
