#!/usr/bin/env python3
"""NEXUS OS CAF — Web Research Module

Provides access to the ThinkPad research API (http://10.0.30.2:18080) for
augmenting plan generation and failure recovery with live web context.

Public API:
    RESEARCH_API                              (str)
    check_research_api()           -> bool
    search_web(query, max_results) -> list[dict]
    fetch_page(url)                -> str | None
    research_topic(query, max_pages) -> list[dict]
    should_research(task_description, error) -> bool
"""

import hashlib
import logging
import time
from typing import Optional

import requests

log = logging.getLogger("web_research")

# ── Constants ──────────────────────────────────────────────────────────────────

RESEARCH_API = "http://10.0.30.2:18080"

_SEARCH_TIMEOUT  = 20   # seconds
_FETCH_TIMEOUT   = 30   # seconds
_HEALTH_TIMEOUT  =  5   # seconds
_HEALTH_TTL      = 60   # seconds between health re-checks

# Keywords that indicate web research would help resolve the issue
_RESEARCH_TRIGGERS = [
    "no module named",
    "modulenotfounderror",
    "importerror",
    "command not found",
    "how to",
    "api",
    "install",
    "configure",
    "error",
    "traceback",
    "exception",
    "permission denied",
    "failed to",
    "cannot",
    "unable to",
    "unknown",
    "deprecated",
    "not found",
]

# ── Health-check cache ─────────────────────────────────────────────────────────

_health_cache: tuple[bool, float] = (False, 0.0)   # (healthy, timestamp)


def check_research_api() -> bool:
    """Return True if the ThinkPad research API is reachable.

    Results are cached for 60 seconds to avoid hammering the endpoint.
    """
    global _health_cache
    healthy, ts = _health_cache
    if time.monotonic() - ts < _HEALTH_TTL:
        return healthy

    try:
        r = requests.get(f"{RESEARCH_API}/health", timeout=_HEALTH_TIMEOUT)
        healthy = r.status_code == 200
    except Exception:
        healthy = False

    _health_cache = (healthy, time.monotonic())
    log.debug("Research API health: %s", "OK" if healthy else "DOWN")
    return healthy


# ── Search ─────────────────────────────────────────────────────────────────────

def search_web(query: str, max_results: int = 5) -> list[dict]:
    """Search via the ThinkPad DDG search endpoint.

    Returns a list of result dicts, each with at least:
        {"title": str, "url": str, "snippet": str}
    Returns an empty list if the API is unreachable or the search fails.
    """
    if not check_research_api():
        log.info("Research API offline — skipping search for: %.60s", query)
        return []

    try:
        r = requests.post(
            f"{RESEARCH_API}/search",
            json={"query": query, "max_results": max_results},
            timeout=_SEARCH_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        results = data if isinstance(data, list) else data.get("results", [])
        log.info("search_web: %d results for '%.60s'", len(results), query)
        return results[:max_results]
    except requests.exceptions.Timeout:
        log.warning("search_web timeout for query: %.60s", query)
    except Exception as e:
        log.warning("search_web error: %s", e)
    return []


# ── Fetch ──────────────────────────────────────────────────────────────────────

def fetch_page(url: str) -> Optional[str]:
    """Fetch a page's text content via the ThinkPad Playwright endpoint.

    Retries once on HTTP 503 (endpoint busy / cold start).
    Returns the page text (str) or None on failure.
    """
    if not check_research_api():
        log.info("Research API offline — skipping fetch for: %.80s", url)
        return None

    for attempt in range(2):
        try:
            r = requests.post(
                f"{RESEARCH_API}/fetch",
                json={"url": url},
                timeout=_FETCH_TIMEOUT,
            )
            if r.status_code == 503 and attempt == 0:
                log.info("fetch_page: 503 on attempt 1, retrying in 3s")
                time.sleep(3)
                continue
            r.raise_for_status()
            data = r.json()
            content = data.get("content") or data.get("text") or (
                data if isinstance(data, str) else None
            )
            if content:
                log.info("fetch_page: %d chars from %s", len(content), url[:60])
            return content
        except requests.exceptions.Timeout:
            log.warning("fetch_page timeout for: %.80s", url)
            break
        except Exception as e:
            log.warning("fetch_page error (%s): %s", url[:60], e)
            break
    return None


# ── Research topic ─────────────────────────────────────────────────────────────

def research_topic(query: str, max_pages: int = 3) -> list[dict]:
    """Search + fetch + store in ChromaDB.  Returns enriched result dicts.

    Each returned dict contains:
        {"title": str, "url": str, "snippet": str, "content": str | None}

    Results are stored in the ChromaDB "web_research" collection using a
    deterministic URL-hash document ID so re-fetching the same URL is idempotent.
    """
    results = search_web(query, max_results=max_pages * 2)
    if not results:
        return []

    enriched: list[dict] = []

    # Lazy import to avoid hard dependency when ChromaDB is unavailable
    try:
        import chromadb
        chroma = chromadb.HttpClient(host="localhost", port=8000)
        collection = chroma.get_or_create_collection("web_research")
        chroma_ok = True
    except Exception as e:
        log.warning("ChromaDB unavailable — research results will not be stored: %s", e)
        chroma_ok = False

    fetched = 0
    for item in results:
        url = item.get("url", "")
        title = item.get("title", "")
        snippet = item.get("snippet", "")

        content: Optional[str] = None
        if fetched < max_pages and url:
            content = fetch_page(url)
            if content:
                fetched += 1

        # Store in ChromaDB (idempotent via URL hash ID)
        if chroma_ok and url:
            doc_id = "wr_" + hashlib.sha256(url.encode()).hexdigest()[:16]
            doc_text = f"Title: {title}\nURL: {url}\nSnippet: {snippet}"
            if content:
                # Store first 2000 chars of page content alongside metadata
                doc_text += f"\n\nContent:\n{content[:2000]}"
            try:
                collection.upsert(
                    ids=[doc_id],
                    documents=[doc_text],
                    metadatas=[{
                        "query":   query[:200],
                        "url":     url[:500],
                        "title":   title[:200],
                        "fetched": str(bool(content)),
                    }],
                )
            except Exception as e:
                log.warning("ChromaDB upsert failed for %s: %s", url[:60], e)

        enriched.append({
            "title":   title,
            "url":     url,
            "snippet": snippet,
            "content": content,
        })

    log.info(
        "research_topic: %d results, %d pages fetched for '%.60s'",
        len(enriched), fetched, query,
    )
    return enriched


# ── Trigger logic ──────────────────────────────────────────────────────────────

def should_research(task_description: str, error: str = "") -> bool:
    """Return True if web research is likely to help with this task/error.

    Triggers on:
    - Known error keywords in the error string (import failures, not found, etc.)
    - Task description containing research-relevant terms
    - Research API being online (no point triggering if offline)
    """
    if not check_research_api():
        return False

    combined = (task_description + " " + error).lower()
    for trigger in _RESEARCH_TRIGGERS:
        if trigger in combined:
            return True
    return False
