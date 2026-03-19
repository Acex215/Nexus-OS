"""
health_monitor.py — Infrastructure health checks for the NEXUS OS dev assistant.

Called on demand by queue_commands.py or the autonomous loop on startup.
Does NOT run on a schedule.
"""

import asyncio
import logging
import shutil
import time
from datetime import datetime, timezone

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    aiohttp = None  # type: ignore
    HAS_AIOHTTP = False
    logging.getLogger("health_monitor").warning(
        "aiohttp not installed — HTTP health checks will be limited. "
        "Run: pip install aiohttp"
    )

from safety_config import DISK_MIN_FREE_GB, LLM_HEALTH_TIMEOUT

log = logging.getLogger("health_monitor")


class HealthMonitor:
    """Check that all infrastructure dependencies (disk, LLMs, blockchain) are alive."""

    def __init__(
        self,
        llm_endpoints: dict,
        blockchain_rpc: str = "http://10.0.20.3:8545",
    ):
        """
        Args:
            llm_endpoints: Mapping of tier name → URL, e.g.
                {"coordinator": "http://10.0.30.3:1234/v1/models",
                 "coder":       "http://10.0.30.2:1234/v1/models"}
            blockchain_rpc: Geth HTTP JSON-RPC endpoint.
        """
        self.llm_endpoints = llm_endpoints
        self.blockchain_rpc = blockchain_rpc

    # -------------------------------------------------------------------------
    # Public entry point
    # -------------------------------------------------------------------------

    async def check_all(self) -> dict:
        """Run all health checks concurrently and return a consolidated report."""
        llm_coros = {
            f"llm_{tier}": self.check_llm(tier, url)
            for tier, url in self.llm_endpoints.items()
        }

        results = await asyncio.gather(
            self.check_disk(),
            self.check_blockchain(),
            *llm_coros.values(),
            return_exceptions=True,
        )

        disk_result = results[0]
        blockchain_result = results[1]
        llm_results = results[2:]

        checks: dict = {}

        checks["disk"] = (
            disk_result
            if isinstance(disk_result, dict)
            else {"ok": False, "free_gb": 0.0, "message": str(disk_result)}
        )

        checks["blockchain"] = (
            blockchain_result
            if isinstance(blockchain_result, dict)
            else {"ok": False, "block_number": 0, "message": str(blockchain_result)}
        )

        for key, result in zip(llm_coros.keys(), llm_results):
            checks[key] = (
                result
                if isinstance(result, dict)
                else {"ok": False, "latency_ms": 0, "message": str(result)}
            )

        healthy = all(v.get("ok", False) for v in checks.values())
        log.info(
            "Health check complete — %s (%d/%d checks ok)",
            "HEALTHY" if healthy else "UNHEALTHY",
            sum(1 for v in checks.values() if v.get("ok")),
            len(checks),
        )

        return {
            "healthy": healthy,
            "checks": checks,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # -------------------------------------------------------------------------
    # Individual checks
    # -------------------------------------------------------------------------

    async def check_disk(self) -> dict:
        """Check free disk space under /opt/nexus."""
        try:
            usage = shutil.disk_usage("/opt/nexus")
            free_gb = usage.free / (1024 ** 3)
            ok = free_gb >= DISK_MIN_FREE_GB
            message = (
                f"{free_gb:.1f} GB free"
                if ok
                else f"only {free_gb:.1f} GB free (minimum {DISK_MIN_FREE_GB} GB)"
            )
            log.debug("check_disk: %s", message)
            return {"ok": ok, "free_gb": round(free_gb, 2), "message": message}
        except Exception as exc:
            log.warning("check_disk failed: %s", exc)
            return {"ok": False, "free_gb": 0.0, "message": str(exc)}

    async def check_llm(self, tier: str, url: str) -> dict:
        """HTTP GET the LLM models endpoint and record latency."""
        if not HAS_AIOHTTP:
            log.warning("check_llm[%s]: aiohttp not installed", tier)
            return {"ok": False, "latency_ms": 0, "message": "aiohttp not installed"}

        timeout = aiohttp.ClientTimeout(total=LLM_HEALTH_TIMEOUT)
        start = time.monotonic()
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    latency_ms = int((time.monotonic() - start) * 1000)
                    ok = resp.status == 200
                    message = f"{latency_ms}ms" if ok else f"HTTP {resp.status}"
                    log.debug("check_llm[%s]: %s", tier, message)
                    return {"ok": ok, "latency_ms": latency_ms, "message": message}
        except aiohttp.ClientConnectionError as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            msg = f"Connection refused ({exc.__class__.__name__})"
            log.warning("check_llm[%s]: %s", tier, msg)
            return {"ok": False, "latency_ms": latency_ms, "message": msg}
        except asyncio.TimeoutError:
            latency_ms = int((time.monotonic() - start) * 1000)
            msg = f"Timed out after {LLM_HEALTH_TIMEOUT}s"
            log.warning("check_llm[%s]: %s", tier, msg)
            return {"ok": False, "latency_ms": latency_ms, "message": msg}
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            msg = str(exc)
            log.warning("check_llm[%s]: %s", tier, msg)
            return {"ok": False, "latency_ms": latency_ms, "message": msg}

    async def check_blockchain(self) -> dict:
        """Call eth_blockNumber via JSON-RPC. Falls back to urllib if aiohttp unavailable."""
        payload = {"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1}
        if HAS_AIOHTTP:
            return await self._check_blockchain_aiohttp(payload)
        return await self._check_blockchain_urllib(payload)

    async def _check_blockchain_aiohttp(self, payload: dict) -> dict:
        timeout = aiohttp.ClientTimeout(total=LLM_HEALTH_TIMEOUT)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.blockchain_rpc, json=payload) as resp:
                    if resp.status != 200:
                        msg = f"HTTP {resp.status}"
                        log.warning("check_blockchain: %s", msg)
                        return {"ok": False, "block_number": 0, "message": msg}
                    data = await resp.json(content_type=None)
                    return self._parse_block_response(data)
        except aiohttp.ClientConnectionError as exc:
            msg = f"Connection refused ({exc.__class__.__name__})"
            log.warning("check_blockchain: %s", msg)
            return {"ok": False, "block_number": 0, "message": msg}
        except asyncio.TimeoutError:
            msg = f"Timed out after {LLM_HEALTH_TIMEOUT}s"
            log.warning("check_blockchain: %s", msg)
            return {"ok": False, "block_number": 0, "message": msg}
        except Exception as exc:
            msg = str(exc)
            log.warning("check_blockchain: %s", msg)
            return {"ok": False, "block_number": 0, "message": msg}

    async def _check_blockchain_urllib(self, payload: dict) -> dict:
        import json
        import urllib.request
        import urllib.error

        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            self.blockchain_rpc,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            loop = asyncio.get_event_loop()
            def _do_request():
                with urllib.request.urlopen(req, timeout=LLM_HEALTH_TIMEOUT) as resp:
                    return json.loads(resp.read())
            data = await loop.run_in_executor(None, _do_request)
            return self._parse_block_response(data)
        except urllib.error.URLError as exc:
            msg = str(exc.reason)
            log.warning("check_blockchain(urllib): %s", msg)
            return {"ok": False, "block_number": 0, "message": msg}
        except Exception as exc:
            msg = str(exc)
            log.warning("check_blockchain(urllib): %s", msg)
            return {"ok": False, "block_number": 0, "message": msg}

    def _parse_block_response(self, data: dict) -> dict:
        hex_block = data.get("result")
        if hex_block is None:
            error = data.get("error", {}).get("message", "no result field")
            log.warning("check_blockchain: %s", error)
            return {"ok": False, "block_number": 0, "message": error}
        block_number = int(hex_block, 16)
        msg = f"block #{block_number:,}"
        log.debug("check_blockchain: %s", msg)
        return {"ok": True, "block_number": block_number, "message": msg}

    # -------------------------------------------------------------------------
    # Formatting
    # -------------------------------------------------------------------------

    def format_report(self, result: dict) -> str:
        """Format a check_all() result as a human-readable Discord message (plain text)."""
        checks = result.get("checks", {})
        lines = ["🏥 **Health Check**"]

        disk = checks.get("disk", {})
        icon = "✅" if disk.get("ok") else "❌"
        lines.append(f"{icon} Disk: {disk.get('message', 'unknown')}")

        for key, info in checks.items():
            if not key.startswith("llm_"):
                continue
            tier_label = key[4:].replace("_", " ").title()
            icon = "✅" if info.get("ok") else "❌"
            msg = info.get("message", "unknown")
            if info.get("ok"):
                lines.append(f"{icon} {tier_label} LLM: {msg}")
            else:
                lines.append(f"{icon} {tier_label} LLM: unreachable ({msg})")

        chain = checks.get("blockchain", {})
        icon = "✅" if chain.get("ok") else "❌"
        lines.append(f"{icon} Blockchain: {chain.get('message', 'unknown')}")

        overall = result.get("healthy", False)
        lines.append(f"\nOverall: **{'healthy' if overall else 'unhealthy'}**")

        return "\n".join(lines)
