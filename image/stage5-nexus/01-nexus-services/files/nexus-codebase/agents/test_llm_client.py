"""Tests for NEXUS OS LLM Client."""
import asyncio
import time
import pytest
import pytest_asyncio
from llm_client import NexusLLMClient, RateLimiter, get_llm_client, reset_client


@pytest_asyncio.fixture
async def client():
    """Provide a shared client backed by the real .env key."""
    c = get_llm_client()
    yield c
    await c.close()
    reset_client()


# ── 1. CEO completion (Qwen2.5-7B) ──────────────────────────────────

@pytest.mark.asyncio
async def test_ceo_completion(client):
    messages = [
        {"role": "system", "content": "You are the NEXUS OS CEO. Reply in JSON."},
        {"role": "user", "content": "Status report on the cluster."},
    ]
    resp = await client.chat_completion("ceo", messages, max_tokens=128)
    assert isinstance(resp, str)
    assert len(resp) > 0
    model = client._select_model("ceo")
    assert model == "Qwen/Qwen2.5-7B-Instruct"
    print(f"\n  CEO model: {model}")
    print(f"  Response ({len(resp)} chars): {resp[:120]}...")


# ── 2. Worker completion (SmolLM2-1.7B) ─────────────────────────────

@pytest.mark.asyncio
async def test_director_completion(client):
    messages = [
        {"role": "system", "content": "You are a compute director. Reply briefly."},
        {"role": "user", "content": "Summarize cluster CPU status."},
    ]
    resp = await client.chat_completion("director", messages, max_tokens=64)
    assert isinstance(resp, str)
    assert len(resp) > 0
    model = client._select_model("director")
    assert model == "meta-llama/Llama-3.2-3B-Instruct"
    print(f"\n  Director model: {model}")
    print(f"  Response ({len(resp)} chars): {resp[:120]}...")


@pytest.mark.asyncio
async def test_worker_completion(client):
    messages = [
        {"role": "system", "content": "You are a compute worker. Reply briefly."},
        {"role": "user", "content": "What is your current CPU load?"},
    ]
    resp = await client.chat_completion("worker", messages, max_tokens=64)
    assert isinstance(resp, str)
    assert len(resp) > 0
    model = client._select_model("worker")
    assert model == "meta-llama/Llama-3.2-1B-Instruct"
    print(f"\n  Worker model: {model}")
    print(f"  Response ({len(resp)} chars): {resp[:120]}...")


# ── 3. Rate limiting (35 rapid requests) ────────────────────────────

@pytest.mark.asyncio
async def test_rate_limiting(client):
    """Fire 10 rapid requests concurrently and verify rate limiter throttles."""
    total = 10
    messages = [{"role": "user", "content": "Say OK"}]
    successes = 0
    errors = []

    start = time.monotonic()

    async def fire(i):
        nonlocal successes
        try:
            await client.chat_completion(
                "ceo", messages, max_tokens=4, temperature=0.1
            )
            successes += 1
        except Exception as e:
            errors.append(str(e))

    tasks = [fire(i) for i in range(total)]
    await asyncio.gather(*tasks)

    elapsed = time.monotonic() - start
    print(f"\n  {successes}/{total} succeeded in {elapsed:.1f}s")
    if errors:
        print(f"  Errors: {errors[:3]}")

    # All should succeed (rate limiter queues, doesn't reject)
    assert successes == total, f"Only {successes}/{total} succeeded: {errors[:3]}"
    # Should take some time due to rate limiting (burst=5, so 5 extra need waiting)
    assert elapsed >= 2.0, f"Too fast ({elapsed:.1f}s) - rate limiter may not be working"


# ── 4. Invalid API key ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_key():
    bad_client = NexusLLMClient(api_key="hf_INVALID_KEY_12345")
    messages = [{"role": "user", "content": "Hello"}]
    try:
        with pytest.raises(ValueError, match="Invalid HuggingFace API key"):
            await bad_client.chat_completion("ceo", messages, max_tokens=8)
    finally:
        await bad_client.close()
