#!/usr/bin/env python3
"""Deploy FlockCoordinator to the NEXUS private chain."""

import json
import sys
sys.path.insert(0, '/opt/nexus')

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
import solcx

def deploy():
    w3 = Web3(Web3.HTTPProvider('http://10.0.20.3:8545'))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    assert w3.is_connected(), "Cannot connect to Geth"
    print(f"Connected. Block: {w3.eth.block_number}")

    deployer = '0x817B0842B208B76A7665948F8D1A0592F9b1e958'

    # Load TokenManager address
    with open('/opt/nexus/contracts/deployed/TokenManager.json', 'r') as f:
        tm = json.load(f)
    token_manager_address = tm['address']
    print(f"TokenManager: {token_manager_address}")

    # Compile
    solcx.install_solc('0.8.19')
    with open('/opt/nexus/contracts/source/FlockCoordinator.sol', 'r') as f:
        source = f.read()

    compiled = solcx.compile_source(source, output_values=['abi', 'bin'], solc_version='0.8.19')
    contract_key = '<stdin>:FlockCoordinator'
    abi = compiled[contract_key]['abi']
    bytecode = compiled[contract_key]['bin']

    print(f"Compiled. ABI: {len(abi)} entries")

    # Deploy with TokenManager address as constructor arg
    Contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx = Contract.constructor(token_manager_address).build_transaction({
        'from': deployer,
        'nonce': w3.eth.get_transaction_count(deployer),
        'gas': 8000000,
        'gasPrice': 0
    })
    tx_hash = w3.eth.send_transaction(tx)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

    contract_address = receipt['contractAddress']
    print(f"\n=== FlockCoordinator DEPLOYED ===")
    print(f"Address: {contract_address}")
    print(f"TX: {receipt['transactionHash'].hex()}")
    print(f"Gas: {receipt['gasUsed']}")

    # Save deployed info
    deployed = {
        'address': contract_address,
        'abi': abi,
        'deployer': deployer,
        'block': receipt['blockNumber'],
        'txHash': receipt['transactionHash'].hex(),
        'tokenManager': token_manager_address
    }
    with open('/opt/nexus/contracts/deployed/FlockCoordinator.json', 'w') as f:
        json.dump(deployed, f, indent=2)

    print(f"Saved to contracts/deployed/FlockCoordinator.json")

    # Start first epoch
    contract = w3.eth.contract(address=contract_address, abi=abi)
    start_tx = contract.functions.startEpoch().build_transaction({
        'from': deployer,
        'nonce': w3.eth.get_transaction_count(deployer),
        'gas': 500000,
        'gasPrice': 0
    })
    start_hash = w3.eth.send_transaction(start_tx)
    start_receipt = w3.eth.wait_for_transaction_receipt(start_hash, timeout=10)

    epoch_id = contract.functions.currentEpochId().call()
    salt = contract.functions.getCurrentSalt().call()
    print(f"\nFirst epoch started: ID={epoch_id}")
    print(f"Daily salt: {salt.hex()[:32]}...")

if __name__ == '__main__':
    deploy()
