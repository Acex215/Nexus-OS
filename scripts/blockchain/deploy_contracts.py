#!/usr/bin/env python3
"""
NEXUS OS Smart Contract Deployment Script

Deploys ReasoningLedger and ResourceManager contracts to the NEXUS OS blockchain.

Requirements:
    - Running NEXUS OS blockchain (nexus-cli status)
    - Solidity compiler (solc) installed
    - web3.py Python library
    - Funded wallet for gas

Usage:
    python3 deploy_contracts.py [--rpc-url URL] [--keystore PATH] [--password-file PATH]

Example:
    cd /opt/nexus/contracts
    python3 deploy_contracts.py
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime

# Check for required modules
try:
    from web3 import Web3
    from web3.middleware import geth_poa_middleware
except ImportError:
    print("Error: web3 module not installed.")
    print("Install with: pip3 install web3")
    sys.exit(1)

try:
    import solcx
    from solcx import compile_standard, install_solc
    HAS_SOLCX = True
except ImportError:
    HAS_SOLCX = False
    print("Warning: py-solc-x not installed. Will try to use system solc.")

# Configuration
DEFAULT_RPC_URL = "http://localhost:8545"
CONTRACT_DIR = Path(__file__).parent.parent.parent / "contracts"
DEPLOYED_DIR = Path("/opt/nexus/contracts/deployed")
LOG_DIR = Path("/opt/nexus/logs")
KEYSTORE_DIR = Path("/opt/nexus/blockchain/keystore")
PASSWORD_FILE = Path("/opt/nexus/blockchain/password.txt")

# Solidity version
SOLC_VERSION = "0.8.19"

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_solc_path():
    """Find solc compiler."""
    import shutil

    # Check system solc
    solc_path = shutil.which("solc")
    if solc_path:
        return solc_path

    # Try py-solc-x
    if HAS_SOLCX:
        try:
            install_solc(SOLC_VERSION)
            return None  # Will use solcx
        except Exception as e:
            logger.warning(f"Could not install solc via solcx: {e}")

    return None


def compile_contract(contract_path: Path) -> dict:
    """Compile a Solidity contract and return bytecode and ABI."""
    logger.info(f"Compiling {contract_path.name}...")

    contract_source = contract_path.read_text()
    contract_name = contract_path.stem

    if HAS_SOLCX:
        # Use py-solc-x
        try:
            install_solc(SOLC_VERSION)
            solcx.set_solc_version(SOLC_VERSION)
        except Exception:
            pass

        compiled = compile_standard(
            {
                "language": "Solidity",
                "sources": {
                    contract_path.name: {"content": contract_source}
                },
                "settings": {
                    "outputSelection": {
                        "*": {
                            "*": ["abi", "evm.bytecode", "evm.deployedBytecode"]
                        }
                    },
                    "optimizer": {
                        "enabled": True,
                        "runs": 200
                    }
                }
            },
            allow_paths=[str(contract_path.parent)]
        )

        contract_data = compiled["contracts"][contract_path.name][contract_name]
        return {
            "abi": contract_data["abi"],
            "bytecode": contract_data["evm"]["bytecode"]["object"]
        }
    else:
        # Use system solc
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            # Compile to get ABI
            result = subprocess.run(
                ["solc", "--abi", "--optimize", "-o", tmpdir, str(contract_path)],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                raise Exception(f"solc ABI compilation failed: {result.stderr}")

            # Compile to get bytecode
            result = subprocess.run(
                ["solc", "--bin", "--optimize", "-o", tmpdir, str(contract_path)],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                raise Exception(f"solc BIN compilation failed: {result.stderr}")

            # Read outputs
            abi_file = Path(tmpdir) / f"{contract_name}.abi"
            bin_file = Path(tmpdir) / f"{contract_name}.bin"

            abi = json.loads(abi_file.read_text())
            bytecode = bin_file.read_text().strip()

            return {
                "abi": abi,
                "bytecode": bytecode
            }


def deploy_contract(w3: Web3, account: str, compiled: dict, *constructor_args) -> str:
    """Deploy a contract and return its address."""
    contract = w3.eth.contract(
        abi=compiled["abi"],
        bytecode=compiled["bytecode"]
    )

    # Build transaction
    tx = contract.constructor(*constructor_args).build_transaction({
        "from": account,
        "nonce": w3.eth.get_transaction_count(account),
        "gas": 3000000,
        "gasPrice": w3.eth.gas_price
    })

    # Send transaction
    tx_hash = w3.eth.send_transaction(tx)
    logger.info(f"  Transaction sent: {tx_hash.hex()}")

    # Wait for receipt
    logger.info("  Waiting for confirmation...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    if receipt["status"] != 1:
        raise Exception("Contract deployment failed")

    return receipt["contractAddress"]


def save_deployment(contract_name: str, address: str, abi: list, tx_hash: str = None):
    """Save deployment information to file."""
    DEPLOYED_DIR.mkdir(parents=True, exist_ok=True)

    deployment_data = {
        "name": contract_name,
        "address": address,
        "abi": abi,
        "deployedAt": datetime.now().isoformat(),
        "transactionHash": tx_hash
    }

    output_file = DEPLOYED_DIR / f"{contract_name}.json"
    output_file.write_text(json.dumps(deployment_data, indent=2))
    logger.info(f"  Saved to {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Deploy NEXUS OS smart contracts"
    )
    parser.add_argument(
        "--rpc-url",
        default=os.environ.get("NEXUS_RPC_URL", DEFAULT_RPC_URL),
        help="Blockchain RPC URL"
    )
    parser.add_argument(
        "--keystore",
        default=str(KEYSTORE_DIR),
        help="Path to keystore directory"
    )
    parser.add_argument(
        "--password-file",
        default=str(PASSWORD_FILE),
        help="Path to password file"
    )
    parser.add_argument(
        "--contracts-dir",
        default=str(CONTRACT_DIR),
        help="Path to contracts directory"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compile only, don't deploy"
    )

    args = parser.parse_args()

    print()
    print("=" * 60)
    print("  NEXUS OS Contract Deployment")
    print("=" * 60)
    print()

    # Connect to blockchain
    logger.info(f"Connecting to {args.rpc_url}...")
    w3 = Web3(Web3.HTTPProvider(args.rpc_url))

    # Add PoA middleware for Clique consensus
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)

    if not w3.is_connected():
        logger.error("Cannot connect to blockchain. Is nexus-geth running?")
        sys.exit(1)

    logger.info(f"Connected. Chain ID: {w3.eth.chain_id}, Block: {w3.eth.block_number}")

    # Get deployer account
    accounts = w3.eth.accounts
    if not accounts:
        logger.error("No accounts available. Is the wallet unlocked?")
        sys.exit(1)

    deployer = accounts[0]
    balance = w3.eth.get_balance(deployer)
    logger.info(f"Deployer: {deployer}")
    logger.info(f"Balance: {w3.from_wei(balance, 'ether'):.4f} ETH")

    if balance == 0:
        logger.error("Deployer has no funds for gas!")
        sys.exit(1)

    # Find contracts
    contracts_dir = Path(args.contracts_dir)
    if not contracts_dir.exists():
        # Try relative path
        contracts_dir = Path(__file__).parent.parent.parent / "contracts"

    if not contracts_dir.exists():
        logger.error(f"Contracts directory not found: {contracts_dir}")
        sys.exit(1)

    contracts_to_deploy = [
        "ReasoningLedger.sol",
        "ResourceManager.sol"
    ]

    deployed = {}

    for contract_file in contracts_to_deploy:
        contract_path = contracts_dir / contract_file
        contract_name = contract_path.stem

        if not contract_path.exists():
            logger.warning(f"Contract not found: {contract_path}")
            continue

        print()
        logger.info(f"Processing {contract_name}...")

        try:
            # Compile
            compiled = compile_contract(contract_path)
            logger.info(f"  Compiled successfully")

            if args.dry_run:
                logger.info(f"  Dry run - skipping deployment")
                continue

            # Deploy
            logger.info(f"  Deploying...")
            address = deploy_contract(w3, deployer, compiled)
            logger.info(f"  Deployed at: {address}")

            # Save
            save_deployment(contract_name, address, compiled["abi"])
            deployed[contract_name] = address

        except Exception as e:
            logger.error(f"  Failed: {e}")
            continue

    # Summary
    print()
    print("=" * 60)
    print("  Deployment Summary")
    print("=" * 60)

    if deployed:
        for name, address in deployed.items():
            print(f"  {name}: {address}")
        print()
        print(f"  Contract data saved to: {DEPLOYED_DIR}")
    elif args.dry_run:
        print("  Dry run completed - no contracts deployed")
    else:
        print("  No contracts were deployed")

    print()

    # Write summary to log
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "contract_deployment.log"
    with open(log_file, "a") as f:
        f.write(f"\n{'=' * 40}\n")
        f.write(f"Deployment: {datetime.now().isoformat()}\n")
        for name, address in deployed.items():
            f.write(f"  {name}: {address}\n")

    return 0 if deployed or args.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
