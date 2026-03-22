#!/usr/bin/env python3
"""Deploy TemporalScheduler contract to NEXUS chain."""
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
import json
import subprocess
import os

RPC_URL = 'http://10.0.20.3:8545'
DEPLOYER = '0x817B0842B208B76A7665948F8D1A0592F9b1e958'
SOURCE_DIR = '/opt/nexus/contracts/source'
DEPLOY_DIR = '/opt/nexus/contracts/deployed'

w3 = Web3(Web3.HTTPProvider(RPC_URL))
w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
print(f"Connected: {w3.is_connected()}")
print(f"Block: {w3.eth.block_number}")
print(f"Balance: {w3.eth.get_balance(DEPLOYER) / 10**18:.4f} ETH\n")

# Compile
sol_file = f"{SOURCE_DIR}/TemporalScheduler.sol"
cmd = f"solcjs --abi --bin {sol_file}"
result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=SOURCE_DIR)
if result.returncode != 0:
    raise Exception(f"Compilation failed: {result.stderr}")

abi_file = f"{SOURCE_DIR}/TemporalScheduler_sol_TemporalScheduler.abi"
bin_file = f"{SOURCE_DIR}/TemporalScheduler_sol_TemporalScheduler.bin"

with open(abi_file, 'r') as f:
    abi = json.load(f)
with open(bin_file, 'r') as f:
    bytecode = '0x' + f.read().strip()

print(f"Compiled: {len(bytecode)} hex chars bytecode")

# Deploy
contract = w3.eth.contract(abi=abi, bytecode=bytecode)
tx_hash = contract.constructor().transact({
    'from': Web3.to_checksum_address(DEPLOYER),
    'gas': 2000000
})
print(f"Deploy TX: {tx_hash.hex()}")
receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
addr = receipt['contractAddress']
print(f"Deployed at: {addr} (block {receipt['blockNumber']})")

# Save
deployed = {
    'address': Web3.to_checksum_address(addr),
    'abi': abi,
    'block': receipt['blockNumber'],
    'tx_hash': receipt['transactionHash'].hex()
}
with open(f"{DEPLOY_DIR}/TemporalScheduler.json", 'w') as f:
    json.dump(deployed, f, indent=2)
print(f"Saved to {DEPLOY_DIR}/TemporalScheduler.json")

# Verify
ts = w3.eth.contract(address=addr, abi=abi)

# a. computeBinId(2026, 13, 0, 14)
bin_id = ts.functions.computeBinId(2026, 13, 0, 14).call()
print(f"\nVerification:")
print(f"  computeBinId(2026, 13, 0, 14) = {bin_id.hex()}")

# b. assignTask(2026, 13, 0, 14, <test_hash>, 10)
test_hash = Web3.keccak(text="nexus-test-task")
tx2 = ts.functions.assignTask(2026, 13, 0, 14, test_hash, 10).transact({
    'from': Web3.to_checksum_address(DEPLOYER),
    'gas': 500000
})
receipt2 = w3.eth.wait_for_transaction_receipt(tx2, timeout=30)
print(f"  assignTask TX: {tx2.hex()} (block {receipt2['blockNumber']})")

# c. getBin(binId)
year, week, dow, hour, task_count, ect_spent, created_at, exists = ts.functions.getBin(bin_id).call()
print(f"  getBin: year={year} week={week} dayOfWeek={dow} hour={hour} taskCount={task_count} totalECTSpent={ect_spent} exists={exists}")
assert task_count == 1, f"Expected taskCount=1, got {task_count}"
assert ect_spent == 10, f"Expected totalECTSpent=10, got {ect_spent}"

# d. totalBinsUsed()
total_bins = ts.functions.totalBinsUsed().call()
print(f"  totalBinsUsed() = {total_bins}")
assert total_bins == 1, f"Expected totalBinsUsed=1, got {total_bins}"

# e. totalAssignments()
total_assignments = ts.functions.totalAssignments().call()
print(f"  totalAssignments() = {total_assignments}")
assert total_assignments == 1, f"Expected totalAssignments=1, got {total_assignments}"

print("\nAll assertions passed.")
print(f"\n=== TemporalScheduler Deployment Summary ===")
print(f"  Address:  {Web3.to_checksum_address(addr)}")
print(f"  Block:    {receipt['blockNumber']}")
print(f"  TX Hash:  {receipt['transactionHash'].hex()}")
print(f"  Saved:    {DEPLOY_DIR}/TemporalScheduler.json")
print("============================================")

# Cleanup compilation artifacts
for f in [abi_file, bin_file]:
    if os.path.exists(f):
        os.remove(f)
