#!/usr/bin/env python3
"""NEXUS Behavioral Collection — Channel Coverage Report.

Queries the BehavioralActionRegistry contract for per-channel action counts
and prints a coverage report showing which channels have data on-chain.

Usage:
    python3 verify_collection.py
    python3 verify_collection.py --json
    python3 verify_collection.py --min-actions 5
"""

import argparse
import json
import sys
import os

sys.path.insert(0, '/opt/nexus')

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

CHANNEL_NAMES = {
    1: 'Keystroke',
    2: 'Mouse',
    3: 'Window',
    4: 'Web',
    5: 'Message',
    6: 'File',
    7: 'Clipboard',
    8: 'System',
    9: 'Session',
    10: 'App Lifecycle',
    11: 'GPS',
    12: 'Weather',
    13: 'WiFi',
    14: 'Audio',
    15: 'Display',
    16: 'Power',
    17: 'Peripheral',
    18: 'Notification',
}

# ANSI colors
RED = '\033[91m'
YELLOW = '\033[93m'
GREEN = '\033[92m'
BOLD = '\033[1m'
DIM = '\033[2m'
RESET = '\033[0m'


def load_contract(rpc_url):
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    deployed_path = '/opt/nexus/contracts/deployed/BehavioralActionRegistry.json'
    with open(deployed_path, 'r') as f:
        deployed = json.load(f)

    contract = w3.eth.contract(address=deployed['address'], abi=deployed['abi'])
    return w3, contract, deployed['address']


def get_wallet():
    config_path = '/opt/nexus/config/node_identity.json'
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            addr = json.load(f).get('wallet_address')
            if addr:
                return addr
    # Fallback to deployer
    return '0x817B0842B208B76A7665948F8D1A0592F9b1e958'


def get_time_range(contract, total_actions, wallet):
    """Get earliest and latest action timestamps for rate calculation."""
    if total_actions < 2:
        return None, None

    earliest_ts = None
    latest_ts = None

    # Read first few actions to find earliest
    for i in range(min(total_actions, 5)):
        try:
            result = contract.functions.getAction(i).call()
            ts = result[3]  # timestamp field
            if ts > 0:
                if earliest_ts is None or ts < earliest_ts:
                    earliest_ts = ts
                break
        except Exception:
            continue

    # Read last few actions for latest
    for i in range(max(0, total_actions - 5), total_actions):
        try:
            result = contract.functions.getAction(i).call()
            ts = result[3]
            if ts > 0:
                latest_ts = ts
        except Exception:
            continue

    return earliest_ts, latest_ts


def run_report(rpc_url, wallet_override, min_actions, output_json):
    w3, contract, contract_addr = load_contract(rpc_url)

    if not w3.is_connected():
        print(f'{RED}Cannot connect to Geth at {rpc_url}{RESET}', file=sys.stderr)
        sys.exit(2)

    wallet = wallet_override or get_wallet()
    total_actions = contract.functions.actionCount().call()
    total_compounds = contract.functions.compoundCount().call()
    debug_mode = contract.functions.debugMode().call()
    block = w3.eth.block_number

    # Per-channel stats
    channels = {}
    for ch in range(1, 19):
        try:
            count = contract.functions.getChannelStats(wallet, ch).call()
        except Exception:
            count = 0
        channels[ch] = count

    # Time range for rate calculation
    earliest_ts, latest_ts = get_time_range(contract, total_actions, wallet)
    duration_min = 0.0
    if earliest_ts and latest_ts and latest_ts > earliest_ts:
        duration_min = (latest_ts - earliest_ts) / 60.0

    # Coverage
    active_count = sum(1 for c in channels.values() if c > 0)
    all_covered = all(c >= min_actions for c in channels.values())

    if output_json:
        report = {
            'wallet': wallet,
            'contract': contract_addr,
            'total_actions': total_actions,
            'total_compounds': total_compounds,
            'block': block,
            'debug_mode': debug_mode,
            'duration_minutes': round(duration_min, 1),
            'channels': {
                str(ch): {
                    'name': CHANNEL_NAMES[ch],
                    'actions': count,
                    'rate_per_min': round(count / duration_min, 1) if duration_min > 0 else 0,
                    'status': 'active' if count > 5 else ('low' if count > 0 else 'missing'),
                }
                for ch, count in channels.items()
            },
            'coverage': f'{active_count}/18',
            'pass': all_covered,
        }
        print(json.dumps(report, indent=2))
        sys.exit(0 if all_covered else 1)

    # Pretty print
    short_wallet = f'{wallet[:8]}...{wallet[-4:]}'
    short_contract = f'{contract_addr[:6]}...{contract_addr[-4:]}'

    print()
    print(f'  {BOLD}═══════════════════════════════════════════════════════{RESET}')
    print(f'  {BOLD}NEXUS Behavioral Collection — Coverage Report{RESET}')
    print(f'  Wallet:   {short_wallet}')
    print(f'  Contract: {short_contract}')
    print(f'  Total actions: {total_actions:,}   Compounds: {total_compounds}')
    print(f'  Block: {block:,}   Debug mode: {debug_mode}')
    if duration_min > 0:
        print(f'  Collection period: {duration_min:.0f} minutes')
    print(f'  {BOLD}═══════════════════════════════════════════════════════{RESET}')
    print()
    print(f'  {"Ch":>3}  {"Channel":<18} {"Actions":>8}  {"Rate":>7}  Status')
    print(f'  {DIM}───────────────────────────────────────────────────────{RESET}')

    for ch in range(1, 19):
        count = channels[ch]
        name = CHANNEL_NAMES[ch]
        rate = count / duration_min if duration_min > 0 else 0

        if count == 0:
            status = f'{RED}✗ MISSING{RESET}'
        elif count <= 5:
            status = f'{YELLOW}✓ LOW{RESET}'
        else:
            status = f'{GREEN}✓ ACTIVE{RESET}'

        rate_str = f'{rate:.1f}/min' if duration_min > 0 else '-'
        print(f'  {ch:>3}  {name:<18} {count:>8,}  {rate_str:>7}  {status}')

    print(f'  {DIM}───────────────────────────────────────────────────────{RESET}')
    print()

    if all_covered:
        print(f'  {GREEN}{BOLD}Coverage: {active_count}/18 channels have data ✓{RESET}')
    else:
        missing = [CHANNEL_NAMES[ch] for ch, c in channels.items() if c < min_actions]
        print(f'  {RED}{BOLD}Coverage: {active_count}/18 channels — missing: {", ".join(missing)}{RESET}')

    print()
    sys.exit(0 if all_covered else 1)


def main():
    parser = argparse.ArgumentParser(description='NEXUS Behavioral Collection Coverage Report')
    parser.add_argument('--rpc', default='http://10.0.20.3:8545', help='Geth RPC URL')
    parser.add_argument('--wallet', default=None, help='Wallet address to check')
    parser.add_argument('--min-actions', type=int, default=1, help='Min actions per channel (default: 1)')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    args = parser.parse_args()

    run_report(args.rpc, args.wallet, args.min_actions, args.json)


if __name__ == '__main__':
    main()
