#!/usr/bin/env python3
"""NEXUS ECT Daily Cycle — mint ECT to all registered nodes.

Run via systemd timer at 00:05 UTC daily.
Mints ECT_PER_NODE to every node registered in ResourceManager.
"""
import sys, logging, json
sys.path.insert(0, '/opt/nexus')

from libnexus.token_client import TokenClient
from libnexus.kernel import NexusKernel

logging.basicConfig(level=logging.INFO, format='%(asctime)s [ect-cycle] %(message)s')
log = logging.getLogger("ect_cycle")

ECT_PER_NODE = 1000  # daily ECT allocation per node
DEPLOYER = '0x817B0842B208B76A7665948F8D1A0592F9b1e958'

def main():
    log.info("Starting daily ECT mint cycle")

    # Get all registered nodes from ResourceManager
    try:
        kernel = NexusKernel(rpc_url="http://10.0.20.3:8545", wallet=DEPLOYER)
        node_count = kernel.get_node_count() if hasattr(kernel, 'get_node_count') else 0

        # Read node addresses from ResourceManager
        from web3 import Web3
        rm_path = '/opt/nexus/contracts/deployed/ResourceManager.json'
        with open(rm_path) as f:
            rm = json.load(f)
        w3 = kernel.w3
        rm_contract = w3.eth.contract(
            address=Web3.to_checksum_address(rm['address']),
            abi=rm['abi']
        )
        addresses = rm_contract.functions.getAllNodes().call()
        log.info("Found %d registered nodes", len(addresses))
    except Exception as e:
        log.warning("Cannot read ResourceManager: %s — minting to deployer only", e)
        addresses = [DEPLOYER]

    if not addresses:
        log.info("No registered nodes. Minting to deployer as fallback.")
        addresses = [DEPLOYER]

    # Mint ECT
    tc = TokenClient(wallet=DEPLOYER)

    if len(addresses) == 1:
        r = tc.mint_daily_ect(addresses[0], ECT_PER_NODE)
        log.info("Minted %d ECT to %s (block %d)", ECT_PER_NODE, addresses[0][:10], r['block'])
    else:
        amounts = [ECT_PER_NODE] * len(addresses)
        r = tc.batch_mint_ect(addresses, amounts)
        log.info("Batch minted %d ECT to %d nodes (block %d)",
                ECT_PER_NODE, len(addresses), r['block'])

    # Report totals
    totals = tc.get_totals()
    log.info("System totals: ECT minted=%d spent=%d, RST earned=%d slashed=%d",
            totals['ect_minted'], totals['ect_spent'],
            totals['rst_earned'], totals['rst_slashed'])

    # Report per-node balances
    for addr in addresses:
        bal = tc.get_balances(addr)
        log.info("  %s: ECT=%d RST=%d", addr[:10], bal['ect'], bal['rst'])

    log.info("Daily ECT mint cycle complete")

if __name__ == "__main__":
    main()
