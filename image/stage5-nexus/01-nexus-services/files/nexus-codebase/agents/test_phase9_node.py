#!/usr/bin/env python3
"""Phase 9 — unit tests for node_agent.py.

All WS connections, psutil calls, and aiohttp calls are mocked so these
tests run on nexus-admin without any real Gateway or node hardware.
"""

import argparse
import asyncio
import json
import logging
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

import aiohttp
import psutil

import node_agent
from node_agent import (
    NodeAgent,
    _detect_models,
    _live_resources,
    _static_resources,
)
from gateway_protocol import (
    MSG_NODE_COMMAND,
    MSG_NODE_HEARTBEAT,
    MSG_NODE_REGISTER,
    MSG_NODE_REGISTERED,
    MSG_NODE_RESPONSE,
    make_message,
)

logging.disable(logging.CRITICAL)


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _make_cfg(**overrides) -> argparse.Namespace:
    defaults = dict(
        gateway_url="ws://localhost:8766",
        auth_token="test-token",
        hostname="test-node",
        wallet="0xDeaDbeefdEAdbeefdEadbEEFdeadbeEFdEaDbeeF",
        capabilities="compute,validator",
        heartbeat_interval=30,
        log_level="WARNING",
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _make_agent(**overrides) -> NodeAgent:
    return NodeAgent(_make_cfg(**overrides))


def _make_session_mock(url_responses: dict) -> MagicMock:
    """
    Build a mock aiohttp.ClientSession whose .get(url) returns different
    responses per URL substring.

    url_responses: {substring: response_dict | Exception instance}
    A response_dict means HTTP 200 with that JSON body.
    An Exception instance means __aenter__ raises it (simulates connection error).
    """
    def get_cm(url):
        cm = MagicMock()
        for key, value in url_responses.items():
            if key in url:
                if isinstance(value, Exception):
                    cm.__aenter__ = AsyncMock(side_effect=value)
                else:
                    resp = AsyncMock()
                    resp.status = 200
                    resp.json = AsyncMock(return_value=value)
                    cm.__aenter__ = AsyncMock(return_value=resp)
                cm.__aexit__ = AsyncMock(return_value=False)
                return cm
        # Default: connection refused
        cm.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("refused"))
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.get = MagicMock(side_effect=get_cm)
    return session


# ── 1. Resource detection ──────────────────────────────────────────────────────

class TestResourceDetection(unittest.TestCase):

    def test_resource_detection(self):
        """_static_resources() returns correct keys derived from psutil values."""
        mem_mock = MagicMock()
        mem_mock.total = 8 * 1024 ** 3   # 8 GB

        disk_mock = MagicMock()
        disk_mock.total = 64 * 1024 ** 3  # 64 GB

        with patch("node_agent.psutil.cpu_count",       return_value=4), \
             patch("node_agent.psutil.virtual_memory",  return_value=mem_mock), \
             patch("node_agent.psutil.disk_usage",      return_value=disk_mock):
            res = _static_resources()

        self.assertEqual(res["cpu_cores"],  4)
        self.assertAlmostEqual(res["memory_gb"],  8.0)
        self.assertAlmostEqual(res["storage_gb"], 64.0)
        self.assertIsNone(res["ai_tops"])


# ── 2-4. Model detection ───────────────────────────────────────────────────────

class TestModelDetection(unittest.IsolatedAsyncioTestCase):

    async def test_model_detection_ollama(self):
        """Ollama /api/tags response → model list with type='ollama'."""
        session = _make_session_mock({
            "11434": {"models": [{"name": "llama3.2:latest"}, {"name": "mistral:7b"}]},
            "1234":  aiohttp.ClientError("refused"),
        })
        with patch("node_agent.aiohttp.ClientSession", return_value=session):
            models = await _detect_models()

        self.assertEqual(len(models), 2)
        names = [m["name"] for m in models]
        self.assertIn("llama3.2:latest", names)
        self.assertIn("mistral:7b",      names)
        for m in models:
            self.assertEqual(m["type"],     "ollama")
            self.assertEqual(m["endpoint"], "http://localhost:11434")

    async def test_model_detection_lm_studio(self):
        """LM Studio /v1/models response → model list with type='lmstudio'."""
        session = _make_session_mock({
            "1234":  {"data": [{"id": "smollm2-1.7b"}, {"id": "phi-3.5-mini"}]},
            "11434": aiohttp.ClientError("refused"),
        })
        with patch("node_agent.aiohttp.ClientSession", return_value=session):
            models = await _detect_models()

        self.assertEqual(len(models), 2)
        names = [m["name"] for m in models]
        self.assertIn("smollm2-1.7b",  names)
        self.assertIn("phi-3.5-mini",  names)
        for m in models:
            self.assertEqual(m["type"],     "lmstudio")
            self.assertEqual(m["endpoint"], "http://localhost:1234")

    async def test_model_detection_none(self):
        """Both endpoints unavailable → empty list with no exception raised."""
        session = _make_session_mock({
            "1234":  aiohttp.ClientError("refused"),
            "11434": aiohttp.ClientError("refused"),
        })
        with patch("node_agent.aiohttp.ClientSession", return_value=session):
            models = await _detect_models()

        self.assertEqual(models, [])


# ── 5-6. Message format ────────────────────────────────────────────────────────

class TestMessageFormats(unittest.TestCase):

    def test_register_message_format(self):
        """node_register wire message has type, timestamp, and all payload fields."""
        payload = {
            "auth_token":     "tok",
            "hostname":       "nexus-master",
            "wallet_address": "0xDeadBeef",
            "capabilities":   ["compute", "validator"],
            "models":         [],
            "resources":      {
                "cpu_cores":  4,
                "memory_gb":  8.0,
                "storage_gb": 64.0,
                "ai_tops":    None,
            },
        }
        msg = make_message(MSG_NODE_REGISTER, payload)

        self.assertEqual(msg["type"], "node_register")
        self.assertIn("timestamp", msg)

        p = msg["payload"]
        self.assertEqual(p["hostname"],       "nexus-master")
        self.assertEqual(p["wallet_address"], "0xDeadBeef")
        self.assertIsInstance(p["capabilities"], list)
        self.assertIsInstance(p["models"],       list)
        self.assertIsInstance(p["resources"],    dict)

        r = p["resources"]
        for key in ("cpu_cores", "memory_gb", "storage_gb"):
            self.assertIn(key, r)

    def test_heartbeat_message_format(self):
        """node_heartbeat payload carries all required utilisation fields."""
        mem_mock = MagicMock(); mem_mock.percent = 55.0
        disk_mock = MagicMock(); disk_mock.percent = 30.0

        with patch("node_agent.psutil.cpu_percent",    return_value=12.5), \
             patch("node_agent.psutil.virtual_memory", return_value=mem_mock), \
             patch("node_agent.psutil.disk_usage",     return_value=disk_mock), \
             patch("node_agent.time.time",
                   return_value=node_agent._BOOT_TIME + 3600):
            live = _live_resources()

        msg = make_message(MSG_NODE_HEARTBEAT, {**live, "active_tasks": 2})
        self.assertEqual(msg["type"], "node_heartbeat")

        p = msg["payload"]
        for key in ("cpu_percent", "memory_percent", "disk_percent",
                    "gpu_percent", "uptime_seconds", "active_tasks"):
            self.assertIn(key, p, f"Missing field: {key}")

        self.assertAlmostEqual(p["cpu_percent"],    12.5)
        self.assertAlmostEqual(p["memory_percent"], 55.0)
        self.assertAlmostEqual(p["disk_percent"],   30.0)
        self.assertIsNone(p["gpu_percent"])
        self.assertEqual(p["uptime_seconds"], 3600)
        self.assertEqual(p["active_tasks"],   2)


# ── 7-8. Command dispatch ──────────────────────────────────────────────────────

class TestCommandDispatch(unittest.IsolatedAsyncioTestCase):

    def _cmd(self, command: str, request_id: str = "req-001") -> dict:
        return make_message(MSG_NODE_COMMAND, {
            "command":    command,
            "args":       {},
            "request_id": request_id,
        })

    def _agent_with_ws(self):
        """Return (agent, captured_sends_list)."""
        agent = _make_agent()
        sent = []
        ws = AsyncMock()
        ws.send = AsyncMock(side_effect=lambda data: sent.append(json.loads(data)))
        agent._ws = ws
        return agent, sent

    async def test_command_dispatch_health(self):
        """health command → status=ok with comprehensive nested structure."""
        agent, sent = self._agent_with_ws()

        # Stub _health_command directly so test is independent of psutil/ports
        fake_health = {
            "status": "ok",
            "result": {
                "hostname": "test-node", "wallet_address": "0xDEAD",
                "uptime_seconds": 7200,
                "cpu":     {"cores": 4, "percent": 22.0, "load_avg": [0.5, 0.4, 0.3]},
                "memory":  {"total_gb": 8.0, "used_gb": 3.5, "percent": 43.7},
                "disk":    {"total_gb": 64.0, "used_gb": 20.0, "percent": 31.2, "mount": "/"},
                "gpu":     {"available": False, "percent": None},
                "network": {"bytes_sent": 1000, "bytes_recv": 2000},
                "services": {"ipfs": True, "ollama": False, "lm_studio": False,
                             "geth": False, "k3s": False},
            },
        }
        with patch.object(agent, "_health_command", AsyncMock(return_value=fake_health)):
            await agent._handle_command(self._cmd("health", "req-hlt"))

        self.assertEqual(len(sent), 1)
        resp = sent[0]
        self.assertEqual(resp["type"],                  "node_response")
        self.assertEqual(resp["payload"]["status"],     "ok")
        self.assertEqual(resp["payload"]["request_id"], "req-hlt")

        result = resp["payload"]["result"]
        for key in ("hostname", "uptime_seconds", "cpu", "memory",
                    "disk", "gpu", "network", "services"):
            self.assertIn(key, result)
        self.assertEqual(result["disk"]["mount"], "/")
        self.assertIn("ipfs", result["services"])

    async def test_command_dispatch_unimplemented(self):
        """Unknown commands → status=error with 'not implemented' message."""
        agent, sent = self._agent_with_ws()

        # "ping" is not a recognised command
        await agent._handle_command(self._cmd("ping", "req-ping"))

        self.assertEqual(len(sent), 1)
        resp = sent[0]
        self.assertEqual(resp["type"],              "node_response")
        self.assertEqual(resp["payload"]["status"], "error")
        self.assertEqual(resp["payload"]["request_id"], "req-ping")
        self.assertIn("not implemented",
                      resp["payload"]["result"]["message"])


# ── 9. Reconnect backoff ───────────────────────────────────────────────────────

class TestReconnectBackoff(unittest.IsolatedAsyncioTestCase):

    async def test_reconnect_backoff(self):
        """Backoff doubles on each connection failure: 1 → 2 → 4 → 8, capped at 60."""
        agent = _make_agent()
        attempt = [0]
        captured_timeouts = []

        async def failing_connect():
            attempt[0] += 1
            if attempt[0] >= 5:
                # Clean exit on 5th attempt — triggers backoff reset + loop exit
                agent._shutdown.set()
                return
            raise ConnectionRefusedError("refused")

        async def instant_wait_for(coro, timeout=None):
            # Record the requested timeout and immediately time out.
            # asyncio.shield is also patched (below) so coro is just asyncio.sleep(0);
            # close it to avoid "never awaited" warnings.
            captured_timeouts.append(timeout)
            if hasattr(coro, "close"):
                coro.close()
            raise asyncio.TimeoutError()

        def _shield_close(coro):
            coro.close()           # prevent "never awaited" warning
            return asyncio.sleep(0)

        with patch.object(agent, "_connect_and_run", failing_connect), \
             patch("node_agent.asyncio.wait_for",  instant_wait_for), \
             patch("node_agent.asyncio.shield",    side_effect=_shield_close):
            await agent.run()

        # 4 failed attempts → 4 wait calls with timeouts 1, 2, 4, 8
        self.assertEqual(len(captured_timeouts), 4,
                         f"Expected 4 backoff waits, got: {captured_timeouts}")
        self.assertEqual(captured_timeouts, [1, 2, 4, 8])

    async def test_backoff_capped_at_60(self):
        """Backoff never exceeds 60 seconds regardless of failure count."""
        agent = _make_agent()
        attempt = [0]
        captured_timeouts = []

        async def failing_connect():
            attempt[0] += 1
            if attempt[0] >= 10:
                agent._shutdown.set()
                return
            raise ConnectionRefusedError("refused")

        async def instant_wait_for(coro, timeout=None):
            captured_timeouts.append(timeout)
            if hasattr(coro, "close"):
                coro.close()
            raise asyncio.TimeoutError()

        def _shield_close(coro):
            coro.close()
            return asyncio.sleep(0)

        with patch.object(agent, "_connect_and_run", failing_connect), \
             patch("node_agent.asyncio.wait_for",  instant_wait_for), \
             patch("node_agent.asyncio.shield",    side_effect=_shield_close):
            await agent.run()

        self.assertTrue(all(t <= 60 for t in captured_timeouts),
                        f"Backoff exceeded 60s: {captured_timeouts}")
        # After enough failures the value should have plateaued at 60
        self.assertIn(60, captured_timeouts)


# ── 10. Graceful shutdown ──────────────────────────────────────────────────────

class TestGracefulShutdown(unittest.IsolatedAsyncioTestCase):

    async def test_graceful_shutdown_pre_set(self):
        """run() exits immediately without connecting when shutdown is pre-set."""
        agent = _make_agent()
        agent.request_shutdown()
        self.assertTrue(agent._shutdown.is_set())

        connect_called = [False]

        async def mock_connect():
            connect_called[0] = True

        with patch.object(agent, "_connect_and_run", mock_connect):
            await agent.run()

        self.assertFalse(connect_called[0],
                         "_connect_and_run must not be called after shutdown is set")

    async def test_graceful_shutdown_during_backoff(self):
        """Shutdown event fired during reconnect wait causes run() to exit cleanly."""
        agent = _make_agent()
        attempt = [0]

        async def fail_once():
            attempt[0] += 1
            raise ConnectionRefusedError("refused")

        async def wait_then_shutdown(coro, timeout=None):
            # Simulate shutdown event firing while we're waiting to reconnect
            agent._shutdown.set()
            if hasattr(coro, "close"):
                coro.close()
            return None  # No TimeoutError — shutdown woke us up cleanly

        def _shield_close(coro):
            coro.close()
            return asyncio.sleep(0)

        with patch.object(agent, "_connect_and_run", fail_once), \
             patch("node_agent.asyncio.wait_for",  wait_then_shutdown), \
             patch("node_agent.asyncio.shield",    side_effect=_shield_close):
            await agent.run()

        # Exactly one connection attempt before shutdown halted the loop
        self.assertEqual(attempt[0], 1)

    async def test_request_shutdown_sets_event(self):
        """request_shutdown() sets the internal Event that controls the run loop."""
        agent = _make_agent()
        self.assertFalse(agent._shutdown.is_set())
        agent.request_shutdown()
        self.assertTrue(agent._shutdown.is_set())


if __name__ == "__main__":
    unittest.main()
