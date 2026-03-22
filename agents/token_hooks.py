"""ECT/RST cost check hooks for NEXUS node operations.

When ENFORCEMENT_ENABLED=true: operations with insufficient ECT are blocked.
When ENFORCEMENT_ENABLED=false (default): operations are logged but never blocked.
Both modes write real on-chain transactions when the blockchain is reachable.
"""

import logging
import os
import hashlib

log = logging.getLogger("token_hooks")

ENFORCEMENT_ENABLED = os.environ.get("ENFORCEMENT_ENABLED", "false").lower() == "true"

OPERATION_COSTS = {
    "exec": 5, "inference": 10, "storage_pin": 3,
    "storage_unpin": 1, "storage_cat": 2, "storage_stat": 1,
    "storage_ls": 1, "health": 0,
}

# RST rewards/penalties
RST_SUCCESS_REWARD = 1
RST_FAILURE_PENALTY = 2
RST_TIMEOUT_PENALTY = 5

# Lazy-init TokenClient (don't crash on import if blockchain unreachable)
_token_client = None
_DEPLOYER = "0x817B0842B208B76A7665948F8D1A0592F9b1e958"

def _get_client():
    global _token_client
    if _token_client is None:
        try:
            import sys
            if '/opt/nexus' not in sys.path:
                sys.path.insert(0, '/opt/nexus')
            from libnexus.token_client import TokenClient
            _token_client = TokenClient(wallet=_DEPLOYER)
            log.info("TokenClient connected to %s", _token_client.address)
        except Exception as e:
            log.warning("TokenClient unavailable: %s — falling back to logging only", e)
    return _token_client


def _make_task_id(operation, node_wallet):
    """Create a deterministic bytes32 task ID from operation + node + timestamp."""
    import time
    raw = f"{operation}:{node_wallet}:{time.time()}".encode()
    return hashlib.sha256(raw).digest()


def cost_check(requester_wallet, operation, node_wallet):
    """Check if requester has enough ECT for this operation.
    Returns (allowed: bool, cost: int).

    When ENFORCEMENT_ENABLED=true: blocks if insufficient ECT.
    When ENFORCEMENT_ENABLED=false: always allows, but still logs real balances
    and spends real ECT if blockchain is reachable.
    """
    cost = OPERATION_COSTS.get(operation, 1)
    if cost == 0:
        return (True, 0)

    client = _get_client()
    if client is None:
        log.info("[ECT] %s costs %d ECT — blockchain unavailable, ALLOWED", operation, cost)
        return (True, cost)

    try:
        balance = client.get_ect_balance(requester_wallet)

        if balance < cost:
            if ENFORCEMENT_ENABLED:
                log.warning("[ECT] %s costs %d ECT, balance=%d — BLOCKED",
                           operation, cost, balance)
                return (False, cost)
            else:
                log.info("[ECT] %s costs %d ECT, balance=%d — ALLOWED (enforcement off)",
                        operation, cost, balance)
                return (True, cost)

        # Spend the ECT on-chain
        task_id = _make_task_id(operation, node_wallet)
        client.spend_ect(requester_wallet, cost, task_id)
        new_balance = client.get_ect_balance(requester_wallet)
        log.info("[ECT] %s: spent %d ECT (balance: %d → %d)",
                operation, cost, balance, new_balance)
        return (True, cost)

    except Exception as e:
        log.warning("[ECT] %s: contract call failed (%s) — ALLOWED (fallback)", operation, e)
        return (True, cost)


def record_reputation(node_wallet, operation, success, duration_ms):
    """Record operation outcome as RST on-chain.
    Success: +RST_SUCCESS_REWARD, Failure: -RST_FAILURE_PENALTY
    """
    client = _get_client()
    if client is None:
        log.info("[RST] %s %s — blockchain unavailable, skipped",
                operation, "SUCCESS" if success else "FAILURE")
        return

    try:
        if success:
            reason = f"{operation} completed in {duration_ms}ms"
            client.earn_rst(node_wallet, RST_SUCCESS_REWARD, reason)
            log.info("[RST] +%d RST to %s: %s", RST_SUCCESS_REWARD, node_wallet[:10], reason)
        else:
            penalty = RST_TIMEOUT_PENALTY if duration_ms > 30000 else RST_FAILURE_PENALTY
            reason = f"{operation} failed after {duration_ms}ms"
            client.slash_rst(node_wallet, penalty, reason)
            log.info("[RST] -%d RST from %s: %s", penalty, node_wallet[:10], reason)
    except Exception as e:
        log.warning("[RST] contract call failed: %s — skipped", e)
