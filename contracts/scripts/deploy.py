#!/usr/bin/env python3
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
import json
import subprocess
import os

# Configuration
RPC_URL = 'http://10.0.20.3:8545'
DEPLOYER = '0x817B0842B208B76A7665948F8D1A0592F9b1e958'
SOURCE_DIR = '/opt/nexus/contracts/source'
DEPLOY_DIR = '/opt/nexus/contracts/deployed'

w3 = Web3(Web3.HTTPProvider(RPC_URL))
w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
print(f"Connected: {w3.is_connected()}")
print(f"Deployer: {DEPLOYER}")
print(f"Balance: {w3.eth.get_balance(DEPLOYER) / 10**18} ETH\n")

def compile_contract(sol_file):
    """Compile Solidity using solcjs"""
    cmd = f"solcjs --abi --bin {sol_file}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=SOURCE_DIR)

    if result.returncode != 0:
        raise Exception(f"Compilation failed: {result.stderr}")

    # solcjs outputs: ContractName_sol_ContractName.abi and .bin
    contract_name = os.path.basename(sol_file).replace('.sol', '')
    abi_file = f"{SOURCE_DIR}/{contract_name}_sol_{contract_name}.abi"
    bin_file = f"{SOURCE_DIR}/{contract_name}_sol_{contract_name}.bin"

    with open(abi_file, 'r') as f:
        abi = json.load(f)
    with open(bin_file, 'r') as f:
        bytecode = f.read().strip()

    # Cleanup temp files
    os.remove(abi_file)
    os.remove(bin_file)

    return abi, bytecode

def deploy_contract(name, sol_file):
    """Deploy a contract"""
    print(f"\n{'='*60}")
    print(f"Deploying {name}...")
    print('='*60)

    # Compile
    abi, bytecode = compile_contract(sol_file)

    # Create contract instance
    Contract = w3.eth.contract(abi=abi, bytecode=bytecode)

    # Build transaction
    tx = Contract.constructor().build_transaction({
        'from': DEPLOYER,
        'nonce': w3.eth.get_transaction_count(DEPLOYER),
        'gas': 3000000,
        'gasPrice': w3.eth.gas_price
    })

    # Send transaction (assumes unlocked account on node)
    tx_hash = w3.eth.send_transaction(tx)
    print(f"TX Hash: {tx_hash.hex()}")

    # Wait for receipt
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    address = receipt['contractAddress']

    print(f"Deployed at: {address}")
    print(f"  Block: {receipt['blockNumber']}")
    print(f"  Gas used: {receipt['gasUsed']}")

    # Save deployment info
    deploy_info = {
        'name': name,
        'address': address,
        'abi': abi,
        'deployer': DEPLOYER,
        'block': receipt['blockNumber'],
        'txHash': tx_hash.hex()
    }

    with open(f"{DEPLOY_DIR}/{name}.json", 'w') as f:
        json.dump(deploy_info, f, indent=2)

    return address

# Deploy contracts
reasoning_addr = deploy_contract('ReasoningLedger', f"{SOURCE_DIR}/ReasoningLedger.sol")
resource_addr = deploy_contract('ResourceManager', f"{SOURCE_DIR}/ResourceManager.sol")

print(f"\n{'='*60}")
print("DEPLOYMENT COMPLETE")
print('='*60)
print(f"ReasoningLedger:  {reasoning_addr}")
print(f"ResourceManager:  {resource_addr}")
print(f"\nABI files saved to: {DEPLOY_DIR}/")
