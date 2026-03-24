#!/usr/bin/env python3
"""Deploy FlockCoordinator contract to NEXUS chain."""
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
sol_file = f"{SOURCE_DIR}/FlockCoordinator.sol"
cmd = f"solcjs --abi --bin {sol_file}"
result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=SOURCE_DIR)
if result.returncode != 0:
    raise Exception(f"Compilation failed: {result.stderr}")

abi_file = f"{SOURCE_DIR}/FlockCoordinator_sol_FlockCoordinator.abi"
bin_file = f"{SOURCE_DIR}/FlockCoordinator_sol_FlockCoordinator.bin"

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
    'name': 'FlockCoordinator',
    'address': Web3.to_checksum_address(addr),
    'abi': abi,
    'deployer': DEPLOYER,
    'block': receipt['blockNumber'],
    'txHash': receipt['transactionHash'].hex()
}
with open(f"{DEPLOY_DIR}/FlockCoordinator.json", 'w') as f:
    json.dump(deployed, f, indent=2)
print(f"Saved to {DEPLOY_DIR}/FlockCoordinator.json")

# Initialize: start epoch 1
fc = w3.eth.contract(address=addr, abi=abi)

tx2 = fc.functions.startEpoch().transact({
    'from': Web3.to_checksum_address(DEPLOYER),
    'gas': 500000
})
receipt2 = w3.eth.wait_for_transaction_receipt(tx2, timeout=30)
print(f"\nstartEpoch TX: {tx2.hex()} (block {receipt2['blockNumber']})")

# Verify
print("\nVerification:")

epoch_id = fc.functions.currentEpoch().call()
print(f"  currentEpoch() = {epoch_id}")
assert epoch_id == 1, f"Expected currentEpoch=1, got {epoch_id}"

epoch = fc.functions.getCurrentEpoch().call()
# Epoch tuple: (epochId, dailySalt, startBlock, endBlock, submissionCount, aggregatedModelHash, finalized)
print(f"  epochId:         {epoch[0]}")
print(f"  dailySalt:       0x{epoch[1].hex()}")
print(f"  startBlock:      {epoch[2]}")
print(f"  endBlock:        {epoch[3]}")
print(f"  submissionCount: {epoch[4]}")
print(f"  finalized:       {epoch[6]}")
assert epoch[0] == 1, f"Expected epochId=1, got {epoch[0]}"
assert epoch[6] == False, f"Expected finalized=False, got {epoch[6]}"
assert epoch[3] == 0, f"Expected endBlock=0, got {epoch[3]}"

salt = fc.functions.getDailySalt(1).call()
print(f"  getDailySalt(1): 0x{salt.hex()}")
assert salt == epoch[1], "dailySalt mismatch"

total = fc.functions.totalSubmissions().call()
print(f"  totalSubmissions: {total}")
assert total == 0, f"Expected totalSubmissions=0, got {total}"

print("\nAll assertions passed.")
print(f"\n=== FlockCoordinator Deployment Summary ===")
print(f"  Address:    {Web3.to_checksum_address(addr)}")
print(f"  Block:      {receipt['blockNumber']}")
print(f"  TX Hash:    {receipt['transactionHash'].hex()}")
print(f"  Epoch 1:    active, salt=0x{salt.hex()[:16]}...")
print(f"  Saved:      {DEPLOY_DIR}/FlockCoordinator.json")
print("=============================================")

# Cleanup compilation artifacts
for f in [abi_file, bin_file]:
    if os.path.exists(f):
        os.remove(f)
