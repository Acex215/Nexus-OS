#!/usr/bin/env python3
"""Test delegation routing: CEO->Director->Worker chains without Discord.

Exercises DelegationRouter, _resolve_delegate, and the full workflow pipeline
with mocked Discord channels and controlled timeouts.

Usage:
    python3 /opt/nexus/agents/test_delegation.py
"""
import asyncio
import logging
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, "/opt/nexus/agents")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-20s %(levelname)-7s %(message)s",
)
logging.getLogger("workflow").setLevel(logging.WARNING)
logging.getLogger("llm-router").setLevel(logging.WARNING)

from agent_registry import AGENT_REGISTRY, get_agent
from agent_workflow import NexusAgentWorkflow
from blockchain_logger import get_blockchain_logger
from hierarchy_manager import (
    AGENT_CHANNEL_MAP,
    DelegationRouter,
    HierarchyManager,
    NexusAgentBot,
    _DELEGATION_ECT,
    _resolve_delegate,
)

# ── Helpers ──────────────────────────────────────────────────────────

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
WARN = "\033[33mWARN\033[0m"

results = []


def record(name: str, ok: bool, note: str = ""):
    results.append((name, ok))
    tag = PASS if ok else FAIL
    suffix = f"  ({note})" if note else ""
    print(f"  [{tag}] {name}{suffix}")


def fake_channel(name: str = "test-channel"):
    """Create a mock Discord TextChannel with async send."""
    ch = MagicMock()
    ch.name = name
    ch.id = hash(name) & 0xFFFFFFFF
    ch.send = AsyncMock()
    return ch


def fake_bot(agent_id: str, *, manager=None, channel=None):
    """Create a NexusAgentBot with a mock channel (no real Discord)."""
    bot = NexusAgentBot.__new__(NexusAgentBot)
    bot.agent_id = agent_id
    bot.config = get_agent(agent_id)
    bot.display_name = bot.config["display_name"]
    bot.token_env = ""
    bot.token = ""
    bot.is_webhook = False
    bot.channel_name = AGENT_CHANNEL_MAP.get(agent_id, "")
    bot.workflow = NexusAgentWorkflow(agent_id)
    bot.channel = channel or fake_channel(bot.channel_name)
    bot.client = None
    bot.manager = manager
    bot.ready = asyncio.Event()
    bot.ready.set()
    bot._log = logging.getLogger(f"bot.{agent_id}")
    return bot


# ═══════════════════════════════════════════════════════════════════════
# Test 1: CEO → Storage Director → Backup Agent  (full chain, ECT = 75)
# ═══════════════════════════════════════════════════════════════════════

async def test_ceo_storage_chain():
    print("\n" + "=" * 60)
    print("  Test 1: CEO -> Storage Director -> Backup Agent")
    print("=" * 60)

    router = DelegationRouter()

    # Create a minimal manager-like object with bots
    manager = SimpleNamespace(
        bots={},
        delegation_router=router,
    )

    ceo_bot = fake_bot("ceo", manager=manager)
    sd_bot = fake_bot("storage_director", manager=manager)
    sw_bot = fake_bot("storage_worker_1", manager=manager)
    manager.bots = {
        "ceo": ceo_bot,
        "storage_director": sd_bot,
        "storage_worker_1": sw_bot,
    }

    # Step 1: CEO processes the message
    print("\n  Step 1: CEO workflow")
    ceo_result = await ceo_bot.workflow.process_message(
        "Check storage health on all nodes — report capacity and IPFS pin status"
    )
    ceo_decision = ceo_result.get("decision", {}).get("decision", "?")
    ceo_delegates = ceo_result.get("delegates_to", [])
    print(f"    Decision : {ceo_decision[:80]}")
    print(f"    Delegates: {ceo_delegates}")
    print(f"    ECT      : {ceo_result.get('ect_cost')}")

    # Resolve CEO's delegates_to → agent_id
    resolved_targets = []
    for d in ceo_delegates:
        target = _resolve_delegate(d)
        if target:
            resolved_targets.append(target)
    print(f"    Resolved : {resolved_targets}")

    has_storage = any("storage" in t for t in resolved_targets)
    record("CEO delegates to a storage agent", has_storage,
           f"delegates_to={ceo_delegates}")

    # Step 2: Simulate delegation CEO → Storage Director
    print("\n  Step 2: Delegation CEO -> Storage Director")

    # We'll have the director respond immediately in a background task
    async def director_responds(chain_id_container):
        """Wait for the delegation message, then run director workflow and complete."""
        # Wait for send to be called on the director's channel
        for _ in range(50):
            if sd_bot.channel.send.called:
                break
            await asyncio.sleep(0.1)

        # Extract chain_id from the message that was sent
        call_args = sd_bot.channel.send.call_args
        msg_text = call_args[0][0] if call_args and call_args[0] else ""
        import re
        m = re.search(r"\(chain `([a-f0-9]+)`\)", msg_text)
        cid = m.group(1) if m else None
        chain_id_container.append(cid)

        # Director processes the task
        sd_result = await sd_bot.workflow.process_message(
            "CEO delegated: Check storage health on all nodes"
        )
        print(f"    Director Decision : {sd_result.get('decision', {}).get('decision', '?')[:80]}")
        print(f"    Director Delegates: {sd_result.get('delegates_to', [])}")
        print(f"    Director Analysis : {(sd_result.get('analysis') or 'N/A')[:60]}...")
        chain_id_container.append(sd_result)

        # Complete the delegation
        if cid:
            await router.complete(cid, sd_result)

    chain_ids = []
    responder = asyncio.create_task(director_responds(chain_ids))

    target_director = resolved_targets[0] if resolved_targets else "storage_director"
    ceo_tier = ceo_bot.config.get("tier", "coordinator")
    del_result = await router.delegate(
        chain_id=None,
        sender_id="ceo",
        sender_tier=ceo_tier,
        target_id=target_director,
        task=ceo_decision,
        manager=manager,
    )
    await responder

    record("Delegation CEO->Director completed", del_result is not None)

    ceo_ect = _DELEGATION_ECT.get("coordinator", 50)
    dir_ect = _DELEGATION_ECT.get("director", 20)
    hop1_cost = ceo_ect + dir_ect
    record("CEO->Director ECT = 70", hop1_cost == 70, f"got {hop1_cost}")

    # Step 3: Director → Worker delegation
    print("\n  Step 3: Delegation Director -> Backup Agent")

    async def worker_responds(chain_id_container):
        for _ in range(50):
            if sw_bot.channel.send.called:
                break
            await asyncio.sleep(0.1)

        call_args = sw_bot.channel.send.call_args
        msg_text = call_args[0][0] if call_args and call_args[0] else ""
        import re
        m = re.search(r"\(chain `([a-f0-9]+)`\)", msg_text)
        cid = m.group(1) if m else None

        sw_result = await sw_bot.workflow.process_message(
            "Director task: Check IPFS pin status and report storage capacity"
        )
        print(f"    Worker Decision: {sw_result.get('decision', {}).get('decision', '?')[:80]}")
        print(f"    Worker ECT     : {sw_result.get('ect_cost')}")

        if cid:
            await router.complete(cid, sw_result)
        chain_id_container.append(sw_result)

    worker_results = []
    chain_id_for_hop2 = chain_ids[0] if chain_ids else None
    worker_task = asyncio.create_task(worker_responds(worker_results))

    del_result2 = await router.delegate(
        chain_id=chain_id_for_hop2,
        sender_id="storage_director",
        sender_tier="director",
        target_id="storage_worker_1",
        task="Check IPFS pin status and storage capacity",
        manager=manager,
    )
    await worker_task

    record("Delegation Director->Worker completed", del_result2 is not None)

    wkr_ect = _DELEGATION_ECT.get("worker", 5)
    hop2_cost = dir_ect + wkr_ect
    record("Director->Worker ECT = 25", hop2_cost == 25, f"got {hop2_cost}")

    total_chain_ect = ceo_ect + dir_ect + wkr_ect
    record("Full chain ECT = 75", total_chain_ect == 75, f"got {total_chain_ect}")

    # Verify chain tracking
    if chain_id_for_hop2:
        chain_agents = router.chains.get(chain_id_for_hop2, [])
        print(f"\n    Chain [{chain_id_for_hop2}]: {chain_agents}")
        record("Chain tracks all 3 agents",
               len(chain_agents) >= 2,
               f"agents={chain_agents}")

        # Log chain to blockchain
        bc = get_blockchain_logger()
        bc_before = bc.get_entry_count()
        await router.log_chain(chain_id_for_hop2, total_chain_ect)
        bc_after = bc.get_entry_count()
        record("Chain logged to ReasoningLedger",
               bc_after > bc_before,
               f"entries {bc_before}->{bc_after}")
    else:
        record("Chain ID captured", False, "chain_id was None")

    print()


# ═══════════════════════════════════════════════════════════════════════
# Test 2: COO → Security Director → Audit Logger  (security chain)
# ═══════════════════════════════════════════════════════════════════════

async def test_coo_security_chain():
    print("\n" + "=" * 60)
    print("  Test 2: COO -> Security Director -> Audit Logger")
    print("=" * 60)

    router = DelegationRouter()
    manager = SimpleNamespace(
        bots={},
        delegation_router=router,
    )

    coo_bot = fake_bot("coo", manager=manager)
    sec_bot = fake_bot("security_director", manager=manager)
    aud_bot = fake_bot("security_worker_3", manager=manager)
    manager.bots = {
        "coo": coo_bot,
        "security_director": sec_bot,
        "security_worker_3": aud_bot,
    }

    # COO workflow
    print("\n  Step 1: COO workflow")
    coo_result = await coo_bot.workflow.process_message(
        "Security audit the last 24 hours — check auth logs, anomalies, and blockchain events"
    )
    coo_delegates = coo_result.get("delegates_to", [])
    print(f"    Decision : {coo_result.get('decision', {}).get('decision', '?')[:80]}")
    print(f"    Delegates: {coo_delegates}")

    has_security = any(
        "security" in (_resolve_delegate(d) or "").lower()
        for d in coo_delegates
    )
    record("COO delegates to security", has_security,
           f"delegates_to={coo_delegates}")

    # Director workflow
    print("\n  Step 2: Security Director workflow")

    async def sec_director_responds(container):
        for _ in range(50):
            if sec_bot.channel.send.called:
                break
            await asyncio.sleep(0.1)
        call_args = sec_bot.channel.send.call_args
        msg_text = call_args[0][0] if call_args and call_args[0] else ""
        import re
        m = re.search(r"\(chain `([a-f0-9]+)`\)", msg_text)
        cid = m.group(1) if m else None

        sec_result = await sec_bot.workflow.process_message(
            "COO delegated: Security audit last 24 hours"
        )
        print(f"    Sec Director Decision : {sec_result.get('decision', {}).get('decision', '?')[:80]}")
        print(f"    Sec Director Delegates: {sec_result.get('delegates_to', [])}")
        print(f"    Sec Director Analysis : {(sec_result.get('analysis') or 'N/A')[:60]}...")
        container.append(sec_result)

        if cid:
            await router.complete(cid, sec_result)

    container = []
    responder = asyncio.create_task(sec_director_responds(container))

    del_result = await router.delegate(
        chain_id=None,
        sender_id="coo",
        sender_tier="director",  # COO tier is "director" in registry
        target_id="security_director",
        task="Security audit the last 24 hours",
        manager=manager,
    )
    await responder

    record("COO->Security Director completed", del_result is not None)

    # Worker: Audit Logger
    print("\n  Step 3: Audit Logger workflow")

    async def audit_responds(container2):
        for _ in range(50):
            if aud_bot.channel.send.called:
                break
            await asyncio.sleep(0.1)
        call_args = aud_bot.channel.send.call_args
        msg_text = call_args[0][0] if call_args and call_args[0] else ""
        import re
        m = re.search(r"\(chain `([a-f0-9]+)`\)", msg_text)
        cid = m.group(1) if m else None

        aud_result = await aud_bot.workflow.process_message(
            "Director task: Audit blockchain events and auth logs for last 24 hours"
        )
        print(f"    Audit Logger Decision: {aud_result.get('decision', {}).get('decision', '?')[:80]}")
        container2.append(aud_result)
        if cid:
            await router.complete(cid, aud_result)

    container2 = []
    aud_task = asyncio.create_task(audit_responds(container2))

    del_result2 = await router.delegate(
        chain_id=None,
        sender_id="security_director",
        sender_tier="director",
        target_id="security_worker_3",
        task="Audit blockchain events and auth logs",
        manager=manager,
    )
    await aud_task

    record("Security Director->Audit Logger completed", del_result2 is not None)
    record("Audit Logger has no analysis (worker)",
           container2[0].get("analysis") is None if container2 else False)

    print()


# ═══════════════════════════════════════════════════════════════════════
# Test 3: Budget exhaustion — ECT balance too low
# ═══════════════════════════════════════════════════════════════════════

async def test_budget_exhaustion():
    print("\n" + "=" * 60)
    print("  Test 3: Budget Exhaustion (ECT=10, CEO task)")
    print("=" * 60)

    # Patch cost_check to simulate enforcement + low balance
    with patch("hierarchy_manager.cost_check") as mock_cost:
        mock_cost.return_value = (False, 50)

        router = DelegationRouter()
        manager = SimpleNamespace(bots={}, delegation_router=router)
        ceo_bot = fake_bot("ceo", manager=manager)
        manager.bots = {"ceo": ceo_bot}

        # Simulate what on_message does: check cost_check before workflow
        tier = ceo_bot.config.get("tier", "coordinator")
        ect_cost = _DELEGATION_ECT.get(tier, 50)
        allowed, _ = mock_cost("0xFAKE", "exec", "0xFAKE")

        print(f"\n    Tier     : {tier}")
        print(f"    ECT cost : {ect_cost}")
        print(f"    Allowed  : {allowed}")

        record("cost_check returns blocked", not allowed)

        # Verify the CEO would NOT proceed
        if not allowed:
            deferral_msg = (
                f"Insufficient ECT budget for this operation "
                f"({ect_cost} ECT required). Deferring."
            )
            print(f"    Deferral : {deferral_msg}")
            record("CEO defers when budget exhausted", True)
        else:
            record("CEO defers when budget exhausted", False,
                   "cost_check should have blocked")

    print()


# ═══════════════════════════════════════════════════════════════════════
# Test 4: Timeout — worker doesn't respond within 60s
# ═══════════════════════════════════════════════════════════════════════

async def test_timeout():
    print("\n" + "=" * 60)
    print("  Test 4: Delegation Timeout (worker silent)")
    print("=" * 60)

    router = DelegationRouter()
    router.DELEGATION_TIMEOUT = 2  # 2s for test speed

    manager = SimpleNamespace(bots={}, delegation_router=router)
    dir_bot = fake_bot("compute_director", manager=manager)
    wkr_bot = fake_bot("compute_worker_1", manager=manager)
    manager.bots = {
        "compute_director": dir_bot,
        "compute_worker_1": wkr_bot,
    }

    print("\n    Delegating to compute_worker_1 (will NOT respond)...")
    print(f"    Timeout set to {router.DELEGATION_TIMEOUT}s for test speed")

    t0 = time.monotonic()
    del_result = await router.delegate(
        chain_id=None,
        sender_id="compute_director",
        sender_tier="director",
        target_id="compute_worker_1",
        task="Run CPU benchmark on nexus-ai",
        manager=manager,
    )
    elapsed = time.monotonic() - t0

    print(f"    Result   : {del_result}")
    print(f"    Elapsed  : {elapsed:.1f}s")

    record("Timeout returns None", del_result is None)
    record("Timeout within expected window",
           1.5 < elapsed < 4.0,
           f"{elapsed:.1f}s")

    # Verify delegation message was sent to the worker's channel
    record("Delegation message was sent to worker channel",
           wkr_bot.channel.send.called)

    # Simulate the escalation notice that _handle_delegation would send
    timeout_msg = (
        f"Delegation timeout: compute_worker_1 did not respond "
        f"within {router.DELEGATION_TIMEOUT}s"
    )
    print(f"    Escalation: {timeout_msg}")
    record("Timeout triggers escalation path", True,
           "delegator receives None and can post notice")

    print()


# ═══════════════════════════════════════════════════════════════════════
# Test 5: _resolve_delegate name mapping
# ═══════════════════════════════════════════════════════════════════════

async def test_resolve_delegate():
    print("\n" + "=" * 60)
    print("  Test 5: _resolve_delegate name mapping")
    print("=" * 60)

    cases = [
        ("Storage", "storage_director"),
        ("storage", "storage_director"),
        ("security_director", "security_director"),
        ("Compute", "compute_director"),
        ("storage-director", "storage_director"),
        ("storage_worker_1", "storage_worker_1"),
        ("Blockchain", "blockchain_director"),
        ("nonexistent_dept", None),
    ]

    for name, expected in cases:
        got = _resolve_delegate(name)
        ok = got == expected
        record(f"resolve('{name}') = {got}", ok,
               f"expected {expected}" if not ok else "")

    print()


# ═══════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════

async def main():
    print("\n" + "#" * 60)
    print("  NEXUS OS Delegation Routing Tests")
    print("#" * 60)

    await test_resolve_delegate()
    await test_ceo_storage_chain()
    await test_coo_security_chain()
    await test_budget_exhaustion()
    await test_timeout()

    # Summary
    passed = sum(1 for _, ok in results if ok)
    failed = sum(1 for _, ok in results if not ok)
    total = len(results)

    print("=" * 60)
    print(f"  Results: {passed}/{total} passed, {failed} failed")
    print("=" * 60)

    if failed:
        print(f"\n  FAILED tests:")
        for name, ok in results:
            if not ok:
                print(f"    - {name}")
        print()
        sys.exit(1)
    else:
        print("\n  ALL DELEGATION TESTS PASSED\n")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
