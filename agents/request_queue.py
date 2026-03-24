"""
NEXUS OS — Global LLM Request Queue with Rate Limiting

Enforces rate limits across all agent LLM calls and provides priority
queueing so C-Suite agents get first access to limited inference resources.

Config:
  MIN_DELAY_MS = 500        — minimum delay between requests to same endpoint
  HF_RATE_LIMIT = 100       — max requests per hour to HuggingFace
  LOCAL_RATE_LIMIT = 0      — no limit for local LM Studio/Ollama

Priority levels:
  3 = C-Suite (CEO, COO)
  2 = Director
  1 = Worker
"""

import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger("nexus.request_queue")

# ── Configuration ────────────────────────────────────────────────────────

MIN_DELAY_MS = 500
HF_RATE_LIMIT = 100       # per hour
LOCAL_RATE_LIMIT = 0       # 0 = unlimited

# Endpoints containing these substrings are treated as HuggingFace
HF_MARKERS = ["huggingface", "hf.co", "api-inference"]

# Priority levels
PRIORITY_CSUITE = 3
PRIORITY_DIRECTOR = 2
PRIORITY_WORKER = 1


@dataclass(order=True)
class QueuedRequest:
    """A request in the priority queue. Higher priority = processed first."""
    priority: int
    enqueue_time: float = field(compare=False)
    request_id: int = field(compare=False)
    endpoint: str = field(compare=False)
    payload: dict = field(compare=False)
    timeout: int = field(compare=False)
    future: asyncio.Future = field(compare=False, repr=False)
    caller_api: Any = field(compare=False, repr=False, default=None)


class RequestQueue:
    """
    Global request queue that enforces rate limits across all agent LLM calls.
    Uses an asyncio priority queue (negated priority for max-first behavior).
    """

    def __init__(self):
        self._queue = asyncio.PriorityQueue()
        self._request_counter = 0
        self._processing = False

        # Rate limit tracking: endpoint → deque of timestamps
        self._request_history = defaultdict(deque)
        # Last request time per endpoint (for MIN_DELAY enforcement)
        self._last_request_time = {}
        # Stats
        self._completed_history = deque()  # (timestamp, latency_ms)
        self._rate_limit_hits = deque()    # timestamps of rate limit blocks

        self._lock = asyncio.Lock()

    # ── Enqueue ─────────────────────────────────────────────────────────────

    async def enqueue(self, endpoint, payload, timeout, priority=PRIORITY_WORKER,
                      caller_api=None):
        """
        Add a request to the priority queue.

        Args:
            endpoint: target LLM endpoint URL
            payload: request payload dict (OpenAI-compatible)
            timeout: request timeout seconds
            priority: 3=C-Suite, 2=Director, 1=Worker
            caller_api: the _call_api coroutine to use for execution

        Returns:
            The LLM response (awaitable — resolves when request is processed)
        """
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        self._request_counter += 1
        # Negate priority so higher priority = lower sort key = dequeued first
        item = QueuedRequest(
            priority=-priority,
            enqueue_time=time.monotonic(),
            request_id=self._request_counter,
            endpoint=endpoint,
            payload=payload,
            timeout=timeout,
            future=future,
            caller_api=caller_api,
        )

        await self._queue.put(item)
        log.debug("Enqueued request #%d to %s (priority=%d, queue_size=%d)",
                  self._request_counter, endpoint[:40], priority, self._queue.qsize())

        # Ensure the processor is running
        if not self._processing:
            asyncio.ensure_future(self.process_queue())

        return await future

    # ── Process queue ───────────────────────────────────────────────────────

    async def process_queue(self):
        """
        Main processing loop. Dequeues requests in priority order,
        enforces rate limits, and executes LLM calls.
        """
        if self._processing:
            return
        self._processing = True

        try:
            while not self._queue.empty():
                item = await self._queue.get()

                # Skip if future was cancelled (e.g., timeout on caller side)
                if item.future.done():
                    self._queue.task_done()
                    continue

                # Rate limit check
                while self._is_rate_limited_internal(item.endpoint):
                    wait_time = self._rate_limit_wait_time(item.endpoint)
                    self._rate_limit_hits.append(time.time())
                    log.info("Rate limited for %s, waiting %.1fs", item.endpoint[:40], wait_time)
                    await asyncio.sleep(wait_time)

                # MIN_DELAY enforcement
                await self._enforce_min_delay(item.endpoint)

                # Execute the request
                start = time.monotonic()
                try:
                    if item.caller_api:
                        result = await item.caller_api(item.endpoint, item.payload, item.timeout)
                    else:
                        result = await self._default_call(item.endpoint, item.payload, item.timeout)

                    latency_ms = (time.monotonic() - start) * 1000
                    self._record_request(item.endpoint, latency_ms)

                    if not item.future.done():
                        item.future.set_result(result)

                except Exception as e:
                    latency_ms = (time.monotonic() - start) * 1000
                    self._record_request(item.endpoint, latency_ms)

                    if not item.future.done():
                        item.future.set_exception(e)

                self._queue.task_done()
        finally:
            self._processing = False

    async def _enforce_min_delay(self, endpoint):
        """Wait if necessary to maintain MIN_DELAY_MS between requests."""
        async with self._lock:
            last_time = self._last_request_time.get(endpoint)
            if last_time is not None:
                elapsed_ms = (time.monotonic() - last_time) * 1000
                if elapsed_ms < MIN_DELAY_MS:
                    wait_s = (MIN_DELAY_MS - elapsed_ms) / 1000
                    await asyncio.sleep(wait_s)
            self._last_request_time[endpoint] = time.monotonic()

    def _record_request(self, endpoint, latency_ms):
        """Record a completed request for rate tracking and stats."""
        now = time.time()
        self._request_history[endpoint].append(now)
        self._completed_history.append((now, latency_ms))
        # Trim old entries
        cutoff = now - 3600
        while (self._request_history[endpoint]
               and self._request_history[endpoint][0] < cutoff):
            self._request_history[endpoint].popleft()

    async def _default_call(self, endpoint, payload, timeout):
        """Default HTTP call if no caller_api provided."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    endpoint,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise RuntimeError(f"API returned {resp.status}: {body[:500]}")
                    data = await resp.json()
            content = data["choices"][0]["message"]["content"]
            tokens = data.get("usage", {}).get("total_tokens", 0)
            return content, tokens
        except ImportError:
            raise RuntimeError("aiohttp not installed for default API calls")

    # ── Rate limit checks ───────────────────────────────────────────────────

    def is_rate_limited(self, endpoint):
        """
        Check if an endpoint is currently rate-limited.

        Returns:
            bool: True if requests to this endpoint would be delayed
        """
        return self._is_rate_limited_internal(endpoint)

    def _is_rate_limited_internal(self, endpoint):
        """Internal rate limit check."""
        limit = self._get_rate_limit(endpoint)
        if limit == 0:
            return False

        now = time.time()
        cutoff = now - 3600
        history = self._request_history.get(endpoint, deque())

        # Trim old entries
        while history and history[0] < cutoff:
            history.popleft()

        return len(history) >= limit

    def _rate_limit_wait_time(self, endpoint):
        """Calculate seconds to wait before next request is allowed."""
        limit = self._get_rate_limit(endpoint)
        if limit == 0:
            return 0

        history = self._request_history.get(endpoint, deque())
        if not history:
            return 0

        # Wait until the oldest request in the window expires
        oldest = history[0]
        wait = (oldest + 3600) - time.time()
        return max(wait, 0.1)

    def _get_rate_limit(self, endpoint):
        """Get the rate limit for an endpoint."""
        endpoint_lower = endpoint.lower()
        for marker in HF_MARKERS:
            if marker in endpoint_lower:
                return HF_RATE_LIMIT
        return LOCAL_RATE_LIMIT

    # ── Status ──────────────────────────────────────────────────────────────

    def get_queue_status(self):
        """
        Current queue and rate limit status.

        Returns:
            dict: {pending, processing, completed_last_hour,
                   rate_limit_hits_last_hour, avg_latency_ms}
        """
        now = time.time()
        cutoff = now - 3600

        # Trim stats
        while self._completed_history and self._completed_history[0][0] < cutoff:
            self._completed_history.popleft()
        while self._rate_limit_hits and self._rate_limit_hits[0] < cutoff:
            self._rate_limit_hits.popleft()

        latencies = [lat for _, lat in self._completed_history]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0

        return {
            "pending": self._queue.qsize(),
            "processing": self._processing,
            "completed_last_hour": len(self._completed_history),
            "rate_limit_hits_last_hour": len(self._rate_limit_hits),
            "avg_latency_ms": round(avg_latency, 1),
        }


# ── Singleton ───────────────────────────────────────────────────────────

_instance = None


def get_request_queue():
    """Get or create the singleton RequestQueue instance."""
    global _instance
    if _instance is None:
        _instance = RequestQueue()
    return _instance


# ── Main demo ───────────────────────────────────────────────────────────

async def _demo():
    print("=== NEXUS LLM Request Queue Demo ===\n")

    queue = RequestQueue()

    # Simulate requests from different tiers
    print("--- Queue status (empty) ---")
    status = queue.get_queue_status()
    print(f"  Pending: {status['pending']}")
    print(f"  Processing: {status['processing']}")

    # Rate limit check
    print("\n--- Rate limit checks ---")
    endpoints = [
        "http://10.0.30.3:1234/v1/chat/completions",
        "https://api-inference.huggingface.co/models/test",
        "http://10.0.20.6:11434/v1/chat/completions",
    ]
    for ep in endpoints:
        limited = queue.is_rate_limited(ep)
        limit = queue._get_rate_limit(ep)
        label = f"{limit}/hr" if limit > 0 else "unlimited"
        print(f"  {ep[:50]:<50s} limit={label:<12s} limited={limited}")

    # Simulate enqueue + process with mock caller
    print("\n--- Simulated requests ---")

    call_count = [0]

    async def mock_api(endpoint, payload, timeout):
        call_count[0] += 1
        await asyncio.sleep(0.05)  # simulate latency
        return f"Response from {endpoint[:30]}...", 42

    # Enqueue requests with different priorities
    tasks = []
    for name, priority in [("worker_1", 1), ("director_1", 2), ("ceo", 3), ("worker_2", 1)]:
        t = asyncio.create_task(
            queue.enqueue(
                endpoint="http://10.0.30.3:1234/v1/chat/completions",
                payload={"model": "test", "messages": [{"role": "user", "content": f"from {name}"}]},
                timeout=30,
                priority=priority,
                caller_api=mock_api,
            )
        )
        tasks.append((name, priority, t))

    # Wait for all to complete
    for name, priority, t in tasks:
        try:
            result = await asyncio.wait_for(t, timeout=10)
            print(f"  {name:<15s} priority={priority}  result={result[0][:40]}...")
        except Exception as e:
            print(f"  {name:<15s} priority={priority}  error={e}")

    print(f"\n  Total API calls made: {call_count[0]}")

    # Final status
    print("\n--- Queue status (after processing) ---")
    status = queue.get_queue_status()
    print(f"  Pending:              {status['pending']}")
    print(f"  Completed (last hr):  {status['completed_last_hour']}")
    print(f"  Rate limit hits:      {status['rate_limit_hits_last_hour']}")
    print(f"  Avg latency:          {status['avg_latency_ms']}ms")

    print("\nDone.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s  %(message)s")
    asyncio.run(_demo())
