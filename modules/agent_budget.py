"""
NEXUS OS — Agent Budget Caps & Safe Mode

Per-agent budget enforcement with automatic safe mode triggers on
correlated failures. Budget caps are ALWAYS enforced — they are not
toggleable like token enforcement.

Integrates with:
  - circuit_breaker.py: PAUSE_REPAIRS, PAUSE_TOKEN_ACTIONS, PAUSE_INFERENCE, SAFE_MODE
  - token_hooks.py: cost_check() calls check_budget() before spending
"""

import json
import logging
import os
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import Lock

log = logging.getLogger("nexus.agent_budget")

# ── Budget caps per tier (ECT per hour) ─────────────────────────────────

C_SUITE_MAX_ECT_PER_HOUR = 200
DIRECTOR_MAX_ECT_PER_HOUR = 100
WORKER_MAX_ECT_PER_HOUR = 30

# Operation-specific caps (per hour, per agent)
MAX_STORAGE_REPAIRS_PER_HOUR = 5
MAX_INFERENCE_REQUESTS_PER_HOUR = 50

TIER_LIMITS = {
    "c_suite": C_SUITE_MAX_ECT_PER_HOUR,
    "director": DIRECTOR_MAX_ECT_PER_HOUR,
    "worker": WORKER_MAX_ECT_PER_HOUR,
}

OPERATION_LIMITS = {
    "storage_repair": MAX_STORAGE_REPAIRS_PER_HOUR,
    "inference": MAX_INFERENCE_REQUESTS_PER_HOUR,
}

# ── Correlated failure detection ────────────────────────────────────────

CORRELATED_FAILURE_WINDOW = 300    # 5 minutes
CORRELATED_FAILURE_THRESHOLD = 3   # 3+ nodes offline triggers safe mode

HEARTBEAT_LOG_PATH = "/opt/nexus/logs/node_heartbeats.jsonl"
BUDGET_LOG_PATH = "/opt/nexus/logs/agent_budget.jsonl"

# Discord webhook for safe mode alerts
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_AGENT_CHAT_WEBHOOK", "")


class AgentBudgetManager:
    """
    Per-agent budget caps with sliding window enforcement and
    correlated failure detection for automatic safe mode.
    """

    def __init__(self):
        self._lock = Lock()
        # wallet → deque of (timestamp, ect_amount)
        self._ect_spending = defaultdict(deque)
        # wallet → {operation → deque of timestamps}
        self._op_counts = defaultdict(lambda: defaultdict(deque))
        # deque of (timestamp, node_id) for failure correlation
        self._node_failures = deque()

    # ── Budget checking ─────────────────────────────────────────────────────

    def check_budget(self, agent_wallet, operation, tier, cost=0):
        """
        Check if an agent is within its budget caps.
        Budget caps are ALWAYS enforced (not toggleable).

        Args:
            agent_wallet: agent's wallet address
            operation: operation type string (e.g., "exec", "inference")
            tier: agent tier ("c_suite", "director", "worker")
            cost: ECT cost of this operation

        Returns:
            bool: True if within budget, False if over budget
        """
        now = time.time()
        cutoff = now - 3600  # 1-hour sliding window

        with self._lock:
            # --- ECT budget check ---
            spending = self._ect_spending[agent_wallet]
            # Evict entries older than 1 hour
            while spending and spending[0][0] < cutoff:
                spending.popleft()

            hourly_spent = sum(amount for _, amount in spending)
            hourly_limit = TIER_LIMITS.get(tier, WORKER_MAX_ECT_PER_HOUR)

            if hourly_spent + cost > hourly_limit:
                log.warning("[BUDGET] %s OVER ECT budget: spent=%d + cost=%d > limit=%d (tier=%s)",
                            agent_wallet[:16], hourly_spent, cost, hourly_limit, tier)
                self._log_event(agent_wallet, operation, "ect_over_budget",
                                spent=hourly_spent, cost=cost, limit=hourly_limit)
                return False

            # --- Operation-specific cap check ---
            op_key = self._operation_category(operation)
            if op_key in OPERATION_LIMITS:
                op_counts = self._op_counts[agent_wallet][op_key]
                while op_counts and op_counts[0] < cutoff:
                    op_counts.popleft()

                if len(op_counts) >= OPERATION_LIMITS[op_key]:
                    log.warning("[BUDGET] %s OVER %s cap: %d/%d per hour",
                                agent_wallet[:16], op_key,
                                len(op_counts), OPERATION_LIMITS[op_key])
                    self._log_event(agent_wallet, operation, "op_over_budget",
                                    count=len(op_counts), limit=OPERATION_LIMITS[op_key])
                    return False

                op_counts.append(now)

            # Record the spend
            if cost > 0:
                spending.append((now, cost))

        return True

    def _operation_category(self, operation):
        """Map operation names to budget category keys."""
        if operation in ("storage_pin", "storage_repair"):
            return "storage_repair"
        if operation == "inference":
            return "inference"
        return operation

    # ── Budget status ───────────────────────────────────────────────────────

    def get_budget_status(self, agent_wallet, tier="worker"):
        """
        Get current budget status for an agent.

        Returns:
            dict: {tier, hourly_spent, hourly_limit, remaining, percentage_used}
        """
        now = time.time()
        cutoff = now - 3600

        with self._lock:
            spending = self._ect_spending.get(agent_wallet, deque())
            hourly_spent = sum(amount for ts, amount in spending if ts >= cutoff)

        hourly_limit = TIER_LIMITS.get(tier, WORKER_MAX_ECT_PER_HOUR)
        remaining = max(0, hourly_limit - hourly_spent)
        pct = (hourly_spent / hourly_limit * 100) if hourly_limit > 0 else 0

        return {
            "tier": tier,
            "hourly_spent": hourly_spent,
            "hourly_limit": hourly_limit,
            "remaining": remaining,
            "percentage_used": round(pct, 1),
        }

    # ── Safe mode ───────────────────────────────────────────────────────────

    def trigger_safe_mode(self, reason):
        """
        Activate safe mode across the entire system.

        Steps:
          1. Pause all circuit breakers
          2. Log to ReasoningLedger
          3. Post to Discord #agent-chat
          4. Require manual resume
        """
        log.critical("[SAFE MODE] ACTIVATING: %s", reason)

        # 1. Pause all circuit breakers via safe mode
        try:
            from circuit_breaker import get_circuit_breaker
            cb = get_circuit_breaker(log_on_chain=False)
            cb.activate_safe_mode(reason, triggered_by="agent_budget")
        except Exception as e:
            log.error("[SAFE MODE] Failed to activate circuit breakers: %s", e)

        # 2. Log to ReasoningLedger
        try:
            if '/opt/nexus' not in sys.path:
                sys.path.insert(0, '/opt/nexus')
            from libnexus import NexusKernel
            kernel = NexusKernel(
                rpc_url="http://10.0.20.3:8545",
                wallet="0x817B0842B208B76A7665948F8D1A0592F9b1e958",
            )
            kernel.log_reasoning(
                f"SAFE MODE ACTIVATED: {reason}",
                "All automated operations paused. Manual resume required.",
            )
        except Exception as e:
            log.warning("[SAFE MODE] On-chain logging failed: %s", e)

        # 3. Post to Discord
        self._post_discord_alert(
            f"\U0001f534 SAFE MODE: {reason}. All automated operations paused. "
            "Manual resume required via dashboard or CLI."
        )

        # 4. Log event
        self._log_event("SYSTEM", "safe_mode", "activated", reason=reason)

    def _post_discord_alert(self, message):
        """Post a safe mode alert to Discord #agent-chat via webhook."""
        if not DISCORD_WEBHOOK_URL:
            log.info("[SAFE MODE] Discord webhook not configured — skipping alert")
            log.info("[SAFE MODE] Would post: %s", message)
            return

        try:
            import requests
            r = requests.post(
                DISCORD_WEBHOOK_URL,
                json={"content": message},
                timeout=10,
            )
            if r.status_code < 300:
                log.info("[SAFE MODE] Discord alert posted")
            else:
                log.warning("[SAFE MODE] Discord alert failed: %d", r.status_code)
        except Exception as e:
            log.warning("[SAFE MODE] Discord post failed: %s", e)

    # ── Correlated failure detection ────────────────────────────────────────

    def check_correlated_failures(self, offline_nodes=None):
        """
        Monitor node heartbeats for correlated failures. If >2 nodes go
        offline within 5 minutes, trigger safe mode.

        Args:
            offline_nodes: optional list of {node_id, timestamp} dicts
                          representing newly-offline nodes. If None, reads
                          from heartbeat log.

        Returns:
            bool: True if safe mode was triggered
        """
        now = time.time()
        cutoff = now - CORRELATED_FAILURE_WINDOW

        if offline_nodes:
            for node in offline_nodes:
                ts = node.get("timestamp", now)
                node_id = node.get("node_id", "unknown")
                self._node_failures.append((ts, node_id))
        else:
            self._read_heartbeat_failures()

        # Evict old entries
        while self._node_failures and self._node_failures[0][0] < cutoff:
            self._node_failures.popleft()

        # Count unique nodes that failed in the window
        recent_nodes = set()
        for ts, node_id in self._node_failures:
            if ts >= cutoff:
                recent_nodes.add(node_id)

        if len(recent_nodes) >= CORRELATED_FAILURE_THRESHOLD:
            minutes = CORRELATED_FAILURE_WINDOW / 60
            reason = (f"Correlated node failure: {len(recent_nodes)} nodes down "
                      f"in {minutes:.0f} min ({', '.join(list(recent_nodes)[:5])})")
            self.trigger_safe_mode(reason)
            # Clear to avoid re-triggering
            self._node_failures.clear()
            return True

        return False

    def _read_heartbeat_failures(self):
        """Read recent heartbeat failures from the log file."""
        if not os.path.exists(HEARTBEAT_LOG_PATH):
            return

        cutoff = time.time() - CORRELATED_FAILURE_WINDOW
        try:
            with open(HEARTBEAT_LOG_PATH, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        ts = entry.get("timestamp", 0)
                        if ts >= cutoff and entry.get("status") == "offline":
                            self._node_failures.append((ts, entry.get("node_id", "unknown")))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass

    # ── Logging ─────────────────────────────────────────────────────────────

    def _log_event(self, wallet, operation, event_type, **kwargs):
        """Append a budget event to the log."""
        entry = {
            "timestamp": time.time(),
            "datetime": datetime.now(timezone.utc).isoformat(),
            "wallet": wallet,
            "operation": operation,
            "event": event_type,
        }
        entry.update(kwargs)

        os.makedirs(os.path.dirname(BUDGET_LOG_PATH), exist_ok=True)
        try:
            with open(BUDGET_LOG_PATH, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as e:
            log.error("Failed to write budget log: %s", e)


# ── Singleton ───────────────────────────────────────────────────────────

_instance = None
_instance_lock = Lock()


def get_budget_manager():
    """Get or create the singleton AgentBudgetManager instance."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = AgentBudgetManager()
        return _instance


# ── Main demo ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s  %(message)s")

    print("=== NEXUS Agent Budget Manager Demo ===\n")

    mgr = AgentBudgetManager()

    # Simulate agents spending ECT
    wallets = {
        "0xCEO_Alice":    "c_suite",
        "0xDir_Bob":      "director",
        "0xWorker_Carol": "worker",
        "0xWorker_Dave":  "worker",
    }

    print("--- Budget caps ---")
    for wallet, tier in wallets.items():
        limit = TIER_LIMITS.get(tier, WORKER_MAX_ECT_PER_HOUR)
        print(f"  {wallet:<20s} tier={tier:<10s} limit={limit} ECT/hr")

    # Simulate spending
    print("\n--- Spending simulation ---")
    test_ops = [
        ("0xWorker_Carol", "exec",      "worker", 5),
        ("0xWorker_Carol", "exec",      "worker", 5),
        ("0xWorker_Carol", "exec",      "worker", 5),
        ("0xWorker_Carol", "exec",      "worker", 5),
        ("0xWorker_Carol", "exec",      "worker", 5),
        ("0xWorker_Carol", "exec",      "worker", 5),   # 30 total — at limit
        ("0xWorker_Carol", "exec",      "worker", 5),   # 35 — OVER budget
        ("0xDir_Bob",      "inference", "director", 10),
        ("0xDir_Bob",      "inference", "director", 10),
        ("0xCEO_Alice",    "exec",      "c_suite", 50),
    ]

    for wallet, op, tier, cost in test_ops:
        allowed = mgr.check_budget(wallet, op, tier, cost)
        status = mgr.get_budget_status(wallet, tier)
        symbol = "OK" if allowed else "BLOCKED"
        print(f"  {wallet:<20s} {op:<12s} cost={cost:>3d}  "
              f"spent={status['hourly_spent']:>3d}/{status['hourly_limit']:>3d}  [{symbol}]")

    # Budget status
    print("\n--- Budget status ---")
    for wallet, tier in wallets.items():
        status = mgr.get_budget_status(wallet, tier)
        print(f"  {wallet:<20s} {status['percentage_used']:5.1f}% used  "
              f"remaining={status['remaining']} ECT")

    # Inference cap test
    print("\n--- Inference cap test (max 50/hr) ---")
    for i in range(52):
        allowed = mgr.check_budget("0xDir_Bob", "inference", "director", 0)
        if not allowed:
            print(f"  Inference #{i+1}: BLOCKED (cap reached)")
            break
    else:
        print("  All 52 allowed (unexpected)")

    # Correlated failure detection
    print("\n--- Correlated failure detection ---")
    now = time.time()
    failures = [
        {"node_id": "nexus-master", "timestamp": now - 60},
        {"node_id": "nexus-ai", "timestamp": now - 30},
    ]
    triggered = mgr.check_correlated_failures(offline_nodes=failures)
    print(f"  2 nodes offline: safe mode triggered = {triggered}")

    failures.append({"node_id": "nexus-storage", "timestamp": now - 10})
    triggered = mgr.check_correlated_failures(offline_nodes=failures)
    print(f"  3 nodes offline: safe mode triggered = {triggered}")

    print("\nDone.")
