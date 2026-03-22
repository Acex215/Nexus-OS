"""ECT/RST cost check hooks for NEXUS node operations.

These hooks will be wired to the real token contracts in a future phase.
For now they always allow every operation and log what WOULD be charged.
"""

import logging

OPERATION_COSTS = {
    "exec":          5,   # ECT cost for running a command on a node
    "inference":    10,   # ECT cost for an inference request
    "storage_pin":   3,   # ECT cost for pinning to IPFS
    "storage_unpin": 1,
    "storage_cat":   2,
    "storage_stat":  1,
    "storage_ls":    1,
    "health":        0,   # health checks are free
}


def cost_check(requester_wallet: str, operation: str, node_wallet: str) -> tuple:
    """Check if requester has enough ECT for this operation.

    Returns (allowed: bool, cost: int).
    Currently always allows — will enforce when ECT contracts are deployed.
    """
    cost = OPERATION_COSTS.get(operation, 1)
    # TODO: query TokenManager contract for requester's ECT balance
    # TODO: if balance < cost, return (False, cost)
    req_display  = requester_wallet[:10] if len(requester_wallet) >= 10 else requester_wallet
    node_display = node_wallet[:10]      if len(node_wallet)      >= 10 else node_wallet
    logging.info(
        "[ECT HOOK] %s on %s... costs %d ECT "
        "(requester: %s...) — ALLOWED (enforcement disabled)",
        operation, node_display, cost, req_display,
    )
    return (True, cost)


def record_reputation(node_wallet: str, operation: str, success: bool, duration_ms: int) -> None:
    """Record operation outcome for RST reputation scoring.

    Currently logs only — will update RST contract when deployed.
    Success: +1 RST, Failure: -2 RST, Timeout: -5 RST
    """
    # TODO: update RST balance on-chain
    outcome      = "SUCCESS" if success else "FAILURE"
    node_display = node_wallet[:10] if len(node_wallet) >= 10 else node_wallet
    logging.info(
        "[RST HOOK] %s... %s %s (%dms) — reputation update pending",
        node_display, operation, outcome, duration_ms,
    )
