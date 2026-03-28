#!/usr/bin/env python3
"""Deploy BehavioralActionRegistry to the NEXUS private chain."""

import json
import sys
sys.path.insert(0, '/opt/nexus')

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
import solcx

def deploy():
    # Connect to chain
    w3 = Web3(Web3.HTTPProvider('http://10.0.20.3:8545'))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    assert w3.is_connected(), "Cannot connect to Geth"
    print(f"Connected. Block: {w3.eth.block_number}")

    # Load deployer account
    deployer = '0x817B0842B208B76A7665948F8D1A0592F9b1e958'
    # Unlock or use keystore — adjust based on your geth config
    # w3.geth.personal.unlock_account(deployer, 'your-password', 600)

    # Compile contract
    solcx.install_solc('0.8.19')
    with open('/opt/nexus/contracts/source/BehavioralActionRegistry.sol', 'r') as f:
        source = f.read()

    compiled = solcx.compile_source(
        source,
        output_values=['abi', 'bin'],
        solc_version='0.8.19'
    )

    contract_key = '<stdin>:BehavioralActionRegistry'
    abi = compiled[contract_key]['abi']
    bytecode = compiled[contract_key]['bin']

    print(f"Compiled. Bytecode: {len(bytecode)} chars")
    print(f"ABI: {len(abi)} entries")

    # Deploy
    Contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx = Contract.constructor().build_transaction({
        'from': deployer,
        'nonce': w3.eth.get_transaction_count(deployer),
        'gas': 10000000,  # High gas limit for large contract
        'gasPrice': 0
    })

    # Sign and send
    # If using unlocked account:
    tx_hash = w3.eth.send_transaction(tx)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

    contract_address = receipt['contractAddress']
    print(f"\n=== DEPLOYED ===")
    print(f"Address: {contract_address}")
    print(f"TX Hash: {receipt['transactionHash'].hex()}")
    print(f"Gas Used: {receipt['gasUsed']}")
    print(f"Block: {receipt['blockNumber']}")

    # Save deployed ABI + address
    deployed = {
        'address': contract_address,
        'abi': abi,
        'deployer': deployer,
        'block': receipt['blockNumber'],
        'txHash': receipt['transactionHash'].hex()
    }

    with open('/opt/nexus/contracts/deployed/BehavioralActionRegistry.json', 'w') as f:
        json.dump(deployed, f, indent=2)

    print(f"\nSaved to contracts/deployed/BehavioralActionRegistry.json")

    # Verify debug mode is enabled
    contract = w3.eth.contract(address=contract_address, abi=abi)
    assert contract.functions.debugMode().call() == True
    assert contract.functions.admin().call() == deployer
    print(f"Debug mode: ENABLED")
    print(f"Admin: {deployer}")
    print(f"\nContract ready for behavioral collection.")

if __name__ == '__main__':
    deploy()
