#!/usr/bin/env python3
"""NEXUS Daily Cycle — federated epoch management + ECT mint.

Run via systemd timer at 00:05 UTC daily.
1. Finalize previous federated learning epoch (if active)
2. Start new epoch
3. Mint daily ECT to all registered nodes

Usage: cd /opt/nexus && python3 scripts/daily_epoch_cycle.py
"""
import sys
import os
import json
import logging

sys.path.insert(0, '/opt/nexus')

os.makedirs('/opt/nexus/logs', exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [daily-cycle] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/opt/nexus/logs/daily_cycle.log', mode='a'),
    ]
)
log = logging.getLogger("daily_cycle")

DEPLOYER = '0x817B0842B208B76A7665948F8D1A0592F9b1e958'
ECT_PER_NODE = 1000

from web3 import Web3
from libnexus.token_client import TokenClient


def do_epoch_cycle():
    """Finalize previous epoch, start new one."""
    try:
        from libnexus.flock_client import FlockClient
    except FileNotFoundError:
        log.warning("FlockCoordinator not deployed — skipping epoch cycle")
        return

    try:
        fc = FlockClient(wallet=DEPLOYER)
    except Exception as e:
        log.warning("FlockClient init failed: %s — skipping epoch cycle", e)
        return

    epoch = fc.get_current_epoch()
    epoch_id = epoch['epochId']

    # Finalize previous epoch if it exists and is still active
    if epoch_id > 0 and not epoch['finalized']:
        # Placeholder aggregated model hash until real aggregation is implemented
        placeholder = Web3.keccak(text=f"aggregate-epoch-{epoch_id}")
        count = epoch['submissionCount']
        try:
            result = fc.finalize_epoch(placeholder)
            log.info("Epoch %d finalized: %d submissions (block %d)",
                     epoch_id, count, result['block'])
        except Exception as e:
            log.error("Failed to finalize epoch %d: %s", epoch_id, e)
            return

    # Start new epoch
    try:
        result = fc.start_epoch()
        new_epoch = fc.get_current_epoch()
        log.info("Epoch %d started, salt: %s (block %d)",
                 new_epoch['epochId'], new_epoch['dailySalt'], result['block'])
    except Exception as e:
        log.error("Failed to start new epoch: %s", e)


def do_ect_mint():
    """Mint daily ECT to all registered nodes."""
    # Get registered nodes from ResourceManager
    try:
        rm_path = '/opt/nexus/contracts/deployed/ResourceManager.json'
        with open(rm_path) as f:
            rm = json.load(f)
        tc = TokenClient(wallet=DEPLOYER)
        rm_contract = tc.w3.eth.contract(
            address=Web3.to_checksum_address(rm['address']),
            abi=rm['abi']
        )
        addresses = rm_contract.functions.getAllNodes().call()
        log.info("Found %d registered nodes", len(addresses))
    except Exception as e:
        log.warning("Cannot read ResourceManager: %s — minting to deployer only", e)
        addresses = []

    if not addresses:
        addresses = [DEPLOYER]

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

    for addr in addresses:
        bal = tc.get_balances(addr)
        log.info("  %s: ECT=%d RST=%d", addr[:10], bal['ect'], bal['rst'])


def main():
    log.info("=== Daily cycle starting ===")

    log.info("--- Epoch cycle ---")
    do_epoch_cycle()

    log.info("--- ECT mint ---")
    do_ect_mint()

    log.info("=== Daily cycle complete ===")


if __name__ == "__main__":
    main()
