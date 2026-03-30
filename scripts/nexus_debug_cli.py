#!/usr/bin/env python3
"""NEXUS Behavioral Collection — Interactive Debug CLI.

Browse on-chain behavioral data before calling disableDebugMode().
Uses Python cmd.Cmd REPL with decoded action payloads.

Usage:
    python3 nexus_debug_cli.py
    python3 nexus_debug_cli.py --utc
    python3 nexus_debug_cli.py --rpc http://10.0.20.3:8545
"""

import argparse
import cmd
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, '/opt/nexus')

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

try:
    import msgpack
    HAS_MSGPACK = True
except ImportError:
    HAS_MSGPACK = False

# ═══════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════

CHANNEL_NAMES = {
    1: 'Keystroke', 2: 'Mouse', 3: 'Window', 4: 'Web',
    5: 'Message', 6: 'File', 7: 'Clipboard', 8: 'System',
    9: 'Session', 10: 'AppLifecycle', 11: 'GPS', 12: 'Weather',
    13: 'WiFi', 14: 'Audio', 15: 'Display', 16: 'Power',
    17: 'Peripheral', 18: 'Notification', 255: 'Compound',
}

ACTION_NAMES = {
    (1, 1): 'KS_BATCH', (1, 2): 'KS_BURST_START', (1, 3): 'KS_BURST_END',
    (1, 4): 'KS_LONG_PAUSE', (1, 5): 'KS_DELETE_BURST', (1, 6): 'KS_SHORTCUT',
    (2, 1): 'MOUSE_BATCH', (2, 2): 'MOUSE_CLICK', (2, 3): 'MOUSE_RIGHT_CLICK',
    (2, 4): 'MOUSE_DOUBLE_CLICK', (2, 5): 'MOUSE_HOVER',
    (2, 6): 'MOUSE_DRAG_START', (2, 7): 'MOUSE_DRAG_END', (2, 8): 'MOUSE_SCROLL',
    (3, 1): 'FOCUS_CHANGE', (3, 2): 'TITLE_CHANGE', (3, 3): 'RESIZE',
    (3, 4): 'CLOSE', (3, 7): 'MAP', (3, 8): 'UNMAP',
    (4, 1): 'URL_VISIT', (4, 2): 'SEARCH',
    (5, 1): 'MSG_NOTIF',
    (6, 1): 'CREATE', (6, 2): 'MODIFY', (6, 3): 'DELETE', (6, 4): 'RENAME',
    (7, 1): 'COPY',
    (8, 1): 'SNAPSHOT', (8, 6): 'RESOURCE',
    (9, 1): 'LOGIN', (9, 3): 'LOCK', (9, 4): 'UNLOCK',
    (9, 5): 'IDLE_START', (9, 6): 'IDLE_END', (9, 7): 'BREAK_START', (9, 8): 'BREAK_END',
    (14, 1): 'VOL_UP', (14, 2): 'VOL_DOWN', (14, 3): 'MUTE', (14, 4): 'UNMUTE',
    (14, 5): 'OUTPUT_CHANGE', (14, 6): 'PLAY_START', (14, 7): 'PLAY_STOP',
    (15, 1): 'BRIGHTNESS', (15, 100): 'SCREEN_TEXT', (15, 101): 'SCREEN_STATIC',
    (17, 1): 'USB_CONNECT', (17, 2): 'USB_DISCONNECT',
    (17, 3): 'BT_CONNECT', (17, 4): 'BT_DISCONNECT',
    (18, 1): 'RECEIVED', (18, 2): 'CLICKED', (18, 3): 'DISMISSED', (18, 4): 'TIMEOUT',
}

G = '\033[92m'
Y = '\033[93m'
R = '\033[91m'
B = '\033[1m'
D = '\033[2m'
X = '\033[0m'


# ═══════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════

def decode_payload(data):
    if not data:
        return 'empty', {}
    if HAS_MSGPACK:
        try:
            return 'msgpack', msgpack.unpackb(data, raw=False)
        except Exception:
            pass
    try:
        return 'json', json.loads(data.decode('utf-8'))
    except Exception:
        pass
    return 'raw', data.hex()


def short_addr(addr):
    if len(addr) >= 10:
        return f'{addr[:6]}...{addr[-4:]}'
    return addr


def action_type_name(ch, at):
    return ACTION_NAMES.get((ch, at), f'type{at}')


def format_ts(ts, use_utc):
    if ts == 0:
        return '—'
    if use_utc:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    return datetime.fromtimestamp(ts).strftime('%H:%M:%S')


def summarize_action(action_id, ch, at, ts, data_decoded, use_utc):
    """One-line summary of an action."""
    ch_name = CHANNEL_NAMES.get(ch, f'ch{ch}')
    at_name = action_type_name(ch, at)
    ts_str = format_ts(ts, use_utc)

    detail = ''
    if isinstance(data_decoded, dict):
        detail = summarize_dict(ch, at, data_decoded)
    elif isinstance(data_decoded, (list, tuple)):
        detail = summarize_list(ch, at, data_decoded)
    elif isinstance(data_decoded, str):
        detail = data_decoded[:60]

    return f'#{action_id:<5d} [{ts_str}] {ch_name}/{at_name:<16s} {detail}'


def summarize_dict(ch, at, d):
    if ch == 1 and at == 1:  # KS_BATCH
        return f'{d.get("n", "?")} keys dev={d.get("dev", "?")} src={d.get("src", "?")}'
    if ch == 1 and at == 4:  # KS_LONG_PAUSE
        return f'pause={d.get("pause_ms", "?")}ms'
    if ch == 2 and at == 1:  # MOUSE_BATCH
        return f'{d.get("n_pos", "?")} pos dist={d.get("dist", "?")}px'
    if ch == 2 and at == 5:  # MOUSE_HOVER
        return f'x={d.get("x")} y={d.get("y")} dur={d.get("duration_ms")}ms'
    if ch == 3 and at == 1:  # FOCUS_CHANGE
        return f'"{d.get("title", "")[:40]}" ({d.get("category", "")})'
    if ch == 3 and at == 2:  # TITLE_CHANGE
        return f'"{d.get("new_title", "")[:40]}"'
    if ch == 6:  # FILE
        return d.get('path', '')[:60]
    if ch == 4 and at == 1:  # URL_VISIT
        return f'{d.get("domain", "")} [{d.get("category", "")}]'
    if ch == 4 and at == 2:  # SEARCH
        return f'{d.get("engine", "")}: {d.get("query", "")[:40]}'
    if ch == 7:  # CLIPBOARD
        return f'{d.get("content_type", "text")} len={d.get("len", "?")} src={d.get("src_class", "")}'
    if ch == 18:  # NOTIFICATION
        return f'{d.get("app", "")} — {d.get("summary", "")[:40]}'
    # Generic
    keys = list(d.keys())[:4]
    parts = [f'{k}={str(d[k])[:20]}' for k in keys]
    return ' '.join(parts)


def summarize_list(ch, at, lst):
    if ch == 8:  # System snapshot as list
        if len(lst) >= 4:
            return f'cpu/mem/net snapshot ({len(lst)} fields)'
    if ch == 10:  # AppLifecycle as list
        if len(lst) >= 3:
            pid, name = lst[0], lst[1] if len(lst) > 1 else '?'
            etype = lst[3] if len(lst) > 3 else '?'
            label = {1: 'started', 2: 'exited', 3: 'crashed'}.get(etype, f'type{etype}')
            return f'pid={pid} "{name}" {label}'
    return f'[{len(lst)} items]'


# ═══════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════

class NexusDebugCLI(cmd.Cmd):
    intro = f'\n  {B}NEXUS Debug CLI{X} — type {B}help{X} for commands, {B}quit{X} to exit\n'
    prompt = f'{B}nexus>{X} '

    def __init__(self, rpc_url, use_utc):
        super().__init__()
        self.use_utc = use_utc
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        with open('/opt/nexus/contracts/deployed/BehavioralActionRegistry.json') as f:
            deployed = json.load(f)
        self.contract = self.w3.eth.contract(address=deployed['address'], abi=deployed['abi'])
        self.contract_addr = deployed['address']
        self.wallet = '0x817B0842B208B76A7665948F8D1A0592F9b1e958'
        self.rpc_url = rpc_url

        if not self.w3.is_connected():
            print(f'{R}Cannot connect to {rpc_url}{X}')
            sys.exit(1)

    def _get_action(self, action_id):
        result = self.contract.functions.getAction(action_id).call()
        return {
            'user': result[0], 'channelId': result[1], 'actionType': result[2],
            'timestamp': result[3], 'epochMs': result[4],
            'dataHash': result[5].hex() if isinstance(result[5], bytes) else str(result[5]),
            'data': result[6],
        }

    def _total_actions(self):
        return self.contract.functions.actionCount().call()

    def _total_compounds(self):
        return self.contract.functions.compoundCount().call()

    # ─── stats ────────────────────────────
    def do_stats(self, arg):
        """Show channel coverage report."""
        total = self._total_actions()
        compounds = self._total_compounds()
        block = self.w3.eth.block_number
        debug = self.contract.functions.debugMode().call()

        print(f'\n  {B}═══════════════════════════════════════{X}')
        print(f'  Contract: {short_addr(self.contract_addr)}')
        print(f'  Actions: {total:,}   Compounds: {compounds}')
        print(f'  Block: {block:,}   Debug: {debug}')
        print(f'  {B}═══════════════════════════════════════{X}')
        print(f'  {"Ch":>3}  {"Channel":<14} {"Count":>7}  Status')
        print(f'  {D}─────────────────────────────────────{X}')

        for ch in range(1, 19):
            try:
                count = self.contract.functions.getChannelStats(self.wallet, ch).call()
            except Exception:
                count = 0
            name = CHANNEL_NAMES.get(ch, f'ch{ch}')
            if count == 0:
                status = f'{R}✗{X}'
            elif count <= 5:
                status = f'{Y}✓{X}'
            else:
                status = f'{G}✓{X}'
            print(f'  {ch:>3}  {name:<14} {count:>7,}  {status}')

        print(f'  {D}─────────────────────────────────────{X}\n')

    # ─── last ─────────────────────────────
    def do_last(self, arg):
        """Show last N actions. Usage: last [N]"""
        n = int(arg) if arg.strip() else 10
        total = self._total_actions()
        start = max(0, total - n)
        for i in range(start, total):
            try:
                a = self._get_action(i)
                fmt, decoded = decode_payload(a['data'])
                line = summarize_action(i, a['channelId'], a['actionType'],
                                       a['timestamp'], decoded, self.use_utc)
                print(f'  {line}')
            except Exception as e:
                print(f'  #{i}: error: {e}')
        print()

    # ─── channel ──────────────────────────
    def do_channel(self, arg):
        """Show actions from a channel. Usage: channel <id> [last N]"""
        parts = arg.split()
        if not parts:
            print('  Usage: channel <id> [last N]')
            return
        ch_id = int(parts[0])
        n = 10
        if len(parts) >= 3 and parts[1] == 'last':
            n = int(parts[2])

        total = self._total_actions()
        found = 0
        # Scan backwards
        for i in range(total - 1, max(-1, total - 500), -1):
            if found >= n:
                break
            try:
                a = self._get_action(i)
                if a['channelId'] == ch_id:
                    fmt, decoded = decode_payload(a['data'])
                    line = summarize_action(i, a['channelId'], a['actionType'],
                                           a['timestamp'], decoded, self.use_utc)
                    print(f'  {line}')
                    found += 1
            except Exception:
                continue
        if found == 0:
            ch_name = CHANNEL_NAMES.get(ch_id, f'ch{ch_id}')
            print(f'  No {ch_name} actions found in last 500')
        print()

    # ─── action ───────────────────────────
    def do_action(self, arg):
        """Show full details for an action. Usage: action <id>"""
        if not arg.strip():
            print('  Usage: action <id>')
            return
        action_id = int(arg)
        try:
            a = self._get_action(action_id)
        except Exception as e:
            print(f'  {R}Error: {e}{X}')
            return

        ch_name = CHANNEL_NAMES.get(a['channelId'], f'ch{a["channelId"]}')
        at_name = action_type_name(a['channelId'], a['actionType'])
        ts_str = format_ts(a['timestamp'], True)

        # Hash check
        computed = self.w3.keccak(a['data']).hex()
        hash_ok = computed == a['dataHash']

        fmt, decoded = decode_payload(a['data'])

        print(f'\n  {B}Action #{action_id}{X}')
        print(f'  {D}────────────────────────────────{X}')
        print(f'  Channel:    {a["channelId"]} ({ch_name})')
        print(f'  Type:       {a["actionType"]} ({at_name})')
        print(f'  Time:       {ts_str}')
        print(f'  Epoch ms:   {a["epochMs"]}')
        print(f'  User:       {short_addr(a["user"])}')
        print(f'  Data Hash:  {a["dataHash"][:32]}...')
        hash_mark = f'{G}✓{X}' if hash_ok else f'{R}✗ MISMATCH{X}'
        print(f'  Hash Valid: {hash_mark}')
        print(f'  Data size:  {len(a["data"])} bytes ({fmt})')
        print(f'  {D}────────────────────────────────{X}')

        if isinstance(decoded, (dict, list)):
            print(f'  Data (decoded {fmt}):')
            print(json.dumps(decoded, indent=4, default=str, ensure_ascii=False))
        else:
            print(f'  Data ({fmt}):')
            print(f'  {str(decoded)[:500]}')
        print()

    # ─── compound ─────────────────────────
    def do_compound(self, arg):
        """Show compound token details. Usage: compound <id>"""
        if not arg.strip():
            print('  Usage: compound <id>')
            return
        compound_id = int(arg)
        try:
            result = self.contract.functions.getCompound(compound_id).call()
        except Exception as e:
            print(f'  {R}Error: {e}{X}')
            return

        user = result[0]
        start_id = result[1]
        end_id = result[2]
        start_time = result[3]
        end_time = result[4]
        action_count = result[5]
        corr_hash = result[6].hex() if isinstance(result[6], bytes) else str(result[6])

        t1 = format_ts(start_time, True)
        t2 = format_ts(end_time, True)
        span = end_time - start_time if end_time > start_time else 0
        span_str = f'{span // 60}m {span % 60}s'

        print(f'\n  {B}Compound #{compound_id}{X}')
        print(f'  {D}────────────────────────────────{X}')
        print(f'  Actions:    #{start_id} — #{end_id} ({action_count} actions)')
        print(f'  Time:       {t1} — {t2} ({span_str})')
        print(f'  User:       {short_addr(user)}')
        print(f'  Corr Hash:  {corr_hash[:32]}...')
        print()

    # ─── search ───────────────────────────
    def do_search(self, arg):
        """Search action data for text. Usage: search <text>"""
        if not arg.strip():
            print('  Usage: search <text>')
            return
        query = arg.strip().lower()
        total = self._total_actions()
        scan = min(total, 500)
        found = 0
        print(f'  Searching last {scan} actions for "{arg.strip()}"...')
        for i in range(total - 1, max(-1, total - scan - 1), -1):
            try:
                a = self._get_action(i)
                fmt, decoded = decode_payload(a['data'])
                text = json.dumps(decoded, default=str) if isinstance(decoded, (dict, list)) else str(decoded)
                if query in text.lower():
                    line = summarize_action(i, a['channelId'], a['actionType'],
                                           a['timestamp'], decoded, self.use_utc)
                    print(f'  {line}')
                    found += 1
            except Exception:
                continue
        print(f'  Found {found} matches.\n')

    # ─── timeline ─────────────────────────
    def do_timeline(self, arg):
        """Show activity timeline. Usage: timeline [minutes]"""
        minutes = int(arg) if arg.strip() else 30
        total = self._total_actions()
        now = int(time.time())
        cutoff = now - minutes * 60

        # Collect actions into 5-minute buckets
        bucket_size = 300  # 5 minutes
        buckets = {}
        ch_counts = {}

        scan = min(total, 2000)
        for i in range(total - 1, max(-1, total - scan - 1), -1):
            try:
                a = self._get_action(i)
                ts = a['timestamp']
                if ts < cutoff:
                    break
                bucket = (ts // bucket_size) * bucket_size
                buckets[bucket] = buckets.get(bucket, 0) + 1
                key = (bucket, a['channelId'])
                ch_counts[key] = ch_counts.get(key, 0) + 1
            except Exception:
                continue

        if not buckets:
            print(f'  No actions in last {minutes} minutes.\n')
            return

        max_count = max(buckets.values()) if buckets else 1
        bar_width = 40

        print(f'\n  {B}Timeline (last {minutes} min, 5-min buckets){X}')
        print(f'  {D}{"─" * 55}{X}')

        for bucket_ts in sorted(buckets.keys()):
            count = buckets[bucket_ts]
            bar_len = int((count / max_count) * bar_width) if max_count > 0 else 0
            bar = '█' * bar_len
            ts_str = datetime.fromtimestamp(bucket_ts).strftime('%H:%M')

            # Find dominant channel
            dominant_ch = 0
            dominant_count = 0
            for ch in range(1, 19):
                c = ch_counts.get((bucket_ts, ch), 0)
                if c > dominant_count:
                    dominant_count = c
                    dominant_ch = ch
            dom_name = CHANNEL_NAMES.get(dominant_ch, '?').lower()

            print(f'  {ts_str}  {G}{bar}{X} {count} ({dom_name})')

        print(f'  {D}{"─" * 55}{X}\n')

    # ─── export ───────────────────────────
    def do_export(self, arg):
        """Export actions to JSON. Usage: export <filename>"""
        if not arg.strip():
            print('  Usage: export <filename>')
            return
        filename = arg.strip()
        if not filename.endswith('.json'):
            filename += '.json'

        export_dir = '/opt/nexus/exports'
        os.makedirs(export_dir, exist_ok=True)
        path = os.path.join(export_dir, filename)

        total = self._total_actions()
        n = min(total, 1000)
        start = total - n

        print(f'  Exporting actions {start}..{total - 1} to {path}...')
        actions = []
        for i in range(start, total):
            try:
                a = self._get_action(i)
                fmt, decoded = decode_payload(a['data'])
                actions.append({
                    'id': i,
                    'channel': a['channelId'],
                    'channel_name': CHANNEL_NAMES.get(a['channelId'], f'ch{a["channelId"]}'),
                    'action_type': a['actionType'],
                    'action_name': action_type_name(a['channelId'], a['actionType']),
                    'timestamp': a['timestamp'],
                    'user': a['user'],
                    'data_hash': a['dataHash'],
                    'data_format': fmt,
                    'data': decoded,
                })
            except Exception as e:
                actions.append({'id': i, 'error': str(e)})

        with open(path, 'w') as f:
            json.dump(actions, f, indent=2, default=str, ensure_ascii=False)

        print(f'  Exported {len(actions)} actions to {path}\n')

    # ─── contract ─────────────────────────
    def do_contract(self, arg):
        """Show contract state."""
        addr = self.contract_addr
        debug = self.contract.functions.debugMode().call()
        admin = self.contract.functions.admin().call()
        locked = self.contract.functions.adminLocked().call()
        actions = self._total_actions()
        compounds = self._total_compounds()
        block = self.w3.eth.block_number
        chain_id = self.w3.eth.chain_id

        print(f'\n  {B}Contract State{X}')
        print(f'  {D}────────────────────────────────{X}')
        print(f'  Address:      {addr}')
        print(f'  Debug mode:   {debug}')
        print(f'  Admin:        {short_addr(admin)}')
        print(f'  Admin locked: {locked}')
        print(f'  Actions:      {actions:,}')
        print(f'  Compounds:    {compounds}')
        print(f'  Block:        {block:,}')
        print(f'  Chain ID:     {chain_id}')
        print(f'  RPC:          {self.rpc_url}')
        print()

    # ─── consent ──────────────────────────
    def do_consent(self, arg):
        """Show consent state for the wallet."""
        has = self.contract.functions.hasConsent(self.wallet).call()
        granted = self.contract.functions.consentGrantedAt(self.wallet).call()
        revoked = self.contract.functions.consentRevokedAt(self.wallet).call()

        print(f'\n  {B}Consent State{X}')
        print(f'  {D}────────────────────────────────{X}')
        print(f'  Wallet:     {short_addr(self.wallet)}')
        status = f'{G}GRANTED{X}' if has else f'{R}NOT GRANTED{X}'
        print(f'  Has consent: {status}')
        print(f'  Granted at: {format_ts(granted, True) if granted else "never"}')
        print(f'  Revoked at: {format_ts(revoked, True) if revoked else "never"}')
        print()

    # ─── quit ─────────────────────────────
    def do_quit(self, arg):
        """Exit the CLI."""
        print('  Goodbye.')
        return True

    def do_exit(self, arg):
        """Exit the CLI."""
        return self.do_quit(arg)

    def do_EOF(self, arg):
        """Handle Ctrl+D."""
        print()
        return self.do_quit(arg)

    def emptyline(self):
        pass


def main():
    parser = argparse.ArgumentParser(description='NEXUS Debug CLI')
    parser.add_argument('--rpc', default='http://10.0.20.3:8545')
    parser.add_argument('--utc', action='store_true', help='Show timestamps in UTC')
    args = parser.parse_args()

    try:
        cli = NexusDebugCLI(args.rpc, args.utc)
        cli.cmdloop()
    except KeyboardInterrupt:
        print('\n  Goodbye.')


if __name__ == '__main__':
    main()
