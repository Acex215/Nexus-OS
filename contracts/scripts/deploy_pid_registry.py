#!/usr/bin/env python3
"""Deploy PidRegistry contract to NEXUS chain."""
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
import json
import subprocess
import os

RPC_URL = 'http://192.168.8.228:8545'
DEPLOYER = '0x817B0842B208B76A7665948F8D1A0592F9b1e958'
SOURCE_DIR = '/opt/nexus/contracts/source'
DEPLOY_DIR = '/opt/nexus/contracts/deployed'

w3 = Web3(Web3.HTTPProvider(RPC_URL))
w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
print(f"Connected: {w3.is_connected()}")
print(f"Block: {w3.eth.block_number}")
print(f"Balance: {w3.eth.get_balance(DEPLOYER) / 10**18:.4f} ETH\n")

# Compile
sol_file = f"{SOURCE_DIR}/PidRegistry.sol"
cmd = f"solcjs --abi --bin {sol_file}"
result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=SOURCE_DIR)
if result.returncode != 0:
    raise Exception(f"Compilation failed: {result.stderr}")

abi_file = f"{SOURCE_DIR}/PidRegistry_sol_PidRegistry.abi"
bin_file = f"{SOURCE_DIR}/PidRegistry_sol_PidRegistry.bin"

with open(abi_file, 'r') as f:
    abi = json.load(f)
with open(bin_file, 'r') as f:
    bytecode = '0x' + f.read().strip()

print(f"Compiled: {len(bytecode)} hex chars bytecode")

# Deploy
contract = w3.eth.contract(abi=abi, bytecode=bytecode)
tx_hash = contract.constructor().transact({
    'from': Web3.to_checksum_address(DEPLOYER),
    'gas': 500000
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
with open(f"{DEPLOY_DIR}/PidRegistry.json", 'w') as f:
    json.dump(deployed, f, indent=2)
print(f"Saved to {DEPLOY_DIR}/PidRegistry.json")

# Test
pid_contract = w3.eth.contract(address=addr, abi=abi)
tx = pid_contract.functions.getPid(Web3.to_checksum_address(DEPLOYER)).transact({
    'from': Web3.to_checksum_address(DEPLOYER),
    'gas': 100000
})
receipt2 = w3.eth.wait_for_transaction_receipt(tx, timeout=30)
pid = pid_contract.functions.viewPid(Web3.to_checksum_address(DEPLOYER)).call()
print(f"\nTest: getPid(deployer) = {pid}")
print("PidRegistry deployed and verified!")

# Cleanup compilation artifacts
for f in [abi_file, bin_file]:
    if os.path.exists(f):
        os.remove(f)
