#!/usr/bin/env python3
"""external_tools.py — Simple HTTP dispatcher for external tool calls.

Phase 10 approach: a plain dict registry + HTTP client.
Full JSON-RPC-over-stdio MCP client integration is deferred to Phase 11.

Usage (from the execution engine)
----------------------------------
from external_tools import call_external_tool

result = await call_external_tool("hf_search_models", {"query": "whisper", "limit": 5})
# {"status": "ok", "data": [...], "tool": "hf_search_models"}

result = await call_external_tool("hf_model_info", {"model_id": "openai/whisper-large-v3"})
# {"status": "ok", "data": {...}, "tool": "hf_model_info"}
"""

import logging
from typing import Any

import httpx

log = logging.getLogger("external_tools")

# ── Tool registry ─────────────────────────────────────────────────────────────
#
# Schema for each entry:
#   description  — human-readable, shown to the coordinator LLM
#   endpoint     — URL template; {name} tokens are expanded from call args
#   method       — HTTP verb (GET only for now)
#   params       — optional query-param template:
#                    str value  → look up that key in call args
#                    other type → use as a literal default (overridable by args)
#   path_params  — list of arg keys that are consumed by URL template expansion
#                  (so they are not also sent as query params)

EXTERNAL_TOOLS: dict[str, dict[str, Any]] = {
    "hf_search_models": {
        "description": (
            "Search HuggingFace Hub for ML models. "
            "Args: query (str, required), limit (int, default 5), "
            "filter (str, optional — e.g. 'text-generation'), "
            "sort (str, optional — e.g. 'downloads')."
        ),
        "endpoint": "https://huggingface.co/api/models",
        "method": "GET",
        # str value = name of the key to pull from call args
        # int value = literal default, caller may override with same-named arg
        "params": {
            "search": "query",   # args["query"]  → ?search=<value>
            "limit":  5,         # literal default; caller can pass limit=N
        },
    },
    "hf_model_info": {
        "description": (
            "Get detailed info about a specific HuggingFace model. "
            "Args: model_id (str, required — e.g. 'openai/whisper-large-v3')."
        ),
        "endpoint": "https://huggingface.co/api/models/{model_id}",
        "method": "GET",
        "path_params": ["model_id"],
    },
}

# ── Dispatcher ────────────────────────────────────────────────────────────────

_TIMEOUT = 15.0  # seconds


def _build_url(spec: dict, args: dict) -> str:
    """Expand {name} tokens in the endpoint template using *args*."""
    try:
        return spec["endpoint"].format(**args)
    except KeyError as exc:
        raise ValueError(f"Missing required path parameter: {exc}") from exc


def _build_params(spec: dict, args: dict) -> dict:
    """Build query-param dict from the spec template and caller args.

    Rules:
    - Path params (listed in spec["path_params"]) are skipped — they were
      already consumed by URL template expansion.
    - For each entry in spec["params"]:
        - str value  → use args[value] if present, else skip
        - other type → use as default; caller can override with same-named arg
    - Any remaining caller args not consumed above are forwarded as-is
      (allows callers to pass extra HF API params like 'sort' or 'filter').
    """
    path_keys = set(spec.get("path_params", []))
    # Keys already consumed by URL expansion — exclude from query params.
    consumed = set(path_keys)

    query: dict[str, Any] = {}
    for param_name, param_source in spec.get("params", {}).items():
        if isinstance(param_source, str):
            # param_source is the arg key whose value becomes the query value
            consumed.add(param_source)
            if param_source in args:
                query[param_name] = args[param_source]
        else:
            # Literal default — caller may override with the param_name key
            query[param_name] = args.get(param_name, param_source)
            consumed.add(param_name)

    # Forward any unconsummed caller args as extra query params
    for key, val in args.items():
        if key not in consumed:
            query[key] = val

    return query


async def call_external_tool(tool_name: str, args: dict) -> dict:
    """Call an external tool by name and return its result.

    Parameters
    ----------
    tool_name : str
        Key from EXTERNAL_TOOLS (e.g. "hf_search_models").
    args : dict
        Keyword arguments for the tool (see each tool's "description" field).

    Returns
    -------
    dict
        On success: {"status": "ok",    "tool": tool_name, "data": <response>}
        On error:   {"status": "error", "tool": tool_name, "message": <str>}
    """
    spec = EXTERNAL_TOOLS.get(tool_name)
    if spec is None:
        available = ", ".join(EXTERNAL_TOOLS)
        return {
            "status":  "error",
            "tool":    tool_name,
            "message": f"Unknown tool '{tool_name}'. Available: {available}",
        }

    try:
        url    = _build_url(spec, args)
        params = _build_params(spec, args)
    except ValueError as exc:
        return {"status": "error", "tool": tool_name, "message": str(exc)}

    method = spec.get("method", "GET").upper()
    log.info("external_tool %s → %s %s params=%s", tool_name, method, url, params)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            if method == "GET":
                resp = await client.get(url, params=params)
            else:
                return {
                    "status":  "error",
                    "tool":    tool_name,
                    "message": f"HTTP method '{method}' not implemented in dispatcher",
                }
            resp.raise_for_status()
            data = resp.json()

    except httpx.TimeoutException:
        msg = f"Request timed out after {_TIMEOUT}s (tool={tool_name})"
        log.warning(msg)
        return {"status": "error", "tool": tool_name, "message": msg}

    except httpx.HTTPStatusError as exc:
        msg = f"HTTP {exc.response.status_code} from {url}"
        log.warning("%s: %s", tool_name, msg)
        return {"status": "error", "tool": tool_name, "message": msg}

    except Exception as exc:
        msg = f"Unexpected error calling {tool_name}: {exc}"
        log.error(msg, exc_info=True)
        return {"status": "error", "tool": tool_name, "message": msg}

    return {"status": "ok", "tool": tool_name, "data": data}


# ── Convenience helpers ───────────────────────────────────────────────────────

def list_tools() -> list[dict]:
    """Return a list of available tools with their descriptions (for prompts)."""
    return [
        {"name": name, "description": spec["description"]}
        for name, spec in EXTERNAL_TOOLS.items()
    ]


def tool_names() -> list[str]:
    """Return just the tool names (for quick inclusion in system prompts)."""
    return list(EXTERNAL_TOOLS.keys())
