#!/usr/bin/env python3
"""
NEXUS Behavioral Intelligence — Master Collector

Orchestrates 18 collection channels, batch flushing, and compound minting.

Usage:
  python3 collector.py --grant-consent          # First run: grant consent on-chain
  python3 collector.py                           # Start all channels
  python3 collector.py --channels keystroke web  # Start specific channels only
  python3 collector.py --stats-interval 30       # Print stats every 30 seconds
"""

import sys
import os
import time
import argparse
import threading

sys.path.insert(0, '/opt/nexus')

from libnexus.behavioral_client import BehavioralClient

from modules.channels.input_channels import (
    KeystrokeChannel, MouseChannel, WindowChannel, ClipboardChannel
)
from modules.channels.activity_channels import (
    WebChannel, FileChannel, MessageChannel, AppLifecycleChannel
)
from modules.channels.environment_channels import (
    GPSChannel, WeatherChannel, WiFiChannel
)
from modules.channels.system_channel import SystemChannel
from modules.channels.hardware_channels import (
    AudioChannel, DisplayChannel, PowerChannel,
    PeripheralChannel, NotificationChannel
)
from modules.channels.session_channel import SessionChannel
from modules.compound_minter import CompoundMinter, BatchFlushOrchestrator


class NexusBehavioralCollector:
    """Master behavioral data collector — orchestrates 18 channels."""

    def __init__(self, rpc_url=None, wallet=None):
        # Use default RPC from config or environment
        rpc = rpc_url or os.environ.get('NEXUS_RPC', 'http://10.0.20.3:8545')
        self.client = BehavioralClient(rpc_url=rpc, wallet=wallet)
        self.active = False

        # Initialize all 18 channels
        self.channels = {
            'keystroke':      KeystrokeChannel(self.client),
            'mouse':          MouseChannel(self.client),
            'window':         WindowChannel(self.client),
            'web':            WebChannel(self.client),
            'message':        MessageChannel(self.client),
            'file':           FileChannel(self.client),
            'clipboard':      ClipboardChannel(self.client),
            'system':         SystemChannel(self.client),
            'session':        SessionChannel(self.client),
            'app_lifecycle':  AppLifecycleChannel(self.client),
            'gps':            GPSChannel(self.client),
            'weather':        WeatherChannel(self.client),
            'wifi':           WiFiChannel(self.client),
            'audio':          AudioChannel(self.client),
            'display':        DisplayChannel(self.client),
            'power':          PowerChannel(self.client),
            'peripheral':     PeripheralChannel(self.client),
            'notification':   NotificationChannel(self.client),
        }

        # Orchestrators
        self.batch_flusher = BatchFlushOrchestrator(self.client)
        self.compound_minter = CompoundMinter(self.client)

    def start(self, channel_filter=None):
        """Start collection. Optionally filter which channels to enable."""
        if not self.client.has_consent():
            print("ERROR: No on-chain consent. Run with --grant-consent first.")
            return False

        self.active = True

        # Start channels
        started = 0
        for name, channel in self.channels.items():
            if channel_filter is None or name in channel_filter:
                channel.start()
                started += 1
            else:
                print(f"  Skipping: {name} (filtered)")

        # Start orchestrators
        self.batch_flusher.start()
        self.compound_minter.start()

        print(f"\n{'='*50}")
        print(f"  NEXUS Behavioral Collection ACTIVE")
        print(f"  Channels: {started}/18")
        print(f"  Wallet: {self.client.wallet}")
        print(f"  Contract: {self.client.contract.address}")
        print(f"  Debug mode: {self.client.is_debug_mode()}")
        print(f"{'='*50}\n")
        return True

    def stop(self):
        """Stop all collection."""
        self.active = False
        for channel in self.channels.values():
            channel.stop()
        self.batch_flusher.stop()
        self.compound_minter.stop()
        print("Collection STOPPED.")

    def get_stats(self):
        """Get collection statistics for all channels."""
        return {
            'active': self.active,
            'total_on_chain_actions': self.client.get_total_actions(),
            'total_compounds': self.client.get_total_compounds(),
            'channels': {name: ch.get_stats() for name, ch in self.channels.items()}
        }

    def print_stats(self):
        """Pretty-print collection stats."""
        stats = self.get_stats()
        print(f"\n{'─'*60}")
        print(f"  On-chain actions: {stats['total_on_chain_actions']:,}")
        print(f"  Compound tokens:  {stats['total_compounds']:,}")
        print(f"{'─'*60}")
        for name, cs in sorted(stats['channels'].items()):
            status = "●" if cs['active'] else "○"
            epm = cs.get('events_per_minute', 0)
            err = f" ({cs['errors']} err)" if cs.get('errors', 0) > 0 else ""
            print(f"  {status} {name:20s}  {cs['event_count']:>8,} events  {epm:>6.1f}/min{err}")
        print(f"{'─'*60}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='NEXUS Behavioral Collector')
    parser.add_argument('--grant-consent', action='store_true',
                        help='Grant consent on-chain before starting')
    parser.add_argument('--channels', nargs='*', default=None,
                        help='Specific channels to enable (default: all)')
    parser.add_argument('--stats-interval', type=int, default=60,
                        help='Print stats every N seconds (default: 60)')
    parser.add_argument('--rpc', default=None,
                        help='Geth RPC URL (default: http://10.0.20.3:8545)')
    args = parser.parse_args()

    collector = NexusBehavioralCollector(rpc_url=args.rpc)

    if args.grant_consent:
        print("Granting behavioral collection consent on-chain...")
        collector.client.grant_consent()
        # Create local consent file for systemd ConditionPathExists
        os.makedirs('/opt/nexus/config', exist_ok=True)
        import json
        with open('/opt/nexus/config/behavioral_consent_active', 'w') as f:
            json.dump({'granted_at': int(time.time()), 'wallet': collector.client.wallet}, f)
        print("Consent granted.")

    channel_filter = set(args.channels) if args.channels else None
    if not collector.start(channel_filter):
        sys.exit(1)

    try:
        while True:
            time.sleep(args.stats_interval)
            collector.print_stats()
    except KeyboardInterrupt:
        print("\nStopping...")
        collector.stop()
        collector.print_stats()
