"""Tests for blockchain_logger — ReasoningLedger integration."""
import asyncio
import pytest
import pytest_asyncio

from blockchain_logger import BlockchainLogger, get_blockchain_logger, reset_blockchain_logger


# ── Fixture ───────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def bc():
    reset_blockchain_logger()
    bl = get_blockchain_logger()
    yield bl
    reset_blockchain_logger()


# ── 1. Connection ─────────────────────────────────────────────────────

def test_connection(bc):
    """BlockchainLogger should connect to Geth on nexus-master."""
    assert bc.is_connected(), "Should be connected to Geth RPC"
    assert bc.wallet == "0x817B0842B208B76A7665948F8D1A0592F9b1e958"
    assert bc.contract_address == "0x0317451264E1de1A0696A81f6141e72E58686DE4"


# ── 2. Entry count ────────────────────────────────────────────────────

def test_entry_count(bc):
    """Should return a non-negative entry count."""
    count = bc.get_entry_count()
    assert count >= 0, f"Entry count should be >= 0, got {count}"
    print(f"\n  Current entry count: {count}")


# ── 3. Log decision on-chain ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_log_decision(bc):
    """Log a decision and verify it appears on-chain."""
    count_before = bc.get_entry_count()

    tx_hash = await bc.log_decision(
        agent_id="test_agent",
        task="Test task for blockchain logger",
        reasoning_hash="b" * 64,
        ect_cost=10,
    )

    assert tx_hash is not None, "Transaction should succeed"
    assert len(tx_hash) == 64, f"TX hash should be 64 hex chars, got {len(tx_hash)}"

    count_after = bc.get_entry_count()
    assert count_after == count_before + 1, (
        f"Entry count should increase by 1: {count_before} -> {count_after}"
    )
    print(f"\n  TX: {tx_hash[:32]}…")
    print(f"  Entries: {count_before} -> {count_after}")


# ── 4. Read entry back ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_entry(bc):
    """Log an entry and read it back."""
    test_hash = "c" * 64
    await bc.log_decision("read_test", "Read test task", test_hash, 5)

    entry = bc.get_latest_entry()
    assert entry is not None, "Should get latest entry"
    assert entry["decision"].startswith("read_test:"), (
        f"Decision should start with agent_id: {entry['decision']}"
    )
    assert entry["reasoning"] == test_hash, (
        f"On-chain hash mismatch: {entry['reasoning']} != {test_hash}"
    )
    assert entry["timestamp"] > 0, "Timestamp should be positive"
    print(f"\n  Entry: {entry}")


# ── 5. Verify hash ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_hash(bc):
    """verify_hash should return True for matching hashes."""
    test_hash = "d" * 64
    await bc.log_decision("verify_test", "Verify hash test", test_hash, 3)

    entry_id = bc.get_entry_count() - 1
    assert bc.verify_hash(entry_id, test_hash), "Hash should match"
    assert not bc.verify_hash(entry_id, "e" * 64), "Wrong hash should not match"
    print(f"\n  Entry {entry_id}: hash verified")


# ── 6. Full pipeline: workflow -> blockchain ──────────────────────────

@pytest.mark.asyncio
async def test_full_pipeline(bc):
    """Process a message through CEO workflow and log to blockchain."""
    from agent_workflow import NexusAgentWorkflow

    w = NexusAgentWorkflow("ceo")
    result = await w.process_message("Network latency is high on nexus-ai")
    await w.llm_client.close()

    reasoning_hash = result["reasoning_hash"]
    assert len(reasoning_hash) == 64

    tx_hash = await bc.log_decision(
        agent_id="ceo",
        task="Network latency is high on nexus-ai",
        reasoning_hash=reasoning_hash,
        ect_cost=result["ect_cost"],
    )

    assert tx_hash is not None, "Blockchain log should succeed"

    # Verify on-chain
    entry = bc.get_latest_entry()
    assert entry["reasoning"] == reasoning_hash, "On-chain hash should match workflow hash"
    print(f"\n  Workflow hash: {reasoning_hash[:32]}…")
    print(f"  On-chain:     {entry['reasoning'][:32]}…")
    print(f"  TX: {tx_hash[:32]}…")


# ── 7. Pending queue ─────────────────────────────────────────────────

def test_pending_queue(bc):
    """Pending logs list should start empty."""
    assert len(bc.pending_logs) == 0, "Should start with no pending logs"


# ── CLI runner ────────────────────────────────────────────────────────

if __name__ == "__main__":
    async def main():
        reset_blockchain_logger()
        bc = get_blockchain_logger()

        print("1. Connection…")
        test_connection(bc)
        print("   PASSED")

        print("2. Entry count…")
        test_entry_count(bc)
        print("   PASSED")

        print("3. Log decision…")
        await test_log_decision(bc)
        print("   PASSED")

        print("4. Get entry…")
        await test_get_entry(bc)
        print("   PASSED")

        print("5. Verify hash…")
        await test_verify_hash(bc)
        print("   PASSED")

        print("6. Full pipeline…")
        await test_full_pipeline(bc)
        print("   PASSED")

        print("7. Pending queue…")
        test_pending_queue(bc)
        print("   PASSED")

        print(f"\nAll 7 blockchain logger tests passed")
        print(f"Total on-chain entries: {bc.get_entry_count()}")

    asyncio.run(main())
