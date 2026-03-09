#!/usr/bin/env python3
"""NEXUS OS CAF — Discord Reporter

Thin compatibility shim that re-exports the full public API of discord_comms.
Import this module instead of discord_comms when you want guaranteed no-crash
behaviour even if Discord credentials are missing or the bot cannot connect.

All symbols are imported from discord_comms; any that are unavailable are
replaced with safe no-op stubs so the orchestrator never crashes due to a
Discord outage.
"""

import logging
import os

log = logging.getLogger("discord_reporter")

# ── Standalone REST-API sender (no bot thread required) ───────────────────────

_DISCORD_API = "https://discord.com/api/v10"
_CHANNEL_ID  = "1446026349528616990"   # CAF agent-chat channel


def send_oneshot(message: str, channel_id: str | None = None) -> bool:
    """Send a single message via Discord REST API without a running bot thread.

    Self-contained: loads credentials from /opt/nexus/agents/.env directly so
    this works regardless of import order and in standalone scripts.
    Returns True on success, False on any failure (never raises).
    """
    # Load .env explicitly — don't rely on discord_comms having been imported first
    try:
        from dotenv import load_dotenv
        load_dotenv("/opt/nexus/agents/.env", override=False)
    except Exception:
        pass

    token = os.environ.get("CAF_DISCORD_TOKEN", "")
    if not token:
        log.warning("send_oneshot: CAF_DISCORD_TOKEN not set — message not sent")
        return False

    # Prefer env CAF_CHANNEL_ID; fall back to hardcoded constant
    cid = channel_id or os.environ.get("CAF_CHANNEL_ID", _CHANNEL_ID)
    url = f"{_DISCORD_API}/channels/{cid}/messages"

    try:
        import requests as _req
        r = _req.post(
            url,
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type":  "application/json",
            },
            json={"content": message[:2000]},
            timeout=10,
        )
        if r.status_code in (200, 201):
            log.info("send_oneshot: sent %d chars to channel %s", len(message), cid)
            return True
        log.warning("send_oneshot: Discord API %s — %s", r.status_code, r.text[:200])
        return False
    except Exception as exc:
        log.warning("send_oneshot: %s", exc)
        return False

# ── Import from discord_comms, stub anything missing ───────────────────────

try:
    from discord_comms import (           # noqa: F401  (re-export)
        send_notification,
        start_discord_listener,
        handle_discord_message,
        should_notify,
        is_idle_mode,
        update_stats,
        request_approval,
        send_status_summary,
    )
    _COMMS_AVAILABLE = True
    log.debug("discord_reporter: discord_comms loaded successfully")
except ImportError as _exc:
    log.warning("discord_reporter: discord_comms unavailable (%s) — using stubs", _exc)
    _COMMS_AVAILABLE = False

    # ── No-op stubs ────────────────────────────────────────────────────────

    def send_notification(kind: str, message: str, **kwargs) -> None:  # type: ignore[misc]
        log.debug("discord_reporter stub: send_notification(%s, %s...)", kind, message[:60])

    def start_discord_listener(handler=None) -> None:  # type: ignore[misc]
        log.debug("discord_reporter stub: start_discord_listener (noop)")

    def handle_discord_message(message) -> None:  # type: ignore[misc]
        log.debug("discord_reporter stub: handle_discord_message (noop)")

    def should_notify(event_type: str) -> bool:  # type: ignore[misc]
        return False

    def is_idle_mode() -> bool:  # type: ignore[misc]
        return False

    def update_stats(**kwargs) -> None:  # type: ignore[misc]
        pass

    def request_approval(intent: dict, plan: dict) -> bool:  # type: ignore[misc]
        log.warning("discord_reporter stub: request_approval returning False (Discord offline)")
        return False

    def send_status_summary(**kwargs) -> None:  # type: ignore[misc]
        log.debug("discord_reporter stub: send_status_summary (noop)")


def is_available() -> bool:
    """Return True if the real discord_comms module loaded successfully."""
    return _COMMS_AVAILABLE
