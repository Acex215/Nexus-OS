#!/usr/bin/env python3
"""NEXUS OS -- Weekly Self-Improvement Analysis

Runs SelfImprover.generate_proposals() over the last 7 days of task logs,
queues approved-style proposals into TaskQueue with source='self-improvement',
and posts a summary to Discord #agent-chat via webhook.

Designed to be triggered by nexus-self-improvement.timer (weekly Sunday 03:00 UTC).
Can also be run manually: python3 /opt/nexus/scripts/run_self_improvement.py
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

# Ensure project paths are importable
for p in ['/opt/nexus/agents', '/opt/nexus']:
    if p not in sys.path:
        sys.path.insert(0, p)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("self_improvement_run")

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
SUMMARY_LOG = "/opt/nexus/logs/self_improvement.log"


def post_discord(message: str):
    """Post message to Discord webhook. Falls back to logging if unavailable."""
    if not WEBHOOK_URL:
        log.info("[Discord] No webhook URL configured, logging only:\n%s", message)
        return

    try:
        import urllib.request
        payload = json.dumps({"content": message[:1990]}).encode()
        req = urllib.request.Request(
            WEBHOOK_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        log.info("[Discord] Summary posted to webhook")
    except Exception as e:
        log.warning("[Discord] Webhook post failed: %s", e)


def run():
    log.info("=== Self-Improvement Analysis starting ===")
    ts_start = time.monotonic()

    # 1. Get performance summary for the past 7 days
    try:
        from metrics import get_performance_summary
        summary = get_performance_summary(window_hours=168)
        log.info("Performance summary: %s", summary)
    except Exception as e:
        log.error("Failed to get performance summary: %s", e)
        summary = None

    # 2. Generate proposals
    try:
        from self_improver import generate_proposals, format_proposals
        proposals = generate_proposals(summary)
        log.info("Generated %d proposals", len(proposals))
    except Exception as e:
        log.error("Failed to generate proposals: %s", e)
        proposals = []

    if not proposals:
        msg = (
            "**Weekly Self-Improvement Report** "
            f"({datetime.now(timezone.utc).strftime('%Y-%m-%d')})\n\n"
            "No improvement proposals this week. System is healthy."
        )
        post_discord(msg)
        log.info("No proposals generated. Done.")
        return

    # 3. Add proposals to task queue with source='self-improvement'
    try:
        from task_queue import TaskQueue
        queue = TaskQueue()
    except Exception as e:
        log.error("Failed to load task queue: %s", e)
        post_discord(f"Self-improvement analysis generated {len(proposals)} proposals but failed to queue them: {e}")
        return

    queued_ids = []
    for p in proposals:
        desc = f"[self-improvement] {p['description']}"
        tid = queue.add(
            description=desc,
            priority=p.get("priority", "P2"),
            risk=p.get("risk", "low"),
        )
        queued_ids.append((tid, p))
        log.info("Queued proposal: %s -> %s", tid, desc[:80])

    # 4. Build summary message
    duration = time.monotonic() - ts_start
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines = [
        f"**Weekly Self-Improvement Report** ({date_str})",
        "",
    ]

    if summary:
        sr = summary.get("success_rate", "?")
        total = summary.get("total_tasks", "?")
        failed = summary.get("failed_tasks", "?")
        lines.append(f"**7-day stats:** {total} tasks, {sr}% success, {failed} failures")
        cats = summary.get("failure_categories", {})
        if cats:
            cat_parts = [f"{k}: {v}" for k, v in cats.items() if v > 0]
            if cat_parts:
                lines.append(f"**Failure breakdown:** {', '.join(cat_parts)}")
        lines.append("")

    lines.append(f"**{len(proposals)} proposals queued:**")
    for tid, p in queued_ids:
        lines.append(f"  [{p['priority']}] `{tid}`: {p['description'][:70]}")
        lines.append(f"        Rationale: {p['rationale'][:100]}")

    lines.append("")
    lines.append(
        "These tasks go through the standard approval gate. "
        "Say `approve <task-id>` or review in the queue."
    )
    lines.append(f"Analysis took {duration:.1f}s.")

    msg = "\n".join(lines)
    post_discord(msg)

    # 5. Append to persistent log
    try:
        os.makedirs(os.path.dirname(SUMMARY_LOG), exist_ok=True)
        with open(SUMMARY_LOG, "a") as f:
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "proposals": len(proposals),
                "queued_ids": [t[0] for t in queued_ids],
                "summary": summary,
                "duration_seconds": round(duration, 2),
            }
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        log.warning("Failed to write summary log: %s", e)

    log.info("=== Self-Improvement Analysis complete: %d proposals queued in %.1fs ===",
             len(proposals), duration)


if __name__ == "__main__":
    run()
