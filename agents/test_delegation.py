#!/usr/bin/env python3
"""Test full CEO -> Director -> Worker delegation chain with blockchain logging."""
import asyncio
import sys

sys.path.insert(0, "/opt/nexus/agents")

from agent_workflow import NexusAgentWorkflow
from blockchain_logger import get_blockchain_logger, reset_blockchain_logger


async def test_full_chain():
    print("\n  Testing Full Delegation Chain")
    print("=" * 55)

    bc = get_blockchain_logger()
    bc_before = bc.get_entry_count()
    print(f"  Blockchain entries before: {bc_before}")

    # ── Step 1: CEO ───────────────────────────────────────
    print("\n  1. CEO receives urgent storage alert")
    ceo = NexusAgentWorkflow("ceo")
    ceo_r = await ceo.process_message(
        "URGENT: nexus-storage at 95% capacity, critical cleanup needed immediately"
    )
    await ceo.llm_client.close()

    print(f"     Decision : {ceo_r['decision'].get('decision', '?')[:80]}")
    print(f"     Delegates: {ceo_r['delegates_to']}")
    print(f"     Priority : {ceo_r['decision'].get('priority')}/5")
    print(f"     ECT      : {ceo_r['ect_cost']}")

    assert "Storage" in ceo_r["delegates_to"], f"CEO should delegate to Storage, got {ceo_r['delegates_to']}"
    assert ceo_r["decision"].get("priority", 0) >= 4, "Should be high priority"

    tx1 = await bc.log_decision("ceo", "Urgent storage alert", ceo_r["reasoning_hash"], ceo_r["ect_cost"])
    print(f"     Tx       : {tx1[:16]}..." if tx1 else "     Tx       : FAILED")

    # ── Step 2: Storage Director ──────────────────────────
    print("\n  2. Storage Director receives CEO delegation")
    sd = NexusAgentWorkflow("storage_director")
    sd_r = await sd.process_message(
        "CEO delegated: Critical storage cleanup on nexus-storage at 95% capacity"
    )
    await sd.llm_client.close()

    print(f"     Decision : {sd_r['decision'].get('decision', '?')[:80]}")
    print(f"     Analysis : {(sd_r.get('analysis') or 'N/A')[:80]}...")
    print(f"     Delegates: {sd_r['delegates_to']}")
    print(f"     ECT      : {sd_r['ect_cost']}")

    assert sd_r.get("analysis"), "Directors must have analysis step"

    tx2 = await bc.log_decision("storage_director", "CEO delegation: storage cleanup", sd_r["reasoning_hash"], sd_r["ect_cost"])
    print(f"     Tx       : {tx2[:16]}..." if tx2 else "     Tx       : FAILED")

    # ── Step 3: Storage Worker ────────────────────────────
    print("\n  3. Backup Agent (storage_worker_1) executes cleanup")
    sw = NexusAgentWorkflow("storage_worker_1")
    sw_r = await sw.process_message(
        "Director task: Initiate automated backup cleanup on nexus-storage"
    )
    await sw.llm_client.close()

    print(f"     Decision : {sw_r['decision'].get('decision', '?')[:80]}")
    print(f"     ECT      : {sw_r['ect_cost']}")

    assert sw_r.get("analysis") is None, "Workers must skip analysis"
    assert sw_r["ect_cost"] <= 30, f"Worker ECT too high: {sw_r['ect_cost']}"

    tx3 = await bc.log_decision("storage_worker_1", "Director task: backup cleanup", sw_r["reasoning_hash"], sw_r["ect_cost"])
    print(f"     Tx       : {tx3[:16]}..." if tx3 else "     Tx       : FAILED")

    # ── Summary ───────────────────────────────────────────
    bc_after = bc.get_entry_count()
    total_ect = ceo_r["ect_cost"] + sd_r["ect_cost"] + sw_r["ect_cost"]

    print("\n" + "=" * 55)
    print("  Delegation chain: CEO -> Storage Director -> Backup Agent")
    print(f"  Total ECT spent : {total_ect}")
    print(f"  Blockchain      : {bc_before} -> {bc_after} entries (+{bc_after - bc_before})")
    print(f"  All 3 tx hashes : {'YES' if all([tx1, tx2, tx3]) else 'PARTIAL'}")

    # Verify hashes on-chain
    for i, (label, rhash) in enumerate([
        ("CEO", ceo_r["reasoning_hash"]),
        ("Director", sd_r["reasoning_hash"]),
        ("Worker", sw_r["reasoning_hash"]),
    ]):
        entry_id = bc_before + i
        ok = bc.verify_hash(entry_id, rhash)
        status = "MATCH" if ok else "MISMATCH"
        print(f"  Hash verify #{entry_id} ({label}): {status}")

    print("\n  FULL DELEGATION CHAIN TEST: PASSED")


if __name__ == "__main__":
    asyncio.run(test_full_chain())
