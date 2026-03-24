#!/usr/bin/env python3
"""NEXUS OS — Subagent Client

Thin wrapper for delegating tasks to the Ollama subagent running on
nexus-master (10.0.20.3:11434).  This is a separate compute tier from
Tier 2 (nexus-ai2 Qwen2.5-coder:7b): it runs qwen2.5:1.5b and is
intended for lightweight, parallel or non-latency-critical work.

Public API:
    check_health()                      → bool
    ask(question, context="")           → str
    summarize(text, max_words=200)      → str
    review_code(code, language="python")→ str
    research(query)                     → str
"""

import logging

import requests

log = logging.getLogger("subagent_client")

SUBAGENT_URL   = "http://10.0.20.3:11434"
SUBAGENT_MODEL = "qwen2.5:1.5b"
TIMEOUT        = 120   # seconds — first call loads the model into RAM


# ── Core call ──────────────────────────────────────────────────────────────────

def _call(prompt: str, system: str = "", max_tokens: int = 1024) -> str:
    """POST to /api/generate and return the response text.

    Returns an error string prefixed with '[SUBAGENT ERROR]' on failure
    so callers can log it without crashing.
    """
    payload: dict = {
        "model":   SUBAGENT_MODEL,
        "prompt":  prompt,
        "stream":  False,
        "options": {"num_predict": max_tokens, "temperature": 0.3},
    }
    if system:
        payload["system"] = system

    try:
        r = requests.post(
            f"{SUBAGENT_URL}/api/generate",
            json=payload,
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get("response", "").strip()
    except requests.exceptions.Timeout:
        msg = f"[SUBAGENT ERROR] Request timed out after {TIMEOUT}s"
        log.warning(msg)
        return msg
    except Exception as exc:
        msg = f"[SUBAGENT ERROR] {exc}"
        log.warning(msg)
        return msg


# ── Public API ─────────────────────────────────────────────────────────────────

def check_health() -> bool:
    """Return True if the subagent is reachable and has the model loaded."""
    try:
        r = requests.get(f"{SUBAGENT_URL}/api/tags", timeout=5)
        if r.status_code != 200:
            return False
        models = [m["name"] for m in r.json().get("models", [])]
        return SUBAGENT_MODEL in models
    except Exception:
        return False


def ask(question: str, context: str = "") -> str:
    """Ask the subagent a free-form question with optional context."""
    if context:
        prompt = f"Context:\n{context}\n\nQuestion: {question}"
    else:
        prompt = question
    return _call(prompt)


def summarize(text: str, max_words: int = 200) -> str:
    """Summarize text in under max_words words."""
    return _call(
        f"Summarize the following in under {max_words} words:\n\n{text}",
        system="You are a concise technical summarizer. Output only the summary.",
    )


def review_code(code: str, language: str = "python") -> str:
    """Review code for bugs, security issues, and improvements."""
    return _call(
        f"Review this {language} code for bugs, security issues, and improvements:\n\n"
        f"```{language}\n{code}\n```",
        system=(
            "You are a senior code reviewer. Be concise and specific. "
            "List issues as bullet points. Focus on correctness and security."
        ),
    )


def research(query: str) -> str:
    """Return a concise factual summary on the query topic."""
    return _call(
        f"What do you know about: {query}\n\nProvide a concise, factual summary.",
        system=(
            "You are a technical research assistant. "
            "Be accurate and concise. Acknowledge when you are uncertain."
        ),
    )
