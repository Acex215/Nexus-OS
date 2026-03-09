#!/usr/bin/env python3
"""NEXUS OS - Phase 2 Comprehensive Validation"""
from libnexus import NexusKernel
import subprocess
import time
import datetime

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"

results = []

def check(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((name, status, detail))
    mark = "+" if condition else "!"
    print(f"  [{mark}] {name}: {status}" + (f"  ({detail})" if detail else ""))
    return condition


print("=" * 70)
print("NEXUS OS - Phase 2 Comprehensive Validation")
print(f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 70)

# ── 1. BLOCKCHAIN HEALTH ──────────────────────────────────────────────
print("\n1. BLOCKCHAIN HEALTH")
print("-" * 70)

validators = {
    'nexus-master':  {'rpc': 'http://10.0.20.3:8545', 'wallet': '0x817B0842B208B76A7665948F8D1A0592F9b1e958'},
    'nexus-ai':      {'rpc': 'http://10.0.20.4:8545', 'wallet': '0x9602699C3Cb2aCf35CF20c32012A88CD451e55F0'},
    'nexus-storage': {'rpc': 'http://10.0.20.11:8545', 'wallet': '0x06eB84AE46d1b914A35432B6BA7351344aeb9C37'},
}

# Check service status on each validator
for node in validators:
    result = subprocess.run(
        f"ssh {node} 'systemctl is-active nexus-geth'",
        shell=True, capture_output=True, text=True, timeout=10
    )
    status = result.stdout.strip()
    check(f"{node} geth service", status == "active", status)

# Check RPC connectivity and block numbers from each node
block_numbers = {}
for node, info in validators.items():
    try:
        kn = NexusKernel(rpc_url=info['rpc'])
        bn = kn.get_block_number()
        block_numbers[node] = bn
        check(f"{node} RPC reachable", True, f"block {bn}")
    except Exception as e:
        check(f"{node} RPC reachable", False, str(e))

# Verify blocks are in sync (within 2 blocks of each other)
if len(block_numbers) == 3:
    spread = max(block_numbers.values()) - min(block_numbers.values())
    check("Block sync across validators", spread <= 2, f"spread={spread}")

# Check peer counts
for node, info in validators.items():
    try:
        result = subprocess.run(
            f"ssh {node} \"sudo geth attach --exec 'net.peerCount' /opt/nexus/blockchain/geth.ipc\"",
            shell=True, capture_output=True, text=True, timeout=10
        )
        peers = int(result.stdout.strip())
        check(f"{node} peer count", peers == 2, f"{peers} peers")
    except Exception as e:
        check(f"{node} peer count", False, str(e))

# Block production rate
k = NexusKernel(rpc_url='http://10.0.20.3:8545')
print(f"\n  Measuring block production over 15 seconds...")
block_start = k.get_block_number()
time.sleep(15)
block_end = k.get_block_number()
blocks_added = block_end - block_start
expected_min = 2  # 15s / 5s = 3, allow 2 minimum
check("Block production rate", blocks_added >= expected_min,
      f"{blocks_added} blocks in 15s (expected ~3)")

# ── 2. CONSENSUS VALIDATION ───────────────────────────────────────────
print("\n2. CONSENSUS VALIDATION")
print("-" * 70)

current = k.get_block_number()
wallet_to_name = {v['wallet'].lower(): name for name, v in validators.items()}

# Use Geth IPC to get block signers (clique.getSigner needs block hash)
scan_count = 20
result = subprocess.run(
    f"ssh nexus-master \"sudo geth attach --exec '"
    f"var result = []; "
    f"for (var i = eth.blockNumber - {scan_count}; i < eth.blockNumber; i++) {{ "
    f"result.push(clique.getSigner(eth.getBlock(i).hash)); }}; "
    f"result' /opt/nexus/blockchain/geth.ipc\"",
    shell=True, capture_output=True, text=True, timeout=15
)

signers = {}
import json as _json
try:
    signer_list = _json.loads(result.stdout.strip())
    for s in signer_list:
        addr = s.lower()
        signers[addr] = signers.get(addr, 0) + 1
except Exception:
    pass

print(f"  Last {scan_count} blocks sealed by:")
for signer, count in sorted(signers.items(), key=lambda x: -x[1]):
    name = wallet_to_name.get(signer, "unknown")
    pct = count / scan_count * 100
    print(f"    {name:15s} ({signer}): {count} blocks ({pct:.0f}%)")

check("All 3 validators sealing", len(signers) == 3,
      f"{len(signers)} unique signers")

if len(signers) == 3:
    min_blocks = min(signers.values())
    check("Fair block distribution", min_blocks >= 4,
          f"min={min_blocks}/{scan_count}, each validator should seal ~6-7")

# Verify chain ID
chain_id = k.w3.eth.chain_id
check("Chain ID correct", chain_id == 123454321, f"chain_id={chain_id}")

# ── 3. SMART CONTRACTS ────────────────────────────────────────────────
print("\n3. SMART CONTRACTS")
print("-" * 70)

expected_reasoning = "0x0317451264E1de1A0696A81f6141e72E58686DE4"
expected_resource = "0x7E7f5e6cd9d7d485eeFa4Ec3Fb211705A3A8c6C6"

# Verify contract code exists at addresses
reasoning_code = k.w3.eth.get_code(expected_reasoning)
check("ReasoningLedger deployed", len(reasoning_code) > 2,
      f"code size: {len(reasoning_code)} bytes")

resource_code = k.w3.eth.get_code(expected_resource)
check("ResourceManager deployed", len(resource_code) > 2,
      f"code size: {len(resource_code)} bytes")

# Verify contract functions accessible
entry_count = k.get_entry_count()
check("ReasoningLedger callable", entry_count >= 0,
      f"entry_count={entry_count}")

node_count = k.get_node_count()
check("ResourceManager callable", node_count >= 0,
      f"node_count={node_count}")

print(f"\n  ReasoningLedger: {expected_reasoning}")
print(f"  ResourceManager: {expected_resource}")

# ── 4. SYSTEM CALL LIBRARY ────────────────────────────────────────────
print("\n4. SYSTEM CALL LIBRARY (libnexus)")
print("-" * 70)

all_hosts = ['nexus-master', 'nexus-ai', 'nexus-storage', 'nexus-admin']
import socket
local_hostname = socket.gethostname()

for node in all_hosts:
    if node == local_hostname or node == 'nexus-admin':
        # Running locally on this node
        result = subprocess.run(
            "source /opt/nexus/contracts/.venv/bin/activate && "
            "python3 -c \"from libnexus import NexusKernel; k = NexusKernel(); "
            "print(k.get_block_number())\"",
            shell=True, capture_output=True, text=True, timeout=15,
            executable='/bin/bash'
        )
    else:
        result = subprocess.run(
            f"ssh {node} \"source /opt/nexus/contracts/.venv/bin/activate && "
            f"python3 -c \\\"from libnexus import NexusKernel; k = NexusKernel(); "
            f"print(k.get_block_number())\\\"\"",
            shell=True, capture_output=True, text=True, timeout=15
        )
    ok = result.returncode == 0 and result.stdout.strip().isdigit()
    check(f"{node} libnexus import+query", ok,
          f"block={result.stdout.strip()}" if ok else result.stderr.strip()[:60])

# ── 5. HARDWARE REGISTRY ──────────────────────────────────────────────
print("\n5. HARDWARE REGISTRY")
print("-" * 70)

expected_specs = {
    'nexus-master':  {'cpu': 4, 'mem': 8, 'storage': 256,  'tops': 0},
    'nexus-ai':      {'cpu': 4, 'mem': 8, 'storage': 128,  'tops': 26},
    'nexus-storage': {'cpu': 4, 'mem': 8, 'storage': 1800, 'tops': 0},
    'nexus-admin':   {'cpu': 4, 'mem': 8, 'storage': 512,  'tops': 0},
}

check("Total nodes registered", node_count == 4, f"count={node_count}")

all_nodes = k.get_all_nodes()
for addr in all_nodes:
    specs = k.get_node(addr)
    hostname, cpu, mem, storage, tops, active = specs
    exp = expected_specs.get(hostname, {})

    specs_match = (
        exp.get('cpu') == cpu and
        exp.get('mem') == mem and
        exp.get('storage') == storage and
        exp.get('tops') == tops
    )
    tops_str = f" | {tops} TOPS" if tops > 0 else ""
    check(f"{hostname} specs correct",
          specs_match,
          f"{cpu}C / {mem}GB / {storage}GB{tops_str}")
    check(f"{hostname} active", active, f"active={active}")

# ── 6. END-TO-END TEST ────────────────────────────────────────────────
print("\n6. END-TO-END TEST: Reasoning Entry")
print("-" * 70)

k_master = NexusKernel(
    rpc_url='http://10.0.20.3:8545',
    wallet='0x817B0842B208B76A7665948F8D1A0592F9b1e958'
)

try:
    result = k_master.log_reasoning(
        decision="Phase 2 Validation Complete",
        reasoning="Blockchain kernel operational. 3 validators producing blocks "
                  "in Clique PoA consensus. Smart contracts deployed. "
                  "Hardware topology registered on-chain. All 4 nodes verified."
    )
    check("Reasoning entry submitted", True,
          f"block={result['block']}, gas={result['gas_used']}")
    print(f"    TX: {result['tx_hash']}")

    # Read it back
    new_count = k_master.get_entry_count()
    entry = k_master.get_reasoning_entry(new_count - 1)
    agent, timestamp, decision, reasoning, entry_hash = entry

    read_ok = (decision == "Phase 2 Validation Complete" and
               agent.lower() == k_master.wallet.lower())
    check("Reasoning entry readable", read_ok, f"entry_id={new_count - 1}")
    print(f"    Agent:     {agent}")
    print(f"    Timestamp: {timestamp}")
    print(f"    Decision:  {decision}")
    print(f"    Reasoning: {reasoning[:70]}...")
    print(f"    Hash:      {entry_hash.hex()}")

    # Verify agent history
    history = k_master.get_agent_history(k_master.wallet)
    check("Agent history queryable", len(history) > 0,
          f"{len(history)} entries")

except Exception as e:
    check("End-to-end reasoning test", False, str(e))

# ── 7. WALLET BALANCES ────────────────────────────────────────────────
print("\n7. WALLET BALANCES")
print("-" * 70)

all_wallets = {
    'nexus-master':  '0x817B0842B208B76A7665948F8D1A0592F9b1e958',
    'nexus-ai':      '0x9602699C3Cb2aCf35CF20c32012A88CD451e55F0',
    'nexus-storage': '0x06eB84AE46d1b914A35432B6BA7351344aeb9C37',
    'nexus-admin':   '0x899D037d099393A2Cd79DB0058E2Fee689BD397a',
}

for name, addr in all_wallets.items():
    bal = k.get_balance(addr)
    has_funds = bal > 0
    check(f"{name} has funds", has_funds, f"{bal:.4f} ETH")

# ── SUMMARY ───────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("PHASE 2 VALIDATION SUMMARY")
print("=" * 70)

passed = sum(1 for _, s, _ in results if s == PASS)
failed = sum(1 for _, s, _ in results if s == FAIL)
total = len(results)

print(f"\n  Results: {passed}/{total} passed" +
      (f", {failed} FAILED" if failed else ""))

if failed:
    print("\n  FAILURES:")
    for name, status, detail in results:
        if status == FAIL:
            print(f"    [!] {name}: {detail}")

print(f"\n  Blockchain Stats:")
print(f"    Chain ID:        {chain_id}")
print(f"    Block height:    {k.get_block_number()}")
print(f"    Block time:      5 seconds (Clique PoA)")
print(f"    Validators:      3 (nexus-master, nexus-ai, nexus-storage)")
print(f"    Consensus:       Clique Proof of Authority")
print(f"    Smart contracts: 2 (ReasoningLedger, ResourceManager)")
print(f"    Registered nodes: {node_count}")
print(f"    Reasoning entries: {k.get_entry_count()}")

print(f"\n  Contract Addresses:")
print(f"    ReasoningLedger: {expected_reasoning}")
print(f"    ResourceManager: {expected_resource}")

if failed == 0:
    print(f"\n  STATUS: ALL CHECKS PASSED")
    print(f"  Ready for Phase 3: AI Agent Integration")
else:
    print(f"\n  STATUS: {failed} CHECK(S) FAILED - Review before proceeding")

print("=" * 70)
