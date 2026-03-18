#!/usr/bin/env python3
"""
NEXUS OS 3-Tier LLM Router
Routes agent requests to the appropriate inference endpoint based on
agent tier and task type.

Tier 1: Coordinator (ThinkStation:1234) — Qwen3.5-35B-A3B
Tier 2A: Coder (ThinkPad:1234) — qwen2.5-coder-14b-instruct
Tier 2B: Director (ThinkStation:1234) — Qwen2.5-7B-Instruct (shared port, model-routed)
Tier 3: Worker (AI HAT+ or fallback to ThinkStation:1234)

Usage:
    from llm_router_v2 import LLMRouter
    router = LLMRouter()
    response = await router.generate("ceo", messages, task_type="planning")
"""

import asyncio
import re
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

try:
    import aiohttp
except ImportError:
    aiohttp = None

try:
    import httpx
except ImportError:
    httpx = None

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [llm-router] %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

@dataclass
class TierConfig:
    """Configuration for a single LLM tier."""
    name: str
    endpoint: str
    model: str
    max_tokens: int = 1024
    temperature: float = 0.7
    timeout: int = 120
    fallback_endpoint: Optional[str] = None
    fallback_model: Optional[str] = None
    agents: list = field(default_factory=list)
    task_types: list = field(default_factory=list)


# ── Endpoint addresses ──
# Update these if IPs or ports change
THINKSTATION_PRIMARY = "http://10.0.30.3:1234"    # Qwen3.5-35B-A3B
THINKSTATION_SECONDARY = "http://10.0.30.3:1234"  # Qwen2.5-7B-Instruct (same LM Studio, model-routed)
THINKPAD = "http://10.0.30.2:1234"                # qwen2.5-coder-14b
AI_HAT = "http://10.0.20.6:11434"                 # nexus-ai2 Hailo-10H (Ollama)

# WireGuard alternatives (if VLAN routing not configured)
WG_THINKSTATION_PRIMARY = "http://10.1.0.5:1234"
WG_THINKSTATION_SECONDARY = "http://10.1.0.5:1234"
WG_THINKPAD = "http://10.1.0.5:1234"  # ThinkPad doesn't have WG yet, update if added


TIERS = {
    "coordinator": TierConfig(
        name="coordinator",
        endpoint=f"{THINKSTATION_PRIMARY}/v1/chat/completions",
        model="qwen/qwen3.5-35b-a3b",  # Confirmed LM Studio identifier
        max_tokens=4096,
        temperature=0.6,
        timeout=600,  # 10 min — this model is slow
        fallback_endpoint=f"{THINKSTATION_SECONDARY}/v1/chat/completions",
        fallback_model="qwen2.5-7b-instruct-1m",
        agents=["ceo"],
        task_types=["planning", "task_decomp", "code_review", "strategy"],
    ),

    "coder": TierConfig(
        name="coder",
        endpoint=f"{THINKPAD}/v1/chat/completions",
        model="qwen/qwen2.5-coder-14b",  # Confirmed LM Studio identifier
        max_tokens=2048,
        temperature=0.2,
        timeout=300,
        fallback_endpoint=f"{THINKSTATION_PRIMARY}/v1/chat/completions",
        fallback_model="qwen/qwen3.5-35b-a3b",
        agents=[],  # Not agent-based — used by task type
        task_types=["code_gen", "agent_v2", "debugging", "patch_create"],
    ),

    "director": TierConfig(
        name="director",
        endpoint=f"{THINKSTATION_SECONDARY}/v1/chat/completions",
        model="qwen2.5-7b-instruct-1m",  # Confirmed LM Studio identifier
        max_tokens=1024,
        temperature=0.7,
        timeout=120,
        fallback_endpoint=f"{THINKSTATION_PRIMARY}/v1/chat/completions",
        fallback_model="qwen/qwen3.5-35b-a3b",
        agents=[
            "coo",
            "compute_director", "storage_director", "network_director",
            "security_director", "blockchain_director", "ml_director",
            "quantum_director",
        ],
        task_types=["department_decision", "resource_allocation", "escalation"],
    ),

    "worker": TierConfig(
        name="worker",
        endpoint=f"{AI_HAT}/v1/chat/completions",
        model="llama3.2:1b",
        max_tokens=512,
        temperature=0.3,
        timeout=120,  # Pi 5 CPU inference is slower than GPU; 1B takes ~5s cold start
        fallback_endpoint=f"{THINKSTATION_SECONDARY}/v1/chat/completions",
        fallback_model="qwen2.5-7b-instruct-1m",
        agents=[
            "process_scheduler", "load_balancer", "resource_monitor",
            "backup_agent", "cache_manager", "flock_federator",
            "mesh_coordinator", "vpn_manager", "dns_agent",
            "auth_agent", "anomaly_detector", "audit_logger",
            "contract_deployer", "token_manager", "consensus_monitor",
            "training_coordinator", "inference_server", "dataset_manager",
            "qaoa_optimizer", "circuit_builder", "noise_analyzer",
        ],
        task_types=["worker_task", "status_report", "simple_json"],
    ),
}


# ═══════════════════════════════════════════════════════════════════
# THINKING TOKEN HANDLING
# ═══════════════════════════════════════════════════════════════════

_THINK_PATTERN = re.compile(r'<think>.*?</think>', re.DOTALL)
_THINK_OPEN = re.compile(r'<think>.*', re.DOTALL)  # Unclosed think block


def strip_thinking_tokens(text: str) -> str:
    """
    Remove <think>...</think> blocks from model output.
    Handles both complete and unclosed think blocks.
    Defense-in-depth — LM Studio stop sequences should catch most cases.
    """
    if not text:
        return text
    # Remove complete think blocks
    cleaned = _THINK_PATTERN.sub('', text)
    # Remove unclosed think blocks (model started thinking but was stopped)
    cleaned = _THINK_OPEN.sub('', cleaned)
    return cleaned.strip()


# ═══════════════════════════════════════════════════════════════════
# ROUTER CLASS
# ═══════════════════════════════════════════════════════════════════

class LLMRouter:
    """
    Routes LLM requests to the appropriate tier based on agent ID and task type.
    Supports health checking, fallback, and response post-processing.
    """

    def __init__(self):
        self._health_cache: dict[str, tuple[bool, float]] = {}
        self._health_ttl = 30.0  # Cache health checks for 30 seconds
        self._build_agent_index()

    def _build_agent_index(self):
        """Build reverse index: agent_id → tier_name."""
        self._agent_to_tier: dict[str, str] = {}
        self._task_to_tier: dict[str, str] = {}

        for tier_name, config in TIERS.items():
            for agent_id in config.agents:
                self._agent_to_tier[agent_id] = tier_name
            for task_type in config.task_types:
                self._task_to_tier[task_type] = tier_name

    def select_tier(
        self,
        agent_id: Optional[str] = None,
        task_type: Optional[str] = None,
    ) -> TierConfig:
        """
        Select the appropriate LLM tier.

        Priority: task_type > agent_id > default (director)
        This lets you override the agent's default tier for specific task types.
        """
        # Task type takes priority (e.g., CEO doing code_gen → coder tier)
        if task_type and task_type in self._task_to_tier:
            tier_name = self._task_to_tier[task_type]
            log.debug(f"Routed by task_type={task_type} → {tier_name}")
            return TIERS[tier_name]

        # Then check local index (built from role-based IDs in TIERS config)
        if agent_id and agent_id in self._agent_to_tier:
            tier_name = self._agent_to_tier[agent_id]
            log.debug(f"Routed by agent_id={agent_id} → {tier_name}")
            return TIERS[tier_name]

        # Try agent_registry as authoritative source (handles numbered IDs like
        # compute_worker_1, storage_worker_2, etc. absent from TIERS.agents lists)
        if agent_id:
            try:
                from agent_registry import get_agent  # lazy — avoid circular imports
                cfg = get_agent(agent_id)
                tier_name = cfg.get("tier")
                if tier_name and tier_name in TIERS:
                    log.debug(f"Routed by registry agent_id={agent_id} → {tier_name}")
                    return TIERS[tier_name]
            except (ValueError, ImportError):
                pass

        # Default fallback — warning so unmapped IDs surface in logs
        log.warning(
            f"No tier mapping for agent={agent_id} task={task_type}, defaulting to director"
        )
        return TIERS["director"]

    async def check_health(self, endpoint: str) -> bool:
        """
        Check if an LLM endpoint is responsive.
        Results are cached for _health_ttl seconds.
        """
        now = time.monotonic()
        if endpoint in self._health_cache:
            healthy, checked_at = self._health_cache[endpoint]
            if now - checked_at < self._health_ttl:
                return healthy

        models_url = endpoint.replace("/chat/completions", "/models")
        healthy = False

        try:
            if aiohttp:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        models_url,
                        timeout=aiohttp.ClientTimeout(total=5)
                    ) as resp:
                        healthy = resp.status == 200
            elif httpx:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(models_url, timeout=5.0)
                    healthy = resp.status_code == 200
            else:
                log.warning("Neither aiohttp nor httpx available for health check")
                healthy = True  # Assume healthy if we can't check
        except Exception as e:
            log.warning(f"Health check failed for {endpoint}: {e}")
            healthy = False

        self._health_cache[endpoint] = (healthy, now)
        return healthy

    async def generate(
        self,
        agent_id: str,
        messages: list[dict],
        task_type: Optional[str] = None,
        override_model: Optional[str] = None,
        override_endpoint: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """
        Generate a response from the appropriate LLM tier.

        Args:
            agent_id: The agent making the request (e.g., "ceo", "compute_director")
            messages: OpenAI-format messages list
            task_type: Optional task type to override agent-based routing
            override_model: Force a specific model name
            override_endpoint: Force a specific endpoint URL
            **kwargs: Additional params passed to the API (temperature, etc.)

        Returns:
            dict with keys: content, model, tier, endpoint, tokens, latency_ms, error
        """
        tier = self.select_tier(agent_id, task_type)
        endpoint = override_endpoint or tier.endpoint
        model = override_model or tier.model

        # Health check primary endpoint
        primary_healthy = await self.check_health(endpoint)
        used_fallback = False

        if not primary_healthy and tier.fallback_endpoint:
            log.warning(
                f"Primary endpoint unhealthy ({endpoint}), "
                f"falling back to {tier.fallback_endpoint}"
            )
            endpoint = tier.fallback_endpoint
            model = tier.fallback_model or model
            used_fallback = True

            # Check fallback health too
            fallback_healthy = await self.check_health(endpoint)
            if not fallback_healthy:
                return {
                    "content": None,
                    "model": model,
                    "tier": tier.name,
                    "endpoint": endpoint,
                    "tokens": 0,
                    "latency_ms": 0,
                    "error": f"All endpoints unhealthy for tier {tier.name}",
                    "used_fallback": True,
                }

        # Build request payload
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", tier.max_tokens),
            "temperature": kwargs.get("temperature", tier.temperature),
            "stop": kwargs.get("stop", ["<think>", "</think>"]),  # Default stop sequences
        }

        # Make the request
        start_time = time.monotonic()
        try:
            content, tokens = await self._call_api(endpoint, payload, tier.timeout)
            latency_ms = (time.monotonic() - start_time) * 1000

            # Post-process: strip thinking tokens (defense-in-depth)
            if content:
                content = strip_thinking_tokens(content)

            log.info(
                f"[{tier.name}] agent={agent_id} model={model} "
                f"tokens={tokens} latency={latency_ms:.0f}ms "
                f"fallback={used_fallback}"
            )

            return {
                "content": content,
                "model": model,
                "tier": tier.name,
                "endpoint": endpoint,
                "tokens": tokens,
                "latency_ms": round(latency_ms, 1),
                "error": None,
                "used_fallback": used_fallback,
            }

        except Exception as e:
            latency_ms = (time.monotonic() - start_time) * 1000
            log.error(f"[{tier.name}] agent={agent_id} error: {e}")
            return {
                "content": None,
                "model": model,
                "tier": tier.name,
                "endpoint": endpoint,
                "tokens": 0,
                "latency_ms": round(latency_ms, 1),
                "error": str(e),
                "used_fallback": used_fallback,
            }

    async def _call_api(
        self,
        endpoint: str,
        payload: dict,
        timeout: int,
    ) -> tuple[str, int]:
        """
        Make the actual API call. Returns (content, token_count).
        Supports both aiohttp and httpx.
        """
        headers = {"Content-Type": "application/json"}

        if aiohttp:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise RuntimeError(
                            f"API returned {resp.status}: {body[:500]}"
                        )
                    data = await resp.json()

        elif httpx:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                )
                if resp.status_code != 200:
                    raise RuntimeError(
                        f"API returned {resp.status_code}: {resp.text[:500]}"
                    )
                data = resp.json()
        else:
            raise RuntimeError("Neither aiohttp nor httpx installed")

        # Parse OpenAI-compatible response
        content = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("total_tokens", 0)
        return content, tokens

    def get_status(self) -> dict:
        """Return current router status for diagnostics."""
        status = {}
        for tier_name, config in TIERS.items():
            cached = self._health_cache.get(config.endpoint)
            status[tier_name] = {
                "endpoint": config.endpoint,
                "model": config.model,
                "healthy": cached[0] if cached else "unknown",
                "agent_count": len(config.agents),
            }
        return status


# ═══════════════════════════════════════════════════════════════════
# CLI DIAGNOSTICS
# ═══════════════════════════════════════════════════════════════════

async def diagnose():
    """Run health checks on all tiers and print status."""
    router = LLMRouter()
    print("NEXUS OS LLM Router — Diagnostics")
    print("=" * 60)

    for tier_name, config in TIERS.items():
        healthy = await router.check_health(config.endpoint)
        fb_healthy = None
        if config.fallback_endpoint:
            fb_healthy = await router.check_health(config.fallback_endpoint)

        status = "✅ UP" if healthy else "❌ DOWN"
        fb_status = ""
        if fb_healthy is not None:
            fb_status = f" | fallback: {'✅' if fb_healthy else '❌'}"

        print(f"  [{tier_name:12}] {status} — {config.model}")
        print(f"                  {config.endpoint}{fb_status}")
        print(f"                  agents: {len(config.agents)} | "
              f"timeout: {config.timeout}s")
        print()

    # Test routing
    print("Routing tests:")
    test_cases = [
        ("ceo", None, "coordinator"),
        ("coo", None, "director"),
        ("compute_director", None, "director"),
        ("process_scheduler", None, "worker"),
        ("ceo", "code_gen", "coder"),  # task_type overrides agent
        (None, "planning", "coordinator"),
        ("unknown_agent", None, "director"),  # fallback
    ]
    for agent_id, task_type, expected in test_cases:
        tier = router.select_tier(agent_id, task_type)
        match = "✅" if tier.name == expected else "❌"
        print(f"  {match} agent={agent_id or 'None':20} "
              f"task={task_type or 'None':15} → {tier.name}")


if __name__ == "__main__":
    asyncio.run(diagnose())
