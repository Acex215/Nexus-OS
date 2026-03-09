#!/usr/bin/env python3
"""
NEXUS OS Block Performance Verification
========================================
Measures block times, verifies smart contracts, tests agent tx submission,
and collects system resource usage across all validators.

Works with both period=5 (current production) and period=0 (on-demand sealing).
"""
import json
import subprocess
import statistics
import sys
import time

sys.path.insert(0, "/opt/nexus/agents")

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

# ── Configuration ────────────────────────────────────────────────
VALIDATORS = {
    "nexus-master":  {"ip": "10.0.20.3", "rpc": 8545},
    "nexus-ai":      {"ip": "10.0.20.4", "rpc": 8545},
    "nexus-storage": {"ip": "10.0.20.11", "rpc": 8545},
}
ADMIN_NODE = {"name": "nexus-admin", "ip": "10.0.10.5"}

CONTRACT_ADDR = "0x0317451264E1de1A0696A81f6141e72E58686DE4"  # ReasoningLedger
RESOURCE_MGR  = "0x7E7f5e6cd9d7d485eeFa4Ec3Fb211705A3A8c6C6"  # ResourceManager
DEPLOYER      = "0x817B0842B208B76A7665948F8D1A0592F9b1e958"

MONITOR_BLOCKS = 30   # How many blocks to observe
SEP = "=" * 60


def connect(ip, port=8545):
    """Connect to a Geth node with PoA middleware."""
    w3 = Web3(Web3.HTTPProvider(f"http://{ip}:{port}", request_kwargs={"timeout": 10}))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def ssh_cmd(host, cmd):
    """Run a command on a remote host via SSH."""
    result = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5", host, cmd],
        capture_output=True, text=True, timeout=15,
    )
    return result.stdout.strip(), result.returncode


# ══════════════════════════════════════════════════════════════════
# TASK 1: Monitor block production
# ══════════════════════════════════════════════════════════════════
def task1_monitor_blocks(w3):
    print(f"\n{SEP}")
    print("  TASK 1: Block Production Monitoring")
    print(SEP)

    current = w3.eth.block_number
    clique_config = w3.eth.get_block(0).proofOfAuthorityData
    genesis_block = w3.eth.get_block(0)

    # Detect period from recent block intervals
    print(f"  Current block   : {current}")
    print(f"  Chain ID        : {w3.eth.chain_id}")

    # Get the clique period from the genesis config via RPC
    # We'll infer it from actual block timestamps
    blocks = []
    start = max(1, current - MONITOR_BLOCKS)
    for bn in range(start, current + 1):
        blk = w3.eth.get_block(bn)
        blocks.append({
            "number": blk.number,
            "timestamp": blk.timestamp,
            "tx_count": len(blk.transactions),
            "gas_used": blk.gasUsed,
            "miner": blk.miner,
        })

    print(f"  Blocks analyzed : {len(blocks)} (#{blocks[0]['number']}-#{blocks[-1]['number']})")

    return blocks


# ══════════════════════════════════════════════════════════════════
# TASK 2: Calculate statistics
# ══════════════════════════════════════════════════════════════════
def task2_statistics(blocks):
    print(f"\n{SEP}")
    print("  TASK 2: Block Time Statistics")
    print(SEP)

    intervals = []
    for i in range(1, len(blocks)):
        diff = blocks[i]["timestamp"] - blocks[i - 1]["timestamp"]
        intervals.append(diff)

    if not intervals:
        print("  [FAIL] Not enough blocks to compute intervals")
        return False

    avg = statistics.mean(intervals)
    med = statistics.median(intervals)
    mn  = min(intervals)
    mx  = max(intervals)
    sd  = statistics.stdev(intervals) if len(intervals) > 1 else 0.0

    # Count empty vs non-empty blocks
    empty = sum(1 for b in blocks if b["tx_count"] == 0)
    non_empty = len(blocks) - empty

    # Blocks per minute (based on actual elapsed time)
    total_time = blocks[-1]["timestamp"] - blocks[0]["timestamp"]
    bpm = (len(blocks) - 1) / (total_time / 60) if total_time > 0 else 0

    # Growth estimate (per day)
    # Rough: each block ~74KB on disk (from earlier measurement)
    growth_mb_day = bpm * 60 * 24 * 0.074  # MB/day

    print(f"  Average block time : {avg:.2f}s")
    print(f"  Median block time  : {med:.2f}s")
    print(f"  Std deviation      : {sd:.3f}s")
    print(f"  Min / Max          : {mn}s / {mx}s")
    print(f"  Blocks per minute  : {bpm:.1f}")
    print(f"  Blocks per hour    : {bpm * 60:.0f}")
    print(f"  Blocks per day     : {bpm * 60 * 24:.0f}")
    print(f"  Empty blocks       : {empty}/{len(blocks)}")
    print(f"  Non-empty blocks   : {non_empty}/{len(blocks)}")
    print(f"  Est. growth/day    : {growth_mb_day:.0f} MB")
    print(f"  Total time span    : {total_time}s")

    # Determine mode
    if avg < 1:
        mode = "ON-DEMAND (period=0)"
    elif 4.5 <= avg <= 5.5:
        mode = "FIXED (period=5)"
    else:
        mode = f"UNKNOWN (avg={avg:.2f}s)"
    print(f"\n  Detected mode      : {mode}")

    return {
        "avg": avg, "median": med, "stdev": sd,
        "min": mn, "max": mx, "bpm": bpm,
        "mode": mode, "empty": empty, "total": len(blocks),
        "growth_mb_day": growth_mb_day,
    }


# ══════════════════════════════════════════════════════════════════
# TASK 3: Verify smart contract functionality
# ══════════════════════════════════════════════════════════════════
def task3_smart_contracts(w3):
    print(f"\n{SEP}")
    print("  TASK 3: Smart Contract Verification")
    print(SEP)

    results = {}

    # ReasoningLedger
    code = w3.eth.get_code(Web3.to_checksum_address(CONTRACT_ADDR))
    if len(code) > 2:  # '0x' means empty
        print(f"  [OK]  ReasoningLedger at {CONTRACT_ADDR[:18]}... ({len(code)} bytes)")
        results["ReasoningLedger"] = True
    else:
        print(f"  [FAIL] ReasoningLedger not found at {CONTRACT_ADDR}")
        results["ReasoningLedger"] = False

    # Read entry count from ReasoningLedger
    try:
        from blockchain_logger import get_blockchain_logger, reset_blockchain_logger
        reset_blockchain_logger()
        bc = get_blockchain_logger()
        count = bc.get_entry_count()
        print(f"  [OK]  ReasoningLedger entries: {count}")
        results["entry_count"] = count

        if count > 0:
            latest = bc.get_latest_entry()
            if latest:
                print(f"         Latest decision: {latest['decision'][:60]}...")
                results["latest_entry"] = True
    except Exception as e:
        print(f"  [WARN] Could not read entry count: {e}")

    # Check deployer balance
    balance = w3.eth.get_balance(Web3.to_checksum_address(DEPLOYER))
    eth = w3.from_wei(balance, "ether")
    print(f"  [OK]  Deployer balance: {eth:.4f} ETH")
    results["deployer_balance"] = float(eth)

    return results


# ══════════════════════════════════════════════════════════════════
# TASK 4: Test AI agent transaction submission
# ══════════════════════════════════════════════════════════════════
def task4_agent_transaction(w3):
    print(f"\n{SEP}")
    print("  TASK 4: AI Agent Transaction Test")
    print(SEP)

    import asyncio
    from blockchain_logger import get_blockchain_logger, reset_blockchain_logger
    import hashlib

    reset_blockchain_logger()
    bc = get_blockchain_logger()

    if not bc.is_connected():
        print("  [FAIL] BlockchainLogger cannot connect to Geth")
        return {"submitted": False}

    before_count = bc.get_entry_count()
    before_block = w3.eth.block_number

    # Submit a test decision
    reasoning = "Verification test: measuring block time performance and agent tx submission"
    reasoning_hash = hashlib.sha256(reasoning.encode()).hexdigest()

    print(f"  Submitting test transaction...")
    t_start = time.monotonic()

    tx_hash = asyncio.get_event_loop().run_until_complete(
        bc.log_decision("verification_test", "Fast block verification", reasoning_hash, 5)
    )

    t_elapsed = time.monotonic() - t_start

    if tx_hash:
        after_count = bc.get_entry_count()
        after_block = w3.eth.block_number
        print(f"  [OK]  Transaction submitted")
        print(f"         Tx hash     : {tx_hash[:20]}...")
        print(f"         Confirm time: {t_elapsed*1000:.0f}ms")
        print(f"         Block       : {before_block} -> {after_block}")
        print(f"         Entries     : {before_count} -> {after_count}")

        # Verify the entry on-chain
        ok = bc.verify_hash(after_count - 1, reasoning_hash)
        print(f"         Hash verify : {'MATCH' if ok else 'MISMATCH'}")

        return {
            "submitted": True,
            "tx_hash": tx_hash,
            "confirm_ms": t_elapsed * 1000,
            "hash_verified": ok,
        }
    else:
        print(f"  [FAIL] Transaction failed")
        return {"submitted": False}


# ══════════════════════════════════════════════════════════════════
# TASK 5: System resource usage
# ══════════════════════════════════════════════════════════════════
def task5_resources():
    print(f"\n{SEP}")
    print("  TASK 5: System Resource Usage")
    print(SEP)

    results = {}

    for name, info in VALIDATORS.items():
        ip = info["ip"]
        print(f"\n  --- {name} ({ip}) ---")

        # Get geth process stats
        out, rc = ssh_cmd(name, "ps aux | grep '[g]eth' | head -1")
        if rc == 0 and out:
            parts = out.split()
            cpu = parts[2] if len(parts) > 2 else "?"
            mem = parts[3] if len(parts) > 3 else "?"
            rss = parts[5] if len(parts) > 5 else "?"
            print(f"    CPU     : {cpu}%")
            print(f"    MEM     : {mem}%")
            print(f"    RSS     : {int(rss)//1024}MB" if rss.isdigit() else f"    RSS     : {rss}")
        else:
            print(f"    [WARN] Cannot read geth process stats")

        # Chaindata size
        out, rc = ssh_cmd(name, "du -sh /opt/nexus/blockchain/data/geth/chaindata/ 2>/dev/null || du -sh /opt/nexus/blockchain/chaindata/ 2>/dev/null")
        if rc == 0 and out:
            print(f"    Chain   : {out.split()[0]}")

        # Disk space
        out, rc = ssh_cmd(name, "df -h / | tail -1")
        if rc == 0 and out:
            parts = out.split()
            print(f"    Disk    : {parts[2]} used / {parts[1]} total ({parts[4]})")

        # System load
        out, rc = ssh_cmd(name, "uptime")
        if rc == 0 and out:
            load_part = out.split("load average:")[1].strip() if "load average:" in out else "?"
            print(f"    Load    : {load_part}")

        # Memory
        out, rc = ssh_cmd(name, "free -m | grep Mem")
        if rc == 0 and out:
            parts = out.split()
            total = parts[1] if len(parts) > 1 else "?"
            used  = parts[2] if len(parts) > 2 else "?"
            print(f"    RAM     : {used}MB / {total}MB")

        # Peer count
        try:
            w3 = connect(ip)
            if w3.is_connected():
                peers = w3.net.peer_count
                block = w3.eth.block_number
                print(f"    Peers   : {peers}")
                print(f"    Block   : {block}")
                results[name] = {"online": True, "peers": peers, "block": block}
            else:
                print(f"    [FAIL] Cannot connect to RPC")
                results[name] = {"online": False}
        except Exception as e:
            print(f"    [FAIL] RPC error: {e}")
            results[name] = {"online": False}

    # Check block sync across validators
    online = {k: v for k, v in results.items() if v.get("online")}
    if len(online) >= 2:
        blocks = [v["block"] for v in online.values()]
        diff = max(blocks) - min(blocks)
        print(f"\n  Block sync delta: {diff} blocks across {len(online)} validators")
        if diff <= 2:
            print(f"  [OK]  Validators in sync")
        else:
            print(f"  [WARN] Validators out of sync by {diff} blocks")

    return results


# ══════════════════════════════════════════════════════════════════
# TASK 6: Confirmation latency benchmark (live)
# ══════════════════════════════════════════════════════════════════
def task6_confirmation_benchmark(w3):
    print(f"\n{SEP}")
    print("  TASK 6: Live Confirmation Latency (10 transactions)")
    print(SEP)

    latencies = []
    for i in range(10):
        nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(DEPLOYER))
        t0 = time.monotonic()

        tx_hash = w3.eth.send_transaction({
            "from": Web3.to_checksum_address(DEPLOYER),
            "to": Web3.to_checksum_address("0x0000000000000000000000000000000000000001"),
            "value": w3.to_wei(0.0001, "ether"),
            "gas": 21000,
            "gasPrice": w3.to_wei(1, "gwei"),
            "nonce": nonce,
        })

        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
        elapsed = time.monotonic() - t0
        latencies.append(elapsed)
        print(f"    Tx {i+1:2d}: {elapsed*1000:.0f}ms  (block #{receipt.blockNumber})")

    avg = statistics.mean(latencies)
    med = statistics.median(latencies)
    print(f"\n  Mean latency   : {avg*1000:.0f}ms")
    print(f"  Median latency : {med*1000:.0f}ms")
    print(f"  Min / Max      : {min(latencies)*1000:.0f}ms / {max(latencies)*1000:.0f}ms")

    return {"mean_ms": avg * 1000, "median_ms": med * 1000, "latencies": latencies}


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════
def main():
    print()
    print(SEP)
    print("  NEXUS OS Block Performance Verification")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(SEP)

    # Connect to primary validator
    w3 = connect("10.0.20.3")
    if not w3.is_connected():
        print("\n  [FATAL] Cannot connect to nexus-master:8545")
        sys.exit(1)

    # Run all tasks
    blocks = task1_monitor_blocks(w3)
    stats = task2_statistics(blocks)
    contracts = task3_smart_contracts(w3)
    agent_tx = task4_agent_transaction(w3)
    resources = task5_resources()
    latency = task6_confirmation_benchmark(w3)

    # ── Final Summary ────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  FINAL SUMMARY")
    print(SEP)

    checks = []

    # Block production
    if stats:
        checks.append(("Block production", True))
        print(f"  Block mode         : {stats['mode']}")
        print(f"  Avg block time     : {stats['avg']:.2f}s")
        print(f"  Blocks/minute      : {stats['bpm']:.1f}")
        print(f"  Empty block ratio  : {stats['empty']}/{stats['total']}")
        print(f"  Est. growth/day    : {stats['growth_mb_day']:.0f} MB")
    else:
        checks.append(("Block production", False))

    # Smart contracts
    rl_ok = contracts.get("ReasoningLedger", False)
    checks.append(("Smart contracts", rl_ok))
    print(f"  ReasoningLedger    : {'accessible' if rl_ok else 'MISSING'}")
    print(f"  On-chain entries   : {contracts.get('entry_count', '?')}")

    # Agent tx
    tx_ok = agent_tx.get("submitted", False)
    checks.append(("Agent transactions", tx_ok))
    print(f"  Agent tx test      : {'PASSED' if tx_ok else 'FAILED'}")
    if tx_ok:
        print(f"  Agent tx confirm   : {agent_tx['confirm_ms']:.0f}ms")
        print(f"  Hash verification  : {'MATCH' if agent_tx.get('hash_verified') else 'MISMATCH'}")

    # Peer connectivity
    online_count = sum(1 for v in resources.values() if isinstance(v, dict) and v.get("online"))
    checks.append(("Peer connectivity", online_count >= 2))
    print(f"  Validators online  : {online_count}/3")

    # Confirmation latency
    mean_lat = latency.get("mean_ms", 99999)
    checks.append(("Confirmation latency", mean_lat < 10000))
    print(f"  Live confirm avg   : {mean_lat:.0f}ms")

    # Overall
    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)

    print(f"\n  Results: {passed}/{total} checks passed")
    for name, ok in checks:
        print(f"    {'[OK]  ' if ok else '[FAIL]'} {name}")

    if passed == total:
        print(f"\n  STATUS: ALL SYSTEMS OPERATIONAL")
    else:
        print(f"\n  STATUS: ISSUES DETECTED — review above")

    print(SEP)
    return passed == total


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
