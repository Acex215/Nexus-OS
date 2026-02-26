"""NEXUS OS Shared LLM Client — local inference + HuggingFace API fallback.

Provides rate-limited, model-aware LLM access for all 30 agents.
Worker agents try local llama-server on nexus-ai first (SmolLM2-1.7B),
falling back to HuggingFace API if local is unavailable.
CEO/COO and Directors always use HuggingFace API.
"""
import asyncio
import aiohttp
import time
import os
import logging
from typing import List, Dict, Optional
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Local inference endpoint (llama-server on nexus-ai)
LOCAL_INFERENCE_URL = "http://192.168.8.128:8090/v1/chat/completions"
LOCAL_TIMEOUT = 30  # seconds — local inference can be slow on CPU
LOCAL_MODEL_NAME = "local/SmolLM2-1.7B"

# Roles eligible for local inference
LOCAL_ELIGIBLE_ROLES = {"default", "worker"}


class InferenceMetrics:
    """Track local vs API usage statistics."""

    def __init__(self):
        self.local_requests = 0
        self.local_successes = 0
        self.api_requests = 0
        self.api_fallbacks = 0
        self.local_total_latency = 0.0

    @property
    def local_avg_latency_ms(self) -> float:
        if self.local_successes == 0:
            return 0.0
        return (self.local_total_latency / self.local_successes) * 1000

    def summary(self) -> dict:
        return {
            "local_requests": self.local_requests,
            "local_successes": self.local_successes,
            "api_requests": self.api_requests,
            "api_fallbacks": self.api_fallbacks,
            "local_avg_latency_ms": round(self.local_avg_latency_ms, 1),
        }


class RateLimiter:
    """Token-bucket rate limiter for HuggingFace API.

    Args:
        rate: Requests per minute (default 28 for free tier).
        burst: Maximum burst capacity (default 5).
    """

    def __init__(self, rate: int = 28, burst: int = 5):
        self.rate = rate
        self.tokens = float(burst)
        self.max_tokens = float(burst)
        self.last_update = time.monotonic()
        self._lock: Optional[asyncio.Lock] = None

    @property
    def lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def acquire(self):
        """Block until a request token is available."""
        async with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.tokens = min(
                self.max_tokens,
                self.tokens + elapsed * (self.rate / 60.0),
            )
            self.last_update = now

            if self.tokens < 1.0:
                wait_time = (1.0 - self.tokens) * (60.0 / self.rate)
                logger.debug("Rate limit: waiting %.2fs", wait_time)
                await asyncio.sleep(wait_time)
                self.tokens = 0.0
                self.last_update = time.monotonic()
            else:
                self.tokens -= 1.0


class NexusLLMClient:
    """Shared async LLM client for all NEXUS OS agents.

    Worker agents try local llama-server first, falling back to
    HuggingFace API. Directors and C-suite always use the API.

    Args:
        api_key: HuggingFace API key.
        rate_limit: Max requests per minute.
        local_url: Local inference endpoint URL.
    """

    API_URL = "https://router.huggingface.co/v1/chat/completions"

    MODEL_MAP = {
        "ceo": "Qwen/Qwen2.5-7B-Instruct",
        "coo": "Qwen/Qwen2.5-7B-Instruct",
        "director": "meta-llama/Llama-3.2-3B-Instruct",
        "default": "meta-llama/Llama-3.2-1B-Instruct",
    }

    def __init__(self, api_key: str, rate_limit: int = 28,
                 local_url: str = LOCAL_INFERENCE_URL):
        self.api_key = api_key
        self.rate_limiter = RateLimiter(rate=rate_limit)
        self.local_url = local_url
        self.metrics = InferenceMetrics()
        self._session: Optional[aiohttp.ClientSession] = None
        self._local_session: Optional[aiohttp.ClientSession] = None
        self._local_available: Optional[bool] = None
        self._local_check_time = 0.0

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=60)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def _ensure_local_session(self):
        if self._local_session is None or self._local_session.closed:
            timeout = aiohttp.ClientTimeout(total=LOCAL_TIMEOUT)
            self._local_session = aiohttp.ClientSession(timeout=timeout)

    def _is_local_eligible(self, agent_role: str) -> bool:
        """Check if this role should try local inference first."""
        if agent_role in LOCAL_ELIGIBLE_ROLES:
            return True
        if "worker" in agent_role:
            return True
        return False

    async def _check_local_health(self) -> bool:
        """Check if local inference is reachable. Cached for 60 seconds."""
        now = time.monotonic()
        if self._local_available is not None and (now - self._local_check_time) < 60:
            return self._local_available

        await self._ensure_local_session()
        try:
            health_url = self.local_url.rsplit("/v1/", 1)[0] + "/health"
            async with self._local_session.get(health_url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                self._local_available = resp.status == 200
        except Exception:
            self._local_available = False

        self._local_check_time = now
        if self._local_available:
            logger.debug("Local inference: available")
        else:
            logger.debug("Local inference: unavailable")
        return self._local_available

    async def _try_local_inference(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> Optional[str]:
        """Attempt local inference. Returns response text or None on failure."""
        await self._ensure_local_session()
        self.metrics.local_requests += 1

        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        start = time.monotonic()
        try:
            async with self._local_session.post(
                self.local_url, json=payload,
                headers={"Content-Type": "application/json"},
            ) as resp:
                if resp.status != 200:
                    logger.warning("Local inference returned %d", resp.status)
                    return None

                data = await resp.json()
                latency = time.monotonic() - start
                response_text = data["choices"][0]["message"]["content"]

                self.metrics.local_successes += 1
                self.metrics.local_total_latency += latency

                logger.info(
                    "LLM ok: role=worker model=%s latency=%.2fs len=%d (local)",
                    LOCAL_MODEL_NAME, latency, len(response_text),
                )
                return response_text

        except (aiohttp.ClientError, asyncio.TimeoutError, KeyError) as exc:
            latency = time.monotonic() - start
            logger.warning(
                "Local inference failed after %.1fs: %s", latency, exc,
            )
            # Mark as unavailable to skip health check for next 60s
            self._local_available = False
            self._local_check_time = time.monotonic()
            return None

    def _select_model(self, agent_role: str) -> str:
        """Select model by agent_id or role name.

        Checks agent_id first (e.g. "ceo"), then role keywords
        ("director", "worker"), then falls back to default.
        """
        if agent_role in self.MODEL_MAP:
            return self.MODEL_MAP[agent_role]
        # Check if the role string contains a known tier
        if "director" in agent_role:
            return self.MODEL_MAP["director"]
        return self.MODEL_MAP["default"]

    async def chat_completion(
        self,
        agent_role: str,
        messages: List[Dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> str:
        """Send a chat completion request.

        For worker roles, tries local inference first, falling back to
        HuggingFace API. Other roles go directly to the API.

        Args:
            agent_role: Agent role key (ceo, coo, director, worker, or agent_id).
            messages: OpenAI-style message list.
            max_tokens: Max response tokens.
            temperature: Sampling temperature.

        Returns:
            The assistant's response text.

        Raises:
            ValueError: If the API key is invalid (401).
            aiohttp.ClientResponseError: On unrecoverable HTTP errors.
            Exception: After max retries exhausted.
        """
        # Try local inference for eligible roles
        if self._is_local_eligible(agent_role):
            if await self._check_local_health():
                result = await self._try_local_inference(
                    messages, max_tokens, temperature,
                )
                if result is not None:
                    return result

                # Local failed — fall through to API
                self.metrics.api_fallbacks += 1
                logger.info(
                    "Falling back to API for role=%s", agent_role,
                )

        # HuggingFace API path
        await self._ensure_session()
        await self.rate_limiter.acquire()
        self.metrics.api_requests += 1

        model = self._select_model(agent_role)
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        start = time.monotonic()

        for attempt in range(3):
            try:
                async with self._session.post(
                    self.API_URL, json=payload, headers=headers
                ) as resp:
                    if resp.status == 401:
                        body = await resp.text()
                        raise ValueError(
                            f"Invalid HuggingFace API key (401): {body[:200]}"
                        )

                    if resp.status == 503:
                        if attempt < 2:
                            logger.warning(
                                "Model %s loading (503), waiting 20s (attempt %d/3)",
                                model, attempt + 1,
                            )
                            await asyncio.sleep(20)
                            await self.rate_limiter.acquire()
                            continue
                        raise Exception(
                            f"Model {model} failed to load after 3 attempts"
                        )

                    if resp.status == 429:
                        wait = 2 ** (attempt + 1)
                        logger.warning(
                            "Rate limited (429), backing off %ds (attempt %d/3)",
                            wait, attempt + 1,
                        )
                        await asyncio.sleep(wait)
                        await self.rate_limiter.acquire()
                        continue

                    if resp.status == 400:
                        body = await resp.text()
                        raise ValueError(
                            f"Bad request for model {model} (400): {body[:300]}"
                        )

                    resp.raise_for_status()
                    data = await resp.json()

                    latency = time.monotonic() - start
                    response_text = data["choices"][0]["message"]["content"]

                    logger.info(
                        "LLM ok: role=%s model=%s latency=%.2fs len=%d",
                        agent_role, model, latency, len(response_text),
                    )
                    return response_text

            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if attempt < 2:
                    wait = 5 * (attempt + 1)
                    logger.warning(
                        "Request error (%s), retrying in %ds (attempt %d/3)",
                        exc, wait, attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise

        raise Exception(f"Max retries exceeded for model {model}")

    async def close(self):
        """Close the underlying HTTP sessions."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        if self._local_session and not self._local_session.closed:
            await self._local_session.close()
            self._local_session = None


# ── Singleton ────────────────────────────────────────────────────────

_client_instance: Optional[NexusLLMClient] = None


def get_llm_client() -> NexusLLMClient:
    """Return the shared NexusLLMClient singleton.

    Loads HUGGINGFACE_API_KEY from /opt/nexus/agents/.env on first call.
    """
    global _client_instance
    if _client_instance is None:
        load_dotenv("/opt/nexus/agents/.env")
        api_key = os.getenv("HUGGINGFACE_API_KEY")
        if not api_key:
            raise ValueError(
                "HUGGINGFACE_API_KEY not found. "
                "Ensure /opt/nexus/agents/.env exists and contains the key."
            )
        _client_instance = NexusLLMClient(api_key)
    return _client_instance


def reset_client():
    """Reset singleton (for testing)."""
    global _client_instance
    _client_instance = None
