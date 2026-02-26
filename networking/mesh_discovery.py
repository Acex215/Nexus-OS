#!/usr/bin/env python3
"""
NEXUS OS Mesh Discovery Service

On boot:
  - Reads this node's WireGuard public key and mesh IP
  - Registers on MeshRegistry.sol
  - Polls for new PeerRegistered events
  - Auto-adds new peers to WireGuard config

Run as: python3 mesh_discovery.py --node-num <1-4> [--register] [--watch]
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time

sys.path.insert(0, '/opt/nexus')
from libnexus import NexusKernel

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [mesh-discovery] %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)

# Node configuration
NODE_MAP = {
    1: {'name': 'nexus-master', 'eth_ip': '192.168.8.228', 'mesh_ip': '10.0.0.1', 'wg_ip': '10.1.0.1'},
    2: {'name': 'nexus-ai',     'eth_ip': '192.168.8.128', 'mesh_ip': '10.0.0.2', 'wg_ip': '10.1.0.2'},
    3: {'name': 'nexus-storage','eth_ip': '192.168.8.224', 'mesh_ip': '10.0.0.3', 'wg_ip': '10.1.0.3'},
    4: {'name': 'nexus-admin',  'eth_ip': '192.168.8.153', 'mesh_ip': '10.0.0.4', 'wg_ip': '10.1.0.4'},
}

WG_INTERFACE = 'nexus-mesh'
WG_DIR = '/opt/nexus/networking'
WG_CONF = '/etc/wireguard/nexus-mesh.conf'
WALLET = os.environ.get('NEXUS_WALLET', '0x817B0842B208B76A7665948F8D1A0592F9b1e958')


def get_wg_public_key():
    """Read this node's WireGuard public key."""
    key_file = os.path.join(WG_DIR, 'wg_public.key')
    if not os.path.exists(key_file):
        raise FileNotFoundError(f"WireGuard public key not found: {key_file}")
    with open(key_file) as f:
        return f.read().strip()


def get_enode_url():
    """Get this node's Geth enode URL (if running)."""
    try:
        import requests
        resp = requests.post(
            'http://localhost:8545',
            json={'jsonrpc': '2.0', 'method': 'admin_nodeInfo', 'params': [], 'id': 1},
            timeout=5
        )
        data = resp.json()
        return data.get('result', {}).get('enode', '')
    except Exception:
        return ''


def register_peer(kernel, node_num):
    """Register this node on the MeshRegistry contract."""
    node = NODE_MAP[node_num]
    wg_pub = get_wg_public_key()
    enode = get_enode_url()

    logger.info(f"Registering peer: node={node_num} mesh_ip={node['wg_ip']} wg_pub={wg_pub[:20]}...")

    result = kernel.register_peer(
        enode_url=enode,
        wg_public_key=wg_pub,
        mesh_ip=node['wg_ip']
    )

    logger.info(f"Registered on-chain: tx={result['tx_hash'][:16]}... block={result['block']}")
    return result


def add_wg_peer(public_key, allowed_ip, endpoint):
    """Add a WireGuard peer dynamically using wg set."""
    try:
        subprocess.run(
            ['sudo', 'wg', 'set', WG_INTERFACE,
             'peer', public_key,
             'allowed-ips', f'{allowed_ip}/32',
             'endpoint', f'{endpoint}:51820',
             'persistent-keepalive', '25'],
            check=True, capture_output=True, text=True
        )
        # Add route for the peer's IP
        subprocess.run(
            ['sudo', 'ip', 'route', 'add', f'{allowed_ip}/32', 'dev', WG_INTERFACE],
            capture_output=True, text=True
        )
        logger.info(f"Added WireGuard peer: {public_key[:20]}... -> {allowed_ip} via {endpoint}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to add peer: {e.stderr}")
        return False


def get_known_peers():
    """Get currently configured WireGuard peers."""
    try:
        result = subprocess.run(
            ['wg', 'show', WG_INTERFACE, 'peers'],
            capture_output=True, text=True, check=True
        )
        return set(result.stdout.strip().split('\n')) if result.stdout.strip() else set()
    except subprocess.CalledProcessError:
        return set()


def watch_for_peers(kernel, node_num):
    """Poll MeshRegistry for new peers and auto-configure WireGuard."""
    logger.info("Watching for new mesh peers...")
    known_keys = get_known_peers()
    my_wg_pub = get_wg_public_key()

    while True:
        try:
            peers = kernel.get_all_peers()
            for peer in peers:
                pub_key = peer['wg_public_key']
                if not pub_key or pub_key == my_wg_pub:
                    continue
                if pub_key in known_keys:
                    continue
                if not peer['active']:
                    continue

                # New peer discovered
                mesh_ip = peer['mesh_ip']
                # Determine endpoint: try Ethernet IPs first, fall back to mesh IP
                endpoint = mesh_ip
                for num, info in NODE_MAP.items():
                    if info['wg_ip'] == mesh_ip:
                        endpoint = info['eth_ip']
                        break

                logger.info(f"New peer discovered: {pub_key[:20]}... at {mesh_ip}")
                if add_wg_peer(pub_key, mesh_ip, endpoint):
                    known_keys.add(pub_key)

        except Exception as e:
            logger.error(f"Error polling peers: {e}")

        time.sleep(30)


def main():
    parser = argparse.ArgumentParser(description='NEXUS OS Mesh Discovery')
    parser.add_argument('--node-num', type=int, required=True, choices=[1, 2, 3, 4])
    parser.add_argument('--register', action='store_true', help='Register this node on-chain')
    parser.add_argument('--watch', action='store_true', help='Watch for new peers continuously')
    parser.add_argument('--list', action='store_true', help='List all registered peers')
    args = parser.parse_args()

    kernel = NexusKernel(wallet=WALLET)
    logger.info(f"Connected to blockchain, block: {kernel.get_block_number()}")

    if args.register:
        register_peer(kernel, args.node_num)

    if args.list:
        peers = kernel.get_all_peers()
        print(f"\nRegistered mesh peers ({len(peers)}):")
        for p in peers:
            status = "active" if p['active'] else "inactive"
            print(f"  {p['wallet'][:10]}... | {p['mesh_ip']:12s} | wg={p['wg_public_key'][:20]}... | {status}")

    if args.watch:
        watch_for_peers(kernel, args.node_num)


if __name__ == '__main__':
    main()
