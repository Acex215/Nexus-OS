#!/usr/bin/env python3
"""NEXUS Behavioral Collection — Data Integrity Checker.

Verifies that on-chain action data is not corrupted:
- dataHash matches keccak256(data) for every action
- channelId, user, timestamp are valid
- Payloads are decodable (JSON or msgpack)

Usage:
    python3 verify_integrity.py
    python3 verify_integrity.py --count 50
    python3 verify_integrity.py --count 20 --verbose
"""

import argparse
import json
import sys
import time
import os

sys.path.insert(0, '/opt/nexus')

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

try:
    import msgpack
    HAS_MSGPACK = True
except ImportError:
    try:
        import rmp_serde
        HAS_MSGPACK = False
    except ImportError:
        HAS_MSGPACK = False

CHANNEL_NAMES = {
    1: 'Keystroke', 2: 'Mouse', 3: 'Window', 4: 'Web',
    5: 'Message', 6: 'File', 7: 'Clipboard', 8: 'System',
    9: 'Session', 10: 'App Lifecycle', 11: 'GPS', 12: 'Weather',
    13: 'WiFi', 14: 'Audio', 15: 'Display', 16: 'Power',
    17: 'Peripheral', 18: 'Notification', 255: 'Compound',
}

ACTION_NAMES = {
    1: {1: 'KS_BATCH', 2: 'KS_BURST_START', 3: 'KS_BURST_END',
        4: 'KS_LONG_PAUSE', 5: 'KS_DELETE_BURST', 6: 'KS_SHORTCUT'},
    2: {1: 'MOUSE_BATCH', 2: 'MOUSE_CLICK', 3: 'MOUSE_RIGHT_CLICK',
        4: 'MOUSE_DOUBLE_CLICK', 5: 'MOUSE_HOVER', 6: 'MOUSE_DRAG_START',
        7: 'MOUSE_DRAG_END', 8: 'MOUSE_SCROLL'},
    3: {1: 'WIN_FOCUS_CHANGE', 2: 'WIN_TITLE_CHANGE', 3: 'WIN_RESIZE',
        4: 'WIN_CLOSE', 7: 'WIN_MAP', 8: 'WIN_UNMAP'},
    6: {1: 'FILE_CREATE', 2: 'FILE_MODIFY', 3: 'FILE_DELETE', 4: 'FILE_RENAME'},
    15: {100: 'DISP_SCREEN_TEXT', 101: 'DISP_SCREEN_STATIC'},
}

RED = '\033[91m'
YELLOW = '\033[93m'
GREEN = '\033[92m'
BOLD = '\033[1m'
DIM = '\033[2m'
RESET = '\033[0m'


def load_contract(rpc_url):
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    with open('/opt/nexus/contracts/deployed/BehavioralActionRegistry.json', 'r') as f:
        deployed = json.load(f)

    contract = w3.eth.contract(address=deployed['address'], abi=deployed['abi'])
    return w3, contract


def decode_payload(data):
    """Try to decode action payload. Returns (format, decoded_str)."""
    if not data or len(data) == 0:
        return 'empty', '{}'

    # Try msgpack first (most Rust collector payloads)
    if HAS_MSGPACK:
        try:
            decoded = msgpack.unpackb(data, raw=False)
            return 'msgpack', json.dumps(decoded, default=str, ensure_ascii=False)
        except Exception:
            pass

    # Try JSON
    try:
        text = data.decode('utf-8') if isinstance(data, bytes) else data
        decoded = json.loads(text)
        return 'json', json.dumps(decoded, ensure_ascii=False)
    except Exception:
        pass

    # Try UTF-8 text
    try:
        text = data.decode('utf-8') if isinstance(data, bytes) else str(data)
        if text.isprintable() or len(text) < 200:
            return 'text', text
    except Exception:
        pass

    # Raw bytes
    hex_preview = data[:64].hex() if isinstance(data, bytes) else str(data)[:128]
    return 'raw', f'0x{hex_preview}...' if len(data) > 64 else f'0x{hex_preview}'


def get_action_name(channel_id, action_type):
    ch_actions = ACTION_NAMES.get(channel_id, {})
    name = ch_actions.get(action_type)
    if name:
        return name
    ch_name = CHANNEL_NAMES.get(channel_id, f'ch{channel_id}')
    return f'{ch_name}/type{action_type}'


def run_check(rpc_url, count, verbose, wallet_override):
    w3, contract = load_contract(rpc_url)

    if not w3.is_connected():
        print(f'{RED}Cannot connect to Geth at {rpc_url}{RESET}', file=sys.stderr)
        sys.exit(2)

    total_actions = contract.functions.actionCount().call()
    if total_actions == 0:
        print(f'{YELLOW}No actions on-chain.{RESET}')
        sys.exit(0)

    wallet = wallet_override or '0x817B0842B208B76A7665948F8D1A0592F9b1e958'
    now = int(time.time())
    # Deploy block timestamp (approximate)
    deploy_ts = 1774700000  # ~March 2026

    start_id = max(0, total_actions - count)
    end_id = total_actions
    actual_count = end_id - start_id

    print()
    print(f'  {BOLD}Integrity Check — Actions {start_id}..{end_id - 1} ({actual_count} actions){RESET}')
    print(f'  {DIM}───────────────────────────────────────{RESET}')

    hash_ok = 0
    hash_fail = 0
    channel_ok = 0
    channel_fail = 0
    user_ok = 0
    user_fail = 0
    decodable = 0
    raw_bytes = 0
    decode_fail = 0
    earliest_ts = None
    latest_ts = None
    samples = {}  # channel_id → (action_id, action_name, decoded_preview)
    errors = []

    for action_id in range(start_id, end_id):
        try:
            result = contract.functions.getAction(action_id).call()
        except Exception as e:
            errors.append(f'#{action_id}: getAction failed: {e}')
            continue

        user = result[0]
        channel_id = result[1]
        action_type = result[2]
        timestamp = result[3]
        epoch_ms = result[4]
        data_hash_bytes = result[5]
        data = result[6]

        # 1. Hash check
        if isinstance(data_hash_bytes, bytes):
            stored_hash = data_hash_bytes.hex()
        else:
            stored_hash = str(data_hash_bytes)

        computed_hash = w3.keccak(data).hex() if data else w3.keccak(b'').hex()

        if computed_hash == stored_hash:
            hash_ok += 1
        else:
            hash_fail += 1
            errors.append(f'#{action_id}: HASH MISMATCH ch={channel_id} '
                         f'stored={stored_hash[:16]}... computed={computed_hash[:16]}...')

        # 2. Channel check
        valid_channels = set(range(1, 19)) | {255}
        if channel_id in valid_channels:
            channel_ok += 1
        else:
            channel_fail += 1
            errors.append(f'#{action_id}: invalid channel {channel_id}')

        # 3. User check
        if user.lower() == wallet.lower():
            user_ok += 1
        else:
            user_fail += 1
            errors.append(f'#{action_id}: unexpected user {user}')

        # 4. Timestamp check
        if timestamp > 0:
            if timestamp < deploy_ts:
                errors.append(f'#{action_id}: timestamp {timestamp} before deploy')
            if timestamp > now + 60:
                errors.append(f'#{action_id}: timestamp {timestamp} in the future')

        if earliest_ts is None or (timestamp > 0 and timestamp < earliest_ts):
            earliest_ts = timestamp
        if latest_ts is None or timestamp > latest_ts:
            latest_ts = timestamp

        # 5. Decode payload
        fmt, decoded = decode_payload(data)
        if fmt in ('msgpack', 'json', 'text'):
            decodable += 1
        elif fmt == 'raw':
            raw_bytes += 1
        else:
            decode_fail += 1

        # Store sample per channel (latest wins)
        action_name = get_action_name(channel_id, action_type)
        preview = decoded[:120] + '...' if len(decoded) > 120 else decoded
        samples[channel_id] = (action_id, action_name, fmt, preview)

        if verbose:
            ch_name = CHANNEL_NAMES.get(channel_id, f'ch{channel_id}')
            print(f'  #{action_id:5d} [{ch_name}/{action_name}] ({fmt}) {preview}')

    # Summary
    checked = hash_ok + hash_fail
    print()
    print(f'  {BOLD}Results:{RESET}')
    print(f'  {DIM}───────────────────────────────────────{RESET}')

    def status(ok, total, label):
        pct = (ok / total * 100) if total > 0 else 0
        color = GREEN if ok == total else (YELLOW if pct > 90 else RED)
        return f'  {label:<16} {color}{ok}/{total} ({pct:.1f}%){RESET}'

    print(status(hash_ok, checked, 'Hash match:'))
    print(status(channel_ok, checked, 'Valid channel:'))
    print(status(user_ok, checked, 'Valid user:'))

    decode_total = decodable + raw_bytes + decode_fail
    decode_note = f' ({raw_bytes} raw bytes)' if raw_bytes > 0 else ''
    print(f'  {"Decodable:":<16} {GREEN}{decodable}/{decode_total}{RESET}{decode_note}')

    if earliest_ts and latest_ts:
        from datetime import datetime
        t1 = datetime.fromtimestamp(earliest_ts).strftime('%H:%M:%S')
        t2 = datetime.fromtimestamp(latest_ts).strftime('%H:%M:%S')
        span = latest_ts - earliest_ts
        span_str = f'{span // 60}m {span % 60}s' if span >= 60 else f'{span}s'
        print(f'  {"Time range:":<16} {t1} — {t2} ({span_str})')

    print(f'  {DIM}───────────────────────────────────────{RESET}')

    # Samples per channel
    if samples and not verbose:
        print()
        print(f'  {BOLD}Samples (one per channel):{RESET}')
        for ch in sorted(samples.keys()):
            action_id, action_name, fmt, preview = samples[ch]
            ch_name = CHANNEL_NAMES.get(ch, f'ch{ch}')
            print(f'  #{action_id} [{ch_name}/{action_name}] ({fmt}): {preview}')

    # Errors
    if errors:
        print()
        print(f'  {RED}{BOLD}Errors:{RESET}')
        for e in errors[:20]:
            print(f'  {RED}{e}{RESET}')
        if len(errors) > 20:
            print(f'  {RED}... and {len(errors) - 20} more{RESET}')

    print()

    all_ok = hash_fail == 0 and channel_fail == 0 and user_fail == 0
    if all_ok:
        print(f'  {GREEN}{BOLD}All integrity checks passed.{RESET}')
    else:
        print(f'  {RED}{BOLD}Integrity issues found!{RESET}')

    print()
    sys.exit(0 if all_ok else 1)


def main():
    parser = argparse.ArgumentParser(description='NEXUS Data Integrity Checker')
    parser.add_argument('--rpc', default='http://10.0.20.3:8545', help='Geth RPC URL')
    parser.add_argument('--count', type=int, default=100, help='Number of recent actions to check')
    parser.add_argument('--wallet', default=None, help='Expected wallet address')
    parser.add_argument('--verbose', action='store_true', help='Print every action decoded')
    args = parser.parse_args()

    run_check(args.rpc, args.count, args.verbose, args.wallet)


if __name__ == '__main__':
    main()
