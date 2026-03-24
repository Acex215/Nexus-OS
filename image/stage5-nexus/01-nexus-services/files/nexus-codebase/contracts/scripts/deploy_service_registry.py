#!/usr/bin/env python3
"""Deploy ServiceRegistry contract to NEXUS chain."""
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
print(f"Deployer: {DEPLOYER}")
print(f"Balance: {w3.eth.get_balance(DEPLOYER) / 10**18:.4f} ETH\n")

# Compile
sol_file = f"{SOURCE_DIR}/ServiceRegistry.sol"
cmd = f"solcjs --abi --bin {sol_file}"
result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=SOURCE_DIR)
if result.returncode != 0:
    raise Exception(f"Compilation failed: {result.stderr}")

abi_file = f"{SOURCE_DIR}/ServiceRegistry_sol_ServiceRegistry.abi"
bin_file = f"{SOURCE_DIR}/ServiceRegistry_sol_ServiceRegistry.bin"

with open(abi_file, 'r') as f:
    abi = json.load(f)
with open(bin_file, 'r') as f:
    bytecode = f.read().strip()

os.remove(abi_file)
os.remove(bin_file)

print("Compiled ServiceRegistry.sol")
print(f"  ABI functions: {len([x for x in abi if x.get('type') == 'function'])}")
print(f"  Bytecode size: {len(bytecode) // 2} bytes")

# Deploy
Contract = w3.eth.contract(abi=abi, bytecode=bytecode)
tx = Contract.constructor().build_transaction({
    'from': DEPLOYER,
    'nonce': w3.eth.get_transaction_count(DEPLOYER),
    'gas': 3000000,
    'gasPrice': w3.eth.gas_price
})

tx_hash = w3.eth.send_transaction(tx)
print(f"\nTX Hash: {tx_hash.hex()}")

receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
address = receipt['contractAddress']

print(f"Deployed at: {address}")
print(f"  Block: {receipt['blockNumber']}")
print(f"  Gas used: {receipt['gasUsed']}")

deploy_info = {
    'name': 'ServiceRegistry',
    'address': address,
    'abi': abi,
    'deployer': DEPLOYER,
    'block': receipt['blockNumber'],
    'txHash': tx_hash.hex()
}

with open(f"{DEPLOY_DIR}/ServiceRegistry.json", 'w') as f:
    json.dump(deploy_info, f, indent=2)

print(f"\nSaved to {DEPLOY_DIR}/ServiceRegistry.json")
