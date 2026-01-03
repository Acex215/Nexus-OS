#!/usr/bin/env python3
"""
NEXUS OS VLAN Manager
Adapted from FreedomBox networks module

Original Source: plinth/modules/networks/
License: AGPL-3.0 (compatible with NEXUS OS)
Modifications: Added blockchain-aware VLAN management

This module manages VLANs for security isolation in NEXUS OS:
- VLAN 10: Blockchain network (Geth nodes)
- VLAN 20: AI Compute network (ML workloads)
- VLAN 30: Storage network (NAS, distributed storage)
- VLAN 40: Management network (web interface, SSH)
"""

import json
import logging
import subprocess
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum


logger = logging.getLogger(__name__)


class VLANType(Enum):
    """VLAN types for NEXUS OS security isolation"""
    BLOCKCHAIN = (10, "10.0.10.0/24", "Blockchain Network")
    AI_COMPUTE = (20, "10.0.20.0/24", "AI Compute Network")
    STORAGE = (30, "10.0.30.0/24", "Storage Network")
    MANAGEMENT = (40, "10.0.40.0/24", "Management Network")

    def __init__(self, vlan_id: int, subnet: str, description: str):
        self.vlan_id = vlan_id
        self.subnet = subnet
        self.description = description


@dataclass
class VLANConfig:
    """VLAN configuration data"""
    vlan_id: int
    name: str
    subnet: str
    ip_address: str
    interface: str
    enabled: bool = False


class VLANManager:
    """
    Manage VLANs for NEXUS OS security isolation

    Adapted from FreedomBox networks module (plinth/modules/networks/)

    FreedomBox pattern:
        - Uses NetworkManager or ifupdown for network configuration
        - Provides web UI for network management
        - Supports firewall integration

    NEXUS OS adaptations:
        - Hardcoded VLAN structure for security
        - Blockchain-aware routing rules
        - Integration with iptables for inter-VLAN routing
    """

    def __init__(self, base_interface: str = "eth0", node_id: int = 2):
        """
        Initialize VLAN Manager

        Args:
            base_interface: Physical network interface (default: eth0)
            node_id: Node ID for IP addressing (2-254)
        """
        self.base_interface = base_interface
        self.node_id = node_id
        self.vlans: Dict[int, VLANConfig] = {}

        # Initialize VLAN configurations
        for vlan_type in VLANType:
            self.vlans[vlan_type.vlan_id] = VLANConfig(
                vlan_id=vlan_type.vlan_id,
                name=vlan_type.description,
                subnet=vlan_type.subnet,
                ip_address=self._get_ip_for_vlan(vlan_type.subnet, node_id),
                interface=f"{base_interface}.{vlan_type.vlan_id}"
            )

    @staticmethod
    def _get_ip_for_vlan(subnet: str, node_id: int) -> str:
        """Generate IP address for node in VLAN subnet"""
        base = subnet.split('/')[0].rsplit('.', 1)[0]
        return f"{base}.{node_id}"

    def create_vlan(self, vlan_id: int) -> bool:
        """
        Create VLAN interface

        Adapted from FreedomBox network interface management

        Args:
            vlan_id: VLAN ID (10, 20, 30, or 40)

        Returns:
            True if successful
        """
        if vlan_id not in self.vlans:
            logger.error(f"Invalid VLAN ID: {vlan_id}")
            return False

        vlan = self.vlans[vlan_id]

        logger.info(f"Creating VLAN {vlan_id}: {vlan.name}")

        try:
            # Create VLAN interface using ip command
            # FreedomBox uses NetworkManager, but we use ip for simplicity
            subprocess.run([
                'ip', 'link', 'add',
                'link', self.base_interface,
                'name', vlan.interface,
                'type', 'vlan',
                'id', str(vlan_id)
            ], check=True, capture_output=True)

            # Assign IP address
            subprocess.run([
                'ip', 'addr', 'add',
                f"{vlan.ip_address}/24",
                'dev', vlan.interface
            ], check=True, capture_output=True)

            # Bring interface up
            subprocess.run([
                'ip', 'link', 'set',
                'dev', vlan.interface,
                'up'
            ], check=True, capture_output=True)

            vlan.enabled = True
            logger.info(f"VLAN {vlan_id} created successfully: {vlan.ip_address}")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create VLAN {vlan_id}: {e}")
            logger.error(f"stderr: {e.stderr.decode() if e.stderr else 'N/A'}")
            return False

    def delete_vlan(self, vlan_id: int) -> bool:
        """
        Delete VLAN interface

        Args:
            vlan_id: VLAN ID to delete

        Returns:
            True if successful
        """
        if vlan_id not in self.vlans:
            logger.error(f"Invalid VLAN ID: {vlan_id}")
            return False

        vlan = self.vlans[vlan_id]

        logger.info(f"Deleting VLAN {vlan_id}")

        try:
            # Delete VLAN interface
            subprocess.run([
                'ip', 'link', 'delete',
                vlan.interface
            ], check=True, capture_output=True)

            vlan.enabled = False
            logger.info(f"VLAN {vlan_id} deleted successfully")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to delete VLAN {vlan_id}: {e}")
            return False

    def setup_all_vlans(self) -> bool:
        """
        Create all NEXUS OS VLANs

        Returns:
            True if all VLANs created successfully
        """
        logger.info("Setting up all NEXUS OS VLANs...")

        success = True
        for vlan_id in self.vlans.keys():
            if not self.create_vlan(vlan_id):
                success = False

        if success:
            logger.info("All VLANs created successfully")
        else:
            logger.error("Some VLANs failed to create")

        return success

    def setup_inter_vlan_routing(self) -> bool:
        """
        Configure iptables rules for inter-VLAN routing

        Adapted from FreedomBox firewall module (plinth/modules/firewall/)

        Routing rules:
        - Blockchain (10) → AI Compute (20): ALLOW
        - Blockchain (10) → Storage (30): ALLOW
        - AI Compute (20) → Storage (30): DENY (air-gapped)
        - Management (40) → All: ALLOW
        """
        logger.info("Configuring inter-VLAN routing...")

        # Enable IP forwarding
        try:
            subprocess.run([
                'sysctl', '-w', 'net.ipv4.ip_forward=1'
            ], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to enable IP forwarding: {e}")
            return False

        # Define routing rules
        rules = [
            # Allow blockchain → AI compute
            ['iptables', '-A', 'FORWARD', '-i', 'eth0.10', '-o', 'eth0.20', '-j', 'ACCEPT'],
            ['iptables', '-A', 'FORWARD', '-i', 'eth0.20', '-o', 'eth0.10',
             '-m', 'state', '--state', 'ESTABLISHED,RELATED', '-j', 'ACCEPT'],

            # Allow blockchain → storage
            ['iptables', '-A', 'FORWARD', '-i', 'eth0.10', '-o', 'eth0.30', '-j', 'ACCEPT'],
            ['iptables', '-A', 'FORWARD', '-i', 'eth0.30', '-o', 'eth0.10',
             '-m', 'state', '--state', 'ESTABLISHED,RELATED', '-j', 'ACCEPT'],

            # Allow management → all
            ['iptables', '-A', 'FORWARD', '-i', 'eth0.40', '-o', 'eth0.10', '-j', 'ACCEPT'],
            ['iptables', '-A', 'FORWARD', '-i', 'eth0.40', '-o', 'eth0.20', '-j', 'ACCEPT'],
            ['iptables', '-A', 'FORWARD', '-i', 'eth0.40', '-o', 'eth0.30', '-j', 'ACCEPT'],

            # Block AI compute ↔ storage (air-gapped)
            ['iptables', '-A', 'FORWARD', '-i', 'eth0.20', '-o', 'eth0.30', '-j', 'DROP'],
            ['iptables', '-A', 'FORWARD', '-i', 'eth0.30', '-o', 'eth0.20', '-j', 'DROP'],
        ]

        # Apply rules
        for rule in rules:
            try:
                subprocess.run(rule, check=True, capture_output=True)
                logger.debug(f"Applied rule: {' '.join(rule)}")
            except subprocess.CalledProcessError as e:
                logger.warning(f"Failed to apply rule {' '.join(rule)}: {e}")

        logger.info("Inter-VLAN routing configured")
        return True

    def get_vlan_status(self, vlan_id: int) -> Optional[Dict]:
        """
        Get status of a VLAN

        Args:
            vlan_id: VLAN ID

        Returns:
            Dictionary with VLAN status or None
        """
        if vlan_id not in self.vlans:
            return None

        vlan = self.vlans[vlan_id]

        # Check if interface exists
        try:
            result = subprocess.run([
                'ip', 'link', 'show', vlan.interface
            ], capture_output=True, text=True)

            exists = result.returncode == 0
            is_up = 'UP' in result.stdout if exists else False

        except subprocess.CalledProcessError:
            exists = False
            is_up = False

        return {
            'vlan_id': vlan_id,
            'name': vlan.name,
            'interface': vlan.interface,
            'ip_address': vlan.ip_address,
            'subnet': vlan.subnet,
            'exists': exists,
            'is_up': is_up,
            'enabled': vlan.enabled
        }

    def get_all_vlan_status(self) -> List[Dict]:
        """Get status of all VLANs"""
        return [self.get_vlan_status(vid) for vid in self.vlans.keys()]

    def diagnose(self) -> List[Dict]:
        """
        Run diagnostics on VLAN configuration

        Returns diagnostic results in FreedomBox format
        """
        results = []

        # Check each VLAN
        for vlan_id in self.vlans.keys():
            status = self.get_vlan_status(vlan_id)

            if status['exists'] and status['is_up']:
                results.append({
                    'component': f'vlan_{vlan_id}',
                    'test': 'vlan_status',
                    'result': 'passed',
                    'message': f"VLAN {vlan_id} ({status['name']}) is UP at {status['ip_address']}"
                })
            else:
                results.append({
                    'component': f'vlan_{vlan_id}',
                    'test': 'vlan_status',
                    'result': 'failed',
                    'message': f"VLAN {vlan_id} ({status['name']}) is DOWN or missing"
                })

        # Check IP forwarding
        try:
            result = subprocess.run([
                'sysctl', 'net.ipv4.ip_forward'
            ], capture_output=True, text=True, check=True)

            if '= 1' in result.stdout:
                results.append({
                    'component': 'ip_forwarding',
                    'test': 'kernel_parameter',
                    'result': 'passed',
                    'message': 'IP forwarding is enabled'
                })
            else:
                results.append({
                    'component': 'ip_forwarding',
                    'test': 'kernel_parameter',
                    'result': 'failed',
                    'message': 'IP forwarding is disabled'
                })
        except subprocess.CalledProcessError:
            results.append({
                'component': 'ip_forwarding',
                'test': 'kernel_parameter',
                'result': 'failed',
                'message': 'Could not check IP forwarding status'
            })

        return results


# Example usage and CLI
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Read node ID from /opt/nexus/node_id if it exists
    try:
        with open('/opt/nexus/node_id', 'r') as f:
            node_id = int(f.read().strip())
    except (FileNotFoundError, ValueError):
        node_id = 2  # Default

    manager = VLANManager(base_interface="eth0", node_id=node_id)

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "setup":
            print("Setting up all VLANs...")
            success = manager.setup_all_vlans()
            if success:
                manager.setup_inter_vlan_routing()
            sys.exit(0 if success else 1)

        elif command == "status":
            print("\nNEXUS OS VLAN Status:")
            print("-" * 80)
            for status in manager.get_all_vlan_status():
                state = "✓ UP" if status['is_up'] else "✗ DOWN"
                print(f"VLAN {status['vlan_id']:2d} ({status['name']:20s}): "
                      f"{state:8s} {status['ip_address']}")

        elif command == "diagnose":
            print("\nNEXUS OS VLAN Diagnostics:")
            print("-" * 80)
            for result in manager.diagnose():
                symbol = "✓" if result['result'] == 'passed' else "✗"
                print(f"{symbol} {result['component']:15s}: {result['message']}")

        else:
            print(f"Unknown command: {command}")
            print("Usage: vlan_manager.py [setup|status|diagnose]")
            sys.exit(1)
    else:
        print("NEXUS OS VLAN Manager")
        print("Usage: vlan_manager.py [setup|status|diagnose]")
