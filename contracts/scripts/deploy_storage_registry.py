#!/usr/bin/env python3
"""Deploy StorageRegistry.sol to NEXUS blockchain."""
import json
import os
import sys
import hashlib
import time

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

RPC_URL    = "http://192.168.8.228:8545"
DEPLOYER   = "0x817B0842B208B76A7665948F8D1A0592F9b1e958"
SOURCE_DIR = "/opt/nexus/contracts/source"
DEPLOY_DIR = "/opt/nexus/contracts/deployed"

# ── Connect ──────────────────────────────────────────────────────
w3 = Web3(Web3.HTTPProvider(RPC_URL))
w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

assert w3.is_connected(), "Cannot connect to Geth"
print(f"Connected to chain {w3.eth.chain_id}, block {w3.eth.block_number}")
print(f"Deployer: {DEPLOYER}")
print(f"Balance:  {w3.from_wei(w3.eth.get_balance(DEPLOYER), 'ether')} ETH\n")

# ── Load compiled artifacts ──────────────────────────────────────
abi_file = os.path.join(SOURCE_DIR, "StorageRegistry_sol_StorageRegistry.abi")
bin_file = os.path.join(SOURCE_DIR, "StorageRegistry_sol_StorageRegistry.bin")

with open(abi_file) as f:
    abi = json.load(f)
with open(bin_file) as f:
    bytecode = f.read().strip()

print(f"ABI:      {len(abi)} entries")
print(f"Bytecode: {len(bytecode)} hex chars ({len(bytecode)//2} bytes)")

# ── Deploy ───────────────────────────────────────────────────────
print("\nDeploying StorageRegistry...")

Contract = w3.eth.contract(abi=abi, bytecode=bytecode)
tx = Contract.constructor().build_transaction({
    "from": DEPLOYER,
    "nonce": w3.eth.get_transaction_count(DEPLOYER),
    "gas": 3000000,
    "gasPrice": w3.eth.gas_price,
})

tx_hash = w3.eth.send_transaction(tx)
print(f"TX Hash:  {tx_hash.hex()}")

receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
address = receipt["contractAddress"]

print(f"Address:  {address}")
print(f"Block:    {receipt['blockNumber']}")
print(f"Gas used: {receipt['gasUsed']}")
print(f"Status:   {'SUCCESS' if receipt['status'] == 1 else 'FAILED'}")

if receipt["status"] != 1:
    print("DEPLOYMENT FAILED")
    sys.exit(1)

# ── Save deployment info ─────────────────────────────────────────
deploy_info = {
    "name": "StorageRegistry",
    "address": address,
    "abi": abi,
    "deployer": DEPLOYER,
    "block": receipt["blockNumber"],
    "txHash": tx_hash.hex(),
}

deploy_path = os.path.join(DEPLOY_DIR, "StorageRegistry.json")
with open(deploy_path, "w") as f:
    json.dump(deploy_info, f, indent=2)

print(f"\nSaved to: {deploy_path}")

# ── Verify: read back code ───────────────────────────────────────
code = w3.eth.get_code(address)
print(f"On-chain code: {len(code)} bytes")

# ── Quick smoke test: call fileCount ─────────────────────────────
contract = w3.eth.contract(address=address, abi=abi)
count = contract.functions.fileCount().call()
print(f"fileCount(): {count}  (expected 0)")

# Cleanup compiled artifacts
os.remove(abi_file)
os.remove(bin_file)

print("\n" + "=" * 55)
print(f"  StorageRegistry deployed at {address}")
print("=" * 55)
