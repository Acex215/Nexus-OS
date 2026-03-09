#!/usr/bin/env python3
"""NEXUS OS LLM Router

Role-based, tier-aware LLM routing. Replaces the simple prefer_tier1 boolean
with a routing table that maps task roles to appropriate model tiers, temperatures,
and token budgets.

Public API:
    route_llm_call(role, system_prompt, user_prompt) -> dict
    check_tier_health(tier)                          -> bool
    ROUTING_TABLE                                    (dict)
    TIER_ENDPOINTS                                   (dict)
"""
import json
import logging
import time

import requests

log = logging.getLogger("llm_router")

# ── Routing configuration ──────────────────────────────────────────────────────

ROUTING_TABLE: dict[str, dict] = {
    # Role            preferred  fallback  temp   max_tokens
    "plan":         {"tier": 1, "fallback": 2, "temp": 0.2, "max_tokens": 4096},
    "analyze_code": {"tier": 1, "fallback": 2, "temp": 0.1, "max_tokens": 4096},
    "review_code":  {"tier": 1, "fallback": 2, "temp": 0.1, "max_tokens": 2048},
    "write_code":   {"tier": 2, "fallback": 1, "temp": 0.1, "max_tokens": 2048},
    "execute_bash": {"tier": 2, "fallback": 2, "temp": 0.0, "max_tokens": 1024},
    "summarize":    {"tier": 2, "fallback": 2, "temp": 0.3, "max_tokens": 1024},
    "classify":     {"tier": 2, "fallback": 2, "temp": 0.0, "max_tokens":  256},
    "ask_human":    {"tier": 1, "fallback": 2, "temp": 0.3, "max_tokens":  512},
    "verify":       {"tier": 1, "fallback": 2, "temp": 0.1, "max_tokens": 2048},
}

TIER_ENDPOINTS: dict[int, dict] = {
    1: {"url": "http://10.0.30.2:1234/v1/chat/completions",  "model": "qwen2.5-coder-14b-instruct"},
    2: {"url": "http://10.0.20.6:11434/v1/chat/completions", "model": "qwen2.5-coder:7b"},
    3: {"url": "http://10.0.20.3:11434/v1/chat/completions", "model": "qwen2.5:1.5b"},
}

# Tier-specific call timeouts (seconds)
_TIER_TIMEOUT = {1: 300, 2: 180, 3: 120}

# Sentinel to distinguish a timeout (retry may succeed) from a hard failure
_TIMEOUT_SENTINEL = object()

# ── Health-check cache ────────────────────────────────────────────────────────

_health_cache: dict[int, tuple[bool, float]] = {}   # tier -> (healthy, timestamp)
_HEALTH_TTL = 60.0                                   # seconds


def check_tier_health(tier: int) -> bool:
    """Return True if the tier's API endpoint responds within 5 seconds.

    Results are cached for 60 seconds so the main loop doesn't hammer the endpoints.
    """
    now = time.monotonic()
    cached = _health_cache.get(tier)
    if cached and (now - cached[1]) < _HEALTH_TTL:
        return cached[0]

    endpoint = TIER_ENDPOINTS.get(tier)
    if not endpoint:
        _health_cache[tier] = (False, now)
        return False

    # Use the /models (OpenAI) or /api/tags (Ollama) endpoint for a lightweight check
    base_url = endpoint["url"].rsplit("/v1/", 1)[0]
    health_url = base_url + "/v1/models"

    try:
        r = requests.get(health_url, timeout=5)
        healthy = r.status_code == 200
    except Exception:
        healthy = False

    _health_cache[tier] = (healthy, now)
    log.debug("Tier %d health: %s", tier, "OK" if healthy else "DOWN")
    return healthy


def _call_tier(tier: int, system_prompt: str, user_prompt: str,
               temp: float, max_tokens: int,
               timeout_override: float | None = None) -> str | object | None:
    """Make a single LLM call to the specified tier.

    Returns:
        str               — success
        _TIMEOUT_SENTINEL — timed out (retry with longer timeout may succeed)
        None              — hard failure (connection refused, parse error, etc.)
    """
    endpoint = TIER_ENDPOINTS.get(tier)
    if not endpoint:
        log.error("Unknown tier: %d", tier)
        return None

    timeout = timeout_override if timeout_override is not None else _TIER_TIMEOUT.get(tier, 60)
    payload = {
        "model": endpoint["model"],
        "messages": [
            {"role": "system",  "content": system_prompt},
            {"role": "user",    "content": user_prompt},
        ],
        "temperature":  temp,
        "max_tokens":   max_tokens,
    }

    try:
        r = requests.post(endpoint["url"], json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except requests.exceptions.Timeout:
        log.warning("Tier %d timed out after %ds", tier, timeout)
        return _TIMEOUT_SENTINEL
    except requests.exceptions.HTTPError as e:
        log.warning("Tier %d HTTP error: %s", tier, e)
    except (KeyError, json.JSONDecodeError, IndexError) as e:
        log.warning("Tier %d response parse error: %s", tier, e)
    except Exception as e:
        log.warning("Tier %d unexpected error: %s", tier, e)

    return None


# ── Main routing function ─────────────────────────────────────────────────────

def route_llm_call(role: str, system_prompt: str, user_prompt: str) -> dict:
    """Route an LLM call based on the task role.

    Returns:
        {
          "response":    str | None,
          "tier_used":   int | None,
          "role":        str,
          "tokens_used": int,           # 0 if unavailable
          "error":       str | None,    # only set on failure
        }
    """
    config = ROUTING_TABLE.get(role, ROUTING_TABLE["summarize"])
    preferred = config["tier"]
    fallback  = config["fallback"]
    temp      = config["temp"]
    max_tok   = config["max_tokens"]

    last_timed_out: list[int] = []   # track most recent tier that timed out

    def _try(tier: int, timeout_override: float | None = None) -> str | None:
        if not check_tier_health(tier):
            log.info("Tier %d unhealthy, skipping", tier)
            return None
        log.info("Calling Tier %d for role=%s (timeout=%s)", tier, role,
                 timeout_override or _TIER_TIMEOUT.get(tier))
        result = _call_tier(tier, system_prompt, user_prompt, temp, max_tok,
                            timeout_override=timeout_override)
        if result is _TIMEOUT_SENTINEL:
            last_timed_out[:] = [tier]          # remember for retry pass
            _health_cache[tier] = (False, time.monotonic())
            return None
        if result is None:
            _health_cache[tier] = (False, time.monotonic())
            return None
        return result  # type: ignore[return-value]

    # Try preferred → fallback → Tier 3 as universal last resort
    tried: set[int] = set()
    for tier in [preferred, fallback, 3]:
        if tier in tried:
            continue
        tried.add(tier)
        text = _try(tier)
        if text is not None:
            return {
                "response":    text,
                "tier_used":   tier,
                "role":        role,
                "tokens_used": 0,
                "error":       None,
            }

    # If a tier timed out (not a hard failure), retry it once with 2× timeout
    if last_timed_out:
        retry_tier = last_timed_out[0]
        doubled = _TIER_TIMEOUT.get(retry_tier, 60) * 2
        log.info("Retry pass: Tier %d with %ds timeout", retry_tier, doubled)
        _health_cache[retry_tier] = (True, time.monotonic())   # force health check to pass
        text = _try(retry_tier, timeout_override=doubled)
        if text is not None:
            return {
                "response":    text,
                "tier_used":   retry_tier,
                "role":        role,
                "tokens_used": 0,
                "error":       None,
            }

    log.error("All tiers down for role=%s", role)
    return {
        "response":    None,
        "tier_used":   None,
        "role":        role,
        "tokens_used": 0,
        "error":       "all_tiers_down",
    }
