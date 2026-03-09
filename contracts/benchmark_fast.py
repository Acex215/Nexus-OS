#!/usr/bin/env python3
"""Benchmark period=0 (on-demand sealing) on nexus-master test chain."""
import time
import statistics
from web3 import Web3

RPC = "http://10.0.20.3:8547"
WALLET = "0x817B0842B208B76A7665948F8D1A0592F9b1e958"
TARGET = "0x0000000000000000000000000000000000000001"  # burn address
TX_COUNT = 100

w3 = Web3(Web3.HTTPProvider(RPC))
from web3.middleware import ExtraDataToPOAMiddleware
w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
assert w3.is_connected(), "Cannot connect to test geth"

print(f"Connected to test chain (block {w3.eth.block_number}, chainId {w3.eth.chain_id})")
print(f"Wallet balance: {w3.from_wei(w3.eth.get_balance(WALLET), 'ether')} ETH")
print(f"Sending {TX_COUNT} transactions...\n")

# ── Send transactions and measure confirmation time ──────────────
tx_times = []       # time from send to receipt
block_numbers = []  # which block each tx landed in

t_start = time.monotonic()
nonce = w3.eth.get_transaction_count(WALLET)

for i in range(TX_COUNT):
    t_send = time.monotonic()

    tx_hash = w3.eth.send_transaction({
        "from": WALLET,
        "to": TARGET,
        "value": w3.to_wei(0.001, "ether"),
        "gas": 21000,
        "gasPrice": w3.to_wei(1, "gwei"),
        "nonce": nonce,
    })

    nonce += 1
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    t_confirm = time.monotonic()

    elapsed = t_confirm - t_send
    tx_times.append(elapsed)
    block_numbers.append(receipt.blockNumber)

    if (i + 1) % 20 == 0:
        print(f"  {i+1}/{TX_COUNT} sent  (last confirm: {elapsed*1000:.0f}ms)")

t_total = time.monotonic() - t_start

# ── Analyze block times ──────────────────────────────────────────
unique_blocks = sorted(set(block_numbers))
print(f"\n{'='*55}")
print(f"  BENCHMARK RESULTS (period=0, on-demand sealing)")
print(f"{'='*55}")
print(f"  Transactions sent : {TX_COUNT}")
print(f"  Total time        : {t_total:.2f}s")
print(f"  Throughput        : {TX_COUNT/t_total:.1f} tx/s")
print(f"  Blocks created    : {len(unique_blocks)} (#{unique_blocks[0]}-#{unique_blocks[-1]})")
print(f"  Tx per block      : {TX_COUNT/len(unique_blocks):.1f} avg")

# Confirmation latency stats
print(f"\n  Confirmation Latency:")
print(f"    Min     : {min(tx_times)*1000:.0f}ms")
print(f"    Max     : {max(tx_times)*1000:.0f}ms")
print(f"    Mean    : {statistics.mean(tx_times)*1000:.0f}ms")
print(f"    Median  : {statistics.median(tx_times)*1000:.0f}ms")
print(f"    Stdev   : {statistics.stdev(tx_times)*1000:.0f}ms")

# Block timestamp analysis
block_timestamps = []
for bn in unique_blocks:
    block = w3.eth.get_block(bn)
    block_timestamps.append(block.timestamp)

if len(block_timestamps) > 1:
    intervals = [block_timestamps[i+1] - block_timestamps[i] for i in range(len(block_timestamps)-1)]
    print(f"\n  Block Time Intervals (from timestamps):")
    print(f"    Min     : {min(intervals)}s")
    print(f"    Max     : {max(intervals)}s")
    print(f"    Mean    : {statistics.mean(intervals):.2f}s")
    # Note: Clique timestamps are integer seconds, so sub-second
    # intervals show as 0s or 1s. Real latency is in tx_times above.

# ── Disk usage ───────────────────────────────────────────────────
import subprocess
result = subprocess.run(
    ["ssh", "-o", "StrictHostKeyChecking=no", "nexus-master",
     "du -sh /opt/nexus/blockchain/data-fast-test/geth/chaindata/"],
    capture_output=True, text=True
)
if result.returncode == 0:
    print(f"\n  Chaindata size: {result.stdout.strip().split()[0]}")

# Block size analysis
total_size = 0
for bn in unique_blocks:
    block = w3.eth.get_block(bn, True)
    # Approximate block size from transaction data
    total_size += len(str(block))

print(f"  Avg block repr  : {total_size/len(unique_blocks):.0f} bytes")

# ── Verdict ──────────────────────────────────────────────────────
print(f"\n{'='*55}")
mean_ms = statistics.mean(tx_times) * 1000
if mean_ms < 500:
    print(f"  VERDICT: PROCEED")
    print(f"  Mean confirmation {mean_ms:.0f}ms < 500ms target")
elif mean_ms < 2000:
    print(f"  VERDICT: PROCEED (with caution)")
    print(f"  Mean confirmation {mean_ms:.0f}ms — acceptable but not sub-second")
else:
    print(f"  VERDICT: ABORT")
    print(f"  Mean confirmation {mean_ms:.0f}ms — too slow")
print(f"{'='*55}")
