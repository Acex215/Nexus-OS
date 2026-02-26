#!/usr/bin/env python3
"""
NEXUS OS RF Mesh Relay Daemon

Runs as a background service providing:
  - Periodic heartbeat broadcast (every 30s) with node status
  - Alert relay: rebroadcast critical alerts from other nodes
  - Message gateway: relay fragmented data between RF and IP networks
  - Peer tracking: maintain table of RF-reachable nodes

Uses FlipperBridge for Sub-GHz TX/RX, falls back to MockFlipperBridge
if no hardware is detected.

Run as: python3 rf_mesh_daemon.py --node-num <1-4> [--mock]
"""

import argparse
import json
import logging
import os
import signal
import struct
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, '/opt/nexus')
sys.path.insert(0, '/opt/nexus/networking')

from rf_relay import (
    MsgType, RFPacket, BROADCAST_ADDR,
    wallet_to_bytes, bytes_to_wallet,
    make_heartbeat, make_alert,
    fragment_message, reassemble_message,
    ALERT_NODE_DOWN, ALERT_CHAIN_STALL, ALERT_STORAGE_FULL, ALERT_SECURITY
)
from flipper_bridge import FlipperBridge, MockFlipperBridge

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [rf-mesh] %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)

# Timing
HEARTBEAT_INTERVAL = 30  # seconds
PEER_TIMEOUT = 120  # seconds before peer considered offline
ALERT_REBROADCAST_TTL = 3  # max times to rebroadcast an alert
FRAG_REASSEMBLY_TIMEOUT = 60  # seconds to wait for all fragments

# Node configuration (mirrors mesh_discovery.py)
NODE_MAP = {
    1: {'name': 'nexus-master', 'wallet': '0x817B0842B208B76A7665948F8D1A0592F9b1e958'},
    2: {'name': 'nexus-ai',     'wallet': '0x817B0842B208B76A7665948F8D1A0592F9b1e958'},
    3: {'name': 'nexus-storage','wallet': '0x817B0842B208B76A7665948F8D1A0592F9b1e958'},
    4: {'name': 'nexus-admin',  'wallet': '0x817B0842B208B76A7665948F8D1A0592F9b1e958'},
}


@dataclass
class RFPeer:
    """Tracked RF peer node."""
    wallet: str
    node_num: int
    last_seen: float
    block_height: int = 0
    rssi: int = 0
    packets_rx: int = 0

    @property
    def is_alive(self) -> bool:
        return (time.time() - self.last_seen) < PEER_TIMEOUT


@dataclass
class FragmentBuffer:
    """Buffer for reassembling fragmented messages."""
    sender: bytes
    packets: list[RFPacket] = field(default_factory=list)
    created: float = field(default_factory=time.time)
    expected_total: int = 0

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created) > FRAG_REASSEMBLY_TIMEOUT

    @property
    def is_complete(self) -> bool:
        return len(self.packets) == self.expected_total > 0


class RFMeshDaemon:
    """RF mesh relay daemon."""

    def __init__(self, node_num: int, mock: bool = False):
        self.node_num = node_num
        self.node_info = NODE_MAP[node_num]
        self.wallet = self.node_info['wallet']
        self.wallet_bytes = wallet_to_bytes(self.wallet)

        # RF bridge
        if mock:
            self.bridge = MockFlipperBridge(on_receive=self._on_packet_rx)
        else:
            self.bridge = FlipperBridge(on_receive=self._on_packet_rx)

        # State
        self.peers: dict[str, RFPeer] = {}  # wallet_hex -> RFPeer
        self.frag_buffers: dict[bytes, FragmentBuffer] = {}  # sender_bytes -> buffer
        self.seen_alerts: set[bytes] = set()  # track alert dedup (sender+seq)
        self.seq_num = 0
        self._running = False
        self._lock = threading.Lock()

        # Stats
        self.stats = {
            'tx_packets': 0,
            'rx_packets': 0,
            'heartbeats_sent': 0,
            'heartbeats_rx': 0,
            'alerts_relayed': 0,
            'fragments_rx': 0,
            'messages_reassembled': 0,
        }

    def _next_seq(self) -> int:
        seq = self.seq_num
        self.seq_num = (self.seq_num + 1) % 256
        return seq

    def _get_block_height(self) -> int:
        """Get current blockchain block number."""
        try:
            from libnexus import NexusKernel
            kernel = NexusKernel(wallet=self.wallet)
            return kernel.get_block_number()
        except Exception:
            return 0

    def _on_packet_rx(self, packet: RFPacket):
        """Handle incoming RF packet."""
        self.stats['rx_packets'] += 1
        sender_hex = bytes_to_wallet(packet.sender)

        # Skip our own packets (loopback)
        if packet.sender == self.wallet_bytes:
            return

        logger.debug(f"RX from {sender_hex[:10]}...: {packet.msg_type.name}")

        if packet.msg_type == MsgType.HEARTBEAT:
            self._handle_heartbeat(packet, sender_hex)
        elif packet.msg_type == MsgType.ALERT:
            self._handle_alert(packet, sender_hex)
        elif packet.msg_type == MsgType.FRAG_DATA:
            self._handle_fragment(packet, sender_hex)
        elif packet.msg_type == MsgType.PEER_ANNOUNCE:
            self._handle_peer_announce(packet, sender_hex)
        elif packet.msg_type == MsgType.ACK:
            self._handle_ack(packet, sender_hex)
        elif packet.msg_type == MsgType.DATA:
            self._handle_data(packet, sender_hex)

    def _handle_heartbeat(self, packet: RFPacket, sender_hex: str):
        """Process heartbeat: update peer table."""
        self.stats['heartbeats_rx'] += 1
        payload = packet.payload.rstrip(b'\x00')
        if len(payload) >= 7:
            node_num, _, block_height = struct.unpack('>BHI', payload[:7])
        else:
            node_num, block_height = 0, 0

        with self._lock:
            if sender_hex in self.peers:
                peer = self.peers[sender_hex]
                peer.last_seen = time.time()
                peer.block_height = block_height
                peer.packets_rx += 1
            else:
                self.peers[sender_hex] = RFPeer(
                    wallet=sender_hex,
                    node_num=node_num,
                    last_seen=time.time(),
                    block_height=block_height,
                    packets_rx=1
                )
                logger.info(f"New RF peer: node={node_num} wallet={sender_hex[:10]}... block={block_height}")

    def _handle_alert(self, packet: RFPacket, sender_hex: str):
        """Process alert: log and rebroadcast."""
        # Dedup key: sender + seq_num
        dedup_key = packet.sender + bytes([packet.seq_num])
        if dedup_key in self.seen_alerts:
            return

        self.seen_alerts.add(dedup_key)

        payload = packet.payload.rstrip(b'\x00')
        if len(payload) >= 2:
            alert_code = struct.unpack('>H', payload[:2])[0]
            alert_msg = payload[2:].decode('utf-8', errors='replace').rstrip('\x00')
        else:
            alert_code, alert_msg = 0, ''

        alert_names = {
            ALERT_NODE_DOWN: 'NODE_DOWN',
            ALERT_CHAIN_STALL: 'CHAIN_STALL',
            ALERT_STORAGE_FULL: 'STORAGE_FULL',
            ALERT_SECURITY: 'SECURITY',
        }
        alert_name = alert_names.get(alert_code, f'0x{alert_code:04x}')
        logger.warning(f"ALERT from {sender_hex[:10]}...: [{alert_name}] {alert_msg}")

        # Rebroadcast alert (don't change sender, just relay)
        self.bridge.transmit(packet)
        self.stats['alerts_relayed'] += 1

        # Cap dedup set size
        if len(self.seen_alerts) > 1000:
            self.seen_alerts.clear()

    def _handle_fragment(self, packet: RFPacket, sender_hex: str):
        """Process fragment: buffer and reassemble."""
        self.stats['fragments_rx'] += 1

        if len(packet.payload) < 2:
            return

        frag_idx, frag_total = struct.unpack('BB', packet.payload[:2])

        with self._lock:
            key = packet.sender
            if key not in self.frag_buffers:
                self.frag_buffers[key] = FragmentBuffer(
                    sender=packet.sender,
                    expected_total=frag_total
                )

            buf = self.frag_buffers[key]
            buf.packets.append(packet)

            if buf.is_complete:
                data = reassemble_message(buf.packets)
                del self.frag_buffers[key]
                if data:
                    self.stats['messages_reassembled'] += 1
                    logger.info(f"Reassembled message from {sender_hex[:10]}...: {len(data)} bytes")
                    self._handle_reassembled(sender_hex, data)

        # Cleanup expired fragment buffers
        self._cleanup_frag_buffers()

    def _handle_reassembled(self, sender_hex: str, data: bytes):
        """Handle a fully reassembled message."""
        try:
            msg = json.loads(data.decode('utf-8'))
            logger.info(f"Reassembled JSON from {sender_hex[:10]}...: {msg}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.info(f"Reassembled binary from {sender_hex[:10]}...: {data.hex()[:40]}...")

    def _handle_peer_announce(self, packet: RFPacket, sender_hex: str):
        """Handle peer announcement (new node joining RF mesh)."""
        logger.info(f"Peer announce from {sender_hex[:10]}...")
        # Update peer table like heartbeat
        self._handle_heartbeat(packet, sender_hex)

    def _handle_ack(self, packet: RFPacket, sender_hex: str):
        """Handle ACK packet."""
        logger.debug(f"ACK from {sender_hex[:10]}... seq={packet.seq_num}")

    def _handle_data(self, packet: RFPacket, sender_hex: str):
        """Handle single-packet data."""
        payload = packet.payload.rstrip(b'\x00')
        logger.info(f"DATA from {sender_hex[:10]}...: {len(payload)} bytes")

    def _cleanup_frag_buffers(self):
        """Remove expired fragment reassembly buffers."""
        with self._lock:
            expired = [k for k, v in self.frag_buffers.items() if v.is_expired]
            for k in expired:
                logger.debug(f"Expired fragment buffer for {bytes_to_wallet(k)[:10]}...")
                del self.frag_buffers[k]

    def _heartbeat_loop(self):
        """Periodic heartbeat broadcast."""
        while self._running:
            try:
                block_height = self._get_block_height()
                hb = make_heartbeat(self.wallet, self.node_num, block_height)
                hb.seq_num = self._next_seq()
                self.bridge.transmit(hb)
                self.stats['heartbeats_sent'] += 1
                self.stats['tx_packets'] += 1
                logger.debug(f"Heartbeat sent: node={self.node_num} block={block_height}")
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")

            time.sleep(HEARTBEAT_INTERVAL)

    def _maintenance_loop(self):
        """Periodic maintenance: clean stale peers, buffers."""
        while self._running:
            time.sleep(60)

            # Check for offline peers
            with self._lock:
                for wallet_hex, peer in list(self.peers.items()):
                    if not peer.is_alive:
                        logger.warning(f"RF peer offline: node={peer.node_num} {wallet_hex[:10]}...")
                        del self.peers[wallet_hex]

            # Cleanup fragments
            self._cleanup_frag_buffers()

    def send_alert(self, alert_code: int, message: str):
        """Send an alert broadcast."""
        alert = make_alert(self.wallet, alert_code, message)
        alert.seq_num = self._next_seq()
        self.bridge.transmit(alert)
        self.stats['tx_packets'] += 1
        logger.info(f"Alert sent: code=0x{alert_code:04x} msg={message}")

    def send_data(self, recipient_wallet: str, data: bytes):
        """Send data to a specific peer (with fragmentation if needed)."""
        recipient = wallet_to_bytes(recipient_wallet)
        if len(data) <= 18:
            # Single packet
            pkt = RFPacket(
                sender=self.wallet_bytes,
                recipient=recipient,
                msg_type=MsgType.DATA,
                seq_num=self._next_seq(),
                payload=data
            )
            self.bridge.transmit(pkt)
            self.stats['tx_packets'] += 1
        else:
            # Fragmented
            packets = fragment_message(
                self.wallet_bytes, recipient, data,
                start_seq=self._next_seq()
            )
            for pkt in packets:
                self.bridge.transmit(pkt)
                self.stats['tx_packets'] += 1

    def get_status(self) -> dict:
        """Get daemon status for monitoring."""
        with self._lock:
            alive_peers = [p for p in self.peers.values() if p.is_alive]
        return {
            'node_num': self.node_num,
            'bridge_connected': self.bridge.is_connected,
            'rf_peers': len(alive_peers),
            'peers': [
                {
                    'wallet': p.wallet[:10] + '...',
                    'node_num': p.node_num,
                    'last_seen_ago': int(time.time() - p.last_seen),
                    'block_height': p.block_height,
                    'packets_rx': p.packets_rx,
                }
                for p in alive_peers
            ],
            'stats': dict(self.stats),
            'tx_queue': self.bridge.tx_queue_size,
            'frag_buffers': len(self.frag_buffers),
        }

    def start(self):
        """Start the RF mesh daemon."""
        logger.info(f"Starting RF mesh daemon: node={self.node_num} wallet={self.wallet[:10]}...")

        if not self.bridge.start():
            logger.warning("Bridge failed to start, running in degraded mode")

        self._running = True

        # Start heartbeat thread
        hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True, name='rf-heartbeat')
        hb_thread.start()

        # Start maintenance thread
        maint_thread = threading.Thread(target=self._maintenance_loop, daemon=True, name='rf-maintenance')
        maint_thread.start()

        logger.info("RF mesh daemon started")

    def stop(self):
        """Stop the daemon."""
        self._running = False
        self.bridge.stop()
        logger.info("RF mesh daemon stopped")
        logger.info(f"Stats: {json.dumps(self.stats, indent=2)}")


def main():
    parser = argparse.ArgumentParser(description='NEXUS OS RF Mesh Relay Daemon')
    parser.add_argument('--node-num', type=int, required=True, choices=[1, 2, 3, 4])
    parser.add_argument('--mock', action='store_true', help='Use mock bridge (no Flipper hardware)')
    parser.add_argument('--status', action='store_true', help='Print status and exit')
    args = parser.parse_args()

    daemon = RFMeshDaemon(node_num=args.node_num, mock=args.mock)

    # Handle signals
    def shutdown(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        daemon.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    daemon.start()

    # Main loop: periodically print status
    try:
        while True:
            time.sleep(60)
            status = daemon.get_status()
            logger.info(
                f"Status: peers={status['rf_peers']} "
                f"tx={status['stats']['tx_packets']} rx={status['stats']['rx_packets']} "
                f"queue={status['tx_queue']}"
            )
    except KeyboardInterrupt:
        daemon.stop()


if __name__ == '__main__':
    main()
