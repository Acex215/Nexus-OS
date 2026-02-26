#!/usr/bin/env python3
"""
NEXUS OS Network Degradation Manager

Monitors connectivity across all network layers and auto-switches
between them based on availability. Logs level transitions on-chain.

Degradation chain (best to worst):
  Level 1: Ethernet (192.168.8.0/24) — full bandwidth, <1ms
  Level 2: WiFi mesh (BATMAN-adv 10.0.0.0/24) — ~50Mbps, 1-6ms
  Level 3: WireGuard overlay (10.1.0.0/24) — encrypted tunnel
  Level 4: Sub-GHz RF (433MHz via Flipper) — 64B packets, ~1kbps
  Level 5: BLE beacon (discovery only, no data) — future

Run as: python3 degradation_manager.py --node-num <1-4> [--interval 30]
"""

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

sys.path.insert(0, '/opt/nexus')
sys.path.insert(0, '/opt/nexus/networking')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [degradation] %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)

# Node network configuration
NODE_MAP = {
    1: {
        'name': 'nexus-master',
        'eth': '192.168.8.228',
        'mesh': '10.0.0.1',
        'wg': '10.1.0.1',
    },
    2: {
        'name': 'nexus-ai',
        'eth': '192.168.8.128',
        'mesh': '10.0.0.2',
        'wg': '10.1.0.2',
    },
    3: {
        'name': 'nexus-storage',
        'eth': '192.168.8.224',
        'mesh': '10.0.0.3',
        'wg': '10.1.0.3',
    },
    4: {
        'name': 'nexus-admin',
        'eth': '192.168.8.153',
        'mesh': '10.0.0.4',
        'wg': '10.1.0.4',
    },
}


class NetLevel(IntEnum):
    ETHERNET = 1
    WIFI_MESH = 2
    WIREGUARD = 3
    SUB_GHZ_RF = 4
    BLE_ONLY = 5
    OFFLINE = 6


LEVEL_NAMES = {
    NetLevel.ETHERNET: "Ethernet",
    NetLevel.WIFI_MESH: "WiFi Mesh (BATMAN)",
    NetLevel.WIREGUARD: "WireGuard Overlay",
    NetLevel.SUB_GHZ_RF: "Sub-GHz RF (Flipper)",
    NetLevel.BLE_ONLY: "BLE Discovery Only",
    NetLevel.OFFLINE: "Offline",
}


@dataclass
class PeerStatus:
    """Connectivity status to a single peer."""
    node_num: int
    name: str
    level: NetLevel
    latency_ms: float = 0.0
    last_check: float = 0.0
    eth_ok: bool = False
    mesh_ok: bool = False
    wg_ok: bool = False
    rf_ok: bool = False


def ping_check(ip: str, timeout: float = 2.0, count: int = 1) -> tuple[bool, float]:
    """Ping an IP and return (reachable, latency_ms)."""
    try:
        result = subprocess.run(
            ['ping', '-c', str(count), '-W', str(int(timeout)), ip],
            capture_output=True, text=True, timeout=timeout + 1
        )
        if result.returncode == 0:
            # Parse average latency from ping output
            for line in result.stdout.splitlines():
                if 'avg' in line:
                    # "rtt min/avg/max/mdev = 0.3/0.5/0.7/0.1 ms"
                    parts = line.split('=')
                    if len(parts) >= 2:
                        vals = parts[1].strip().split('/')
                        if len(vals) >= 2:
                            return True, float(vals[1])
            return True, 0.0
        return False, 0.0
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, ValueError):
        return False, 0.0


def check_interface_up(iface: str) -> bool:
    """Check if a network interface is UP."""
    try:
        result = subprocess.run(
            ['ip', 'link', 'show', iface],
            capture_output=True, text=True, timeout=5
        )
        return 'state UP' in result.stdout
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return False


def check_batman_peers() -> int:
    """Count BATMAN-adv mesh peers."""
    try:
        result = subprocess.run(
            ['batctl', 'n'],
            capture_output=True, text=True, timeout=5
        )
        # Count lines that aren't headers
        lines = [l for l in result.stdout.strip().splitlines()
                 if l.strip() and not l.startswith('[') and 'IF' not in l.split()[0:1]]
        return len(lines)
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
        return 0


def check_wg_peers() -> dict[str, float]:
    """Get WireGuard peer latest handshakes. Returns {endpoint: seconds_ago}."""
    try:
        result = subprocess.run(
            ['wg', 'show', 'nexus-mesh', 'latest-handshakes'],
            capture_output=True, text=True, timeout=5
        )
        peers = {}
        for line in result.stdout.strip().splitlines():
            parts = line.split('\t')
            if len(parts) == 2:
                pubkey, timestamp = parts
                ts = int(timestamp)
                if ts > 0:
                    peers[pubkey] = time.time() - ts
        return peers
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return {}


class DegradationManager:
    """Monitors and manages network degradation levels."""

    def __init__(self, node_num: int, check_interval: int = 30):
        self.node_num = node_num
        self.my_info = NODE_MAP[node_num]
        self.check_interval = check_interval
        self._running = False

        # Peer status tracking
        self.peer_status: dict[int, PeerStatus] = {}
        for num, info in NODE_MAP.items():
            if num != node_num:
                self.peer_status[num] = PeerStatus(
                    node_num=num,
                    name=info['name'],
                    level=NetLevel.OFFLINE
                )

        # Overall network level (worst case across all peers)
        self.current_level = NetLevel.OFFLINE
        self.level_history: list[tuple[float, NetLevel]] = []

        # RF daemon reference (set externally if running)
        self._rf_daemon = None

        # Transition log file
        self.log_file = '/opt/nexus/networking/degradation_log.json'

    def set_rf_daemon(self, daemon):
        """Set reference to RF mesh daemon for Level 4 checks."""
        self._rf_daemon = daemon

    def check_peer(self, node_num: int) -> PeerStatus:
        """Check connectivity to a specific peer across all layers."""
        info = NODE_MAP[node_num]
        status = self.peer_status[node_num]
        status.last_check = time.time()

        # Level 1: Ethernet
        eth_ok, eth_latency = ping_check(info['eth'], timeout=2.0)
        status.eth_ok = eth_ok

        # Level 2: WiFi mesh (BATMAN-adv)
        mesh_ok, mesh_latency = ping_check(info['mesh'], timeout=3.0)
        status.mesh_ok = mesh_ok

        # Level 3: WireGuard
        wg_ok, wg_latency = ping_check(info['wg'], timeout=3.0)
        status.wg_ok = wg_ok

        # Level 4: Sub-GHz RF (check via RF daemon peer table)
        rf_ok = False
        if self._rf_daemon:
            for peer in self._rf_daemon.peers.values():
                if peer.node_num == node_num and peer.is_alive:
                    rf_ok = True
                    break
        status.rf_ok = rf_ok

        # Determine best available level
        if eth_ok:
            status.level = NetLevel.ETHERNET
            status.latency_ms = eth_latency
        elif mesh_ok:
            status.level = NetLevel.WIFI_MESH
            status.latency_ms = mesh_latency
        elif wg_ok:
            status.level = NetLevel.WIREGUARD
            status.latency_ms = wg_latency
        elif rf_ok:
            status.level = NetLevel.SUB_GHZ_RF
            status.latency_ms = 0  # RF doesn't have meaningful ping latency
        else:
            status.level = NetLevel.OFFLINE
            status.latency_ms = 0

        return status

    def check_all_peers(self) -> NetLevel:
        """Check all peers and return overall network level."""
        best_level = NetLevel.OFFLINE

        for node_num in self.peer_status:
            status = self.check_peer(node_num)
            if status.level < best_level:  # lower = better
                best_level = status.level

        old_level = self.current_level
        self.current_level = best_level

        # Log level transition
        if old_level != best_level:
            self._on_level_change(old_level, best_level)

        return best_level

    def _on_level_change(self, old_level: NetLevel, new_level: NetLevel):
        """Handle network level transition."""
        old_name = LEVEL_NAMES[old_level]
        new_name = LEVEL_NAMES[new_level]

        if new_level > old_level:
            logger.warning(f"DEGRADED: {old_name} -> {new_name}")
        else:
            logger.info(f"IMPROVED: {old_name} -> {new_name}")

        self.level_history.append((time.time(), new_level))

        # Persist transition to log file
        self._log_transition(old_level, new_level)

        # Try to log on-chain (only if we have Ethernet/mesh connectivity)
        if new_level <= NetLevel.WIREGUARD:
            self._log_onchain(old_level, new_level)

        # Send RF alert if degrading to RF-only or offline
        if new_level >= NetLevel.SUB_GHZ_RF and self._rf_daemon:
            from rf_relay import ALERT_NODE_DOWN
            self._rf_daemon.send_alert(
                ALERT_NODE_DOWN,
                f"N{self.node_num} L{int(new_level)}"
            )

    def _log_transition(self, old_level: NetLevel, new_level: NetLevel):
        """Append transition to local JSON log."""
        entry = {
            'timestamp': time.time(),
            'node': self.node_num,
            'from_level': int(old_level),
            'to_level': int(new_level),
            'from_name': LEVEL_NAMES[old_level],
            'to_name': LEVEL_NAMES[new_level],
        }

        try:
            if os.path.exists(self.log_file):
                with open(self.log_file) as f:
                    log = json.load(f)
            else:
                log = []

            log.append(entry)
            # Keep last 1000 entries
            log = log[-1000:]

            with open(self.log_file, 'w') as f:
                json.dump(log, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to write degradation log: {e}")

    def _log_onchain(self, old_level: NetLevel, new_level: NetLevel):
        """Log level transition on blockchain via ReasoningLedger."""
        try:
            from libnexus import NexusKernel
            kernel = NexusKernel(wallet=NODE_MAP[self.node_num].get(
                'wallet', '0x817B0842B208B76A7665948F8D1A0592F9b1e958'))

            reason = f"net_degrade:{int(old_level)}->{int(new_level)}"
            kernel.log_reasoning(
                agent_id=f"degradation-node{self.node_num}",
                task="network_monitoring",
                reasoning=reason,
                decision=LEVEL_NAMES[new_level],
                confidence=100
            )
            logger.info(f"Logged transition on-chain: {reason}")
        except Exception as e:
            logger.debug(f"On-chain logging failed (expected if degraded): {e}")

    def get_status(self) -> dict:
        """Get current degradation status."""
        return {
            'node': self.node_num,
            'current_level': int(self.current_level),
            'current_level_name': LEVEL_NAMES[self.current_level],
            'peers': {
                num: {
                    'name': s.name,
                    'level': int(s.level),
                    'level_name': LEVEL_NAMES[s.level],
                    'latency_ms': round(s.latency_ms, 1),
                    'eth': s.eth_ok,
                    'mesh': s.mesh_ok,
                    'wg': s.wg_ok,
                    'rf': s.rf_ok,
                    'last_check_ago': int(time.time() - s.last_check) if s.last_check else -1,
                }
                for num, s in self.peer_status.items()
            },
            'transitions': len(self.level_history),
        }

    def get_best_ip(self, target_node: int) -> Optional[str]:
        """Get the best reachable IP for a target node."""
        if target_node not in self.peer_status:
            return None
        status = self.peer_status[target_node]
        info = NODE_MAP[target_node]

        if status.eth_ok:
            return info['eth']
        elif status.mesh_ok:
            return info['mesh']
        elif status.wg_ok:
            return info['wg']
        return None

    def run(self):
        """Main monitoring loop."""
        logger.info(f"Starting degradation manager: node={self.node_num} interval={self.check_interval}s")
        self._running = True

        # Initial check
        level = self.check_all_peers()
        logger.info(f"Initial network level: {LEVEL_NAMES[level]}")

        while self._running:
            time.sleep(self.check_interval)
            try:
                level = self.check_all_peers()

                # Periodic status log
                alive = sum(1 for s in self.peer_status.values()
                           if s.level < NetLevel.OFFLINE)
                logger.info(
                    f"Level: {LEVEL_NAMES[level]} | "
                    f"Peers reachable: {alive}/{len(self.peer_status)} | "
                    + " | ".join(
                        f"{s.name}:{LEVEL_NAMES[s.level].split()[0]}"
                        for s in self.peer_status.values()
                    )
                )
            except Exception as e:
                logger.error(f"Check error: {e}")

    def stop(self):
        """Stop the manager."""
        self._running = False
        logger.info("Degradation manager stopped")


def main():
    parser = argparse.ArgumentParser(description='NEXUS OS Network Degradation Manager')
    parser.add_argument('--node-num', type=int, required=True, choices=[1, 2, 3, 4])
    parser.add_argument('--interval', type=int, default=30, help='Check interval in seconds')
    parser.add_argument('--status', action='store_true', help='Run one check and print status')
    args = parser.parse_args()

    mgr = DegradationManager(node_num=args.node_num, check_interval=args.interval)

    if args.status:
        mgr.check_all_peers()
        status = mgr.get_status()
        print(json.dumps(status, indent=2))
        return

    def shutdown(sig, frame):
        logger.info(f"Received signal {sig}")
        mgr.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    mgr.run()


if __name__ == '__main__':
    main()
