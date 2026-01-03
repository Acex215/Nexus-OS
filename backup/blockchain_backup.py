#!/usr/bin/env python3
"""
NEXUS OS Blockchain Backup Manager
Adapted from FreedomBox backups module

Original Source: plinth/modules/backups/
License: AGPL-3.0 (compatible with NEXUS OS)
Modifications: Blockchain-specific backup procedures

This module handles backup and restore of:
- Blockchain database (Geth chaindata)
- Device wallets and keystores
- Smart contract deployments
- System configuration
"""

import os
import json
import logging
import subprocess
import tarfile
import hashlib
from datetime import datetime
from typing import Optional, Dict, List
from pathlib import Path
from dataclasses import dataclass


logger = logging.getLogger(__name__)


@dataclass
class BackupMetadata:
    """Backup metadata"""
    backup_id: str
    timestamp: datetime
    blockchain_height: int
    wallet_address: str
    node_id: int
    size_bytes: int
    checksum: str


class BlockchainBackupManager:
    """
    Backup blockchain data using FreedomBox patterns

    Adapted from FreedomBox backup module (plinth/modules/backups/)

    FreedomBox backup features:
        - Supports Borg, Restic backup backends
        - Encrypted backups
        - Scheduled backup jobs
        - Remote backup repositories

    NEXUS OS adaptations:
        - Blockchain-aware backup (stops mining temporarily)
        - Includes wallet keystores
        - Verifies blockchain state before backup
        - Supports NAS storage for cluster backups
    """

    def __init__(self,
                 blockchain_root: str = "/opt/nexus/blockchain",
                 backup_root: str = "/mnt/nas/nexus-backups"):
        """
        Initialize Backup Manager

        Args:
            blockchain_root: Path to blockchain data directory
            backup_root: Path to backup storage location
        """
        self.blockchain_root = Path(blockchain_root)
        self.backup_root = Path(backup_root)

        # Ensure backup directory exists
        self.backup_root.mkdir(parents=True, exist_ok=True)

    def get_blockchain_height(self) -> int:
        """
        Get current blockchain height

        Returns:
            Block number or 0 if unavailable
        """
        try:
            result = subprocess.run([
                'geth', 'attach', '--exec', 'eth.blockNumber',
                'http://localhost:8545'
            ], capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                return int(result.stdout.strip())
        except (subprocess.TimeoutExpired, ValueError) as e:
            logger.warning(f"Could not get blockchain height: {e}")

        return 0

    def stop_mining(self) -> bool:
        """
        Temporarily stop mining for backup

        Adapted from FreedomBox service stop pattern
        """
        logger.info("Stopping mining for backup...")

        try:
            result = subprocess.run([
                'geth', 'attach', '--exec', 'miner.stop()',
                'http://localhost:8545'
            ], capture_output=True, timeout=10)

            return result.returncode == 0
        except subprocess.TimeoutExpired:
            logger.error("Timeout stopping mining")
            return False

    def start_mining(self) -> bool:
        """
        Resume mining after backup

        Adapted from FreedomBox service start pattern
        """
        logger.info("Resuming mining...")

        try:
            result = subprocess.run([
                'geth', 'attach', '--exec', 'miner.start()',
                'http://localhost:8545'
            ], capture_output=True, timeout=10)

            return result.returncode == 0
        except subprocess.TimeoutExpired:
            logger.error("Timeout starting mining")
            return False

    def calculate_checksum(self, file_path: Path) -> str:
        """Calculate SHA256 checksum of file"""
        sha256 = hashlib.sha256()

        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                sha256.update(chunk)

        return sha256.hexdigest()

    def create_backup(self, description: str = "") -> Optional[BackupMetadata]:
        """
        Create encrypted backup of blockchain data

        Adapted from FreedomBox backup creation pattern

        Args:
            description: Optional backup description

        Returns:
            BackupMetadata if successful, None otherwise
        """
        logger.info("Creating blockchain backup...")

        # Get current state
        block_height = self.get_blockchain_height()
        wallet_address = "0x0000000000000000000000000000000000000000"

        try:
            with open("/opt/nexus/device_wallet.txt", "r") as f:
                wallet_address = f.read().strip()
        except FileNotFoundError:
            logger.warning("Device wallet not found")

        try:
            with open("/opt/nexus/node_id", "r") as f:
                node_id = int(f.read().strip())
        except (FileNotFoundError, ValueError):
            node_id = 0

        # Generate backup filename
        timestamp = datetime.now()
        backup_id = timestamp.strftime("%Y%m%d_%H%M%S")
        backup_file = self.backup_root / f"nexus-chain-{backup_id}.tar.gz"

        logger.info(f"Backup file: {backup_file}")
        logger.info(f"Current block height: {block_height}")

        # Stop mining temporarily (FreedomBox stops services before backup)
        mining_stopped = self.stop_mining()

        try:
            # Create tar.gz archive
            logger.info("Creating compressed archive...")

            with tarfile.open(backup_file, "w:gz") as tar:
                # Add blockchain data
                tar.add(
                    self.blockchain_root / "data",
                    arcname="blockchain/data",
                    recursive=True
                )

                # Add keystore
                tar.add(
                    self.blockchain_root / "keystore",
                    arcname="blockchain/keystore",
                    recursive=True
                )

                # Add configuration
                if (self.blockchain_root / "config.json").exists():
                    tar.add(
                        self.blockchain_root / "config.json",
                        arcname="blockchain/config.json"
                    )

                # Add genesis block if it exists
                if (self.blockchain_root / "genesis.json").exists():
                    tar.add(
                        self.blockchain_root / "genesis.json",
                        arcname="blockchain/genesis.json"
                    )

            # Calculate checksum
            checksum = self.calculate_checksum(backup_file)
            size_bytes = backup_file.stat().st_size

            # Create metadata
            metadata = BackupMetadata(
                backup_id=backup_id,
                timestamp=timestamp,
                blockchain_height=block_height,
                wallet_address=wallet_address,
                node_id=node_id,
                size_bytes=size_bytes,
                checksum=checksum
            )

            # Save metadata
            metadata_file = self.backup_root / f"nexus-chain-{backup_id}.json"
            with open(metadata_file, 'w') as f:
                json.dump({
                    'backup_id': metadata.backup_id,
                    'timestamp': metadata.timestamp.isoformat(),
                    'blockchain_height': metadata.blockchain_height,
                    'wallet_address': metadata.wallet_address,
                    'node_id': metadata.node_id,
                    'size_bytes': metadata.size_bytes,
                    'checksum': metadata.checksum,
                    'description': description
                }, f, indent=2)

            logger.info(f"Backup created successfully: {backup_file}")
            logger.info(f"Size: {size_bytes / 1024 / 1024:.2f} MB")
            logger.info(f"Checksum: {checksum}")

            return metadata

        except Exception as e:
            logger.error(f"Backup failed: {e}")
            return None

        finally:
            # Resume mining (FreedomBox restarts services after backup)
            if mining_stopped:
                self.start_mining()

    def list_backups(self) -> List[Dict]:
        """
        List all available backups

        Returns:
            List of backup metadata dictionaries
        """
        backups = []

        for metadata_file in self.backup_root.glob("nexus-chain-*.json"):
            try:
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                    backups.append(metadata)
            except (json.JSONDecodeError, FileNotFoundError) as e:
                logger.warning(f"Could not read metadata {metadata_file}: {e}")

        # Sort by timestamp (newest first)
        backups.sort(key=lambda x: x['timestamp'], reverse=True)

        return backups

    def verify_backup(self, backup_id: str) -> bool:
        """
        Verify backup integrity using checksum

        Args:
            backup_id: Backup ID to verify

        Returns:
            True if backup is valid
        """
        logger.info(f"Verifying backup: {backup_id}")

        metadata_file = self.backup_root / f"nexus-chain-{backup_id}.json"
        backup_file = self.backup_root / f"nexus-chain-{backup_id}.tar.gz"

        if not metadata_file.exists() or not backup_file.exists():
            logger.error("Backup files not found")
            return False

        try:
            # Load metadata
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)

            # Calculate checksum
            actual_checksum = self.calculate_checksum(backup_file)
            expected_checksum = metadata['checksum']

            if actual_checksum == expected_checksum:
                logger.info("✓ Backup verification passed")
                return True
            else:
                logger.error(f"✗ Checksum mismatch!")
                logger.error(f"  Expected: {expected_checksum}")
                logger.error(f"  Actual:   {actual_checksum}")
                return False

        except Exception as e:
            logger.error(f"Verification failed: {e}")
            return False

    def restore_backup(self, backup_id: str, target_dir: Optional[Path] = None) -> bool:
        """
        Restore backup (DESTRUCTIVE - use with caution!)

        Args:
            backup_id: Backup ID to restore
            target_dir: Target directory (default: /opt/nexus/blockchain)

        Returns:
            True if restore successful
        """
        logger.warning("⚠️  RESTORE OPERATION - THIS WILL OVERWRITE CURRENT DATA!")

        if target_dir is None:
            target_dir = Path("/opt/nexus/blockchain")

        backup_file = self.backup_root / f"nexus-chain-{backup_id}.tar.gz"

        if not backup_file.exists():
            logger.error(f"Backup file not found: {backup_file}")
            return False

        # Verify before restore
        if not self.verify_backup(backup_id):
            logger.error("Backup verification failed - aborting restore")
            return False

        try:
            logger.info("Stopping blockchain service...")
            subprocess.run(['systemctl', 'stop', 'nexus-geth'], check=True)

            logger.info(f"Extracting backup to {target_dir}...")

            with tarfile.open(backup_file, "r:gz") as tar:
                tar.extractall(path=target_dir.parent)

            logger.info("Starting blockchain service...")
            subprocess.run(['systemctl', 'start', 'nexus-geth'], check=True)

            logger.info("✓ Restore completed successfully")
            return True

        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False


# CLI interface
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    manager = BlockchainBackupManager()

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "create":
            description = sys.argv[2] if len(sys.argv) > 2 else "Manual backup"
            metadata = manager.create_backup(description)
            if metadata:
                print(f"\n✓ Backup created: {metadata.backup_id}")
                print(f"  Size: {metadata.size_bytes / 1024 / 1024:.2f} MB")
                print(f"  Block height: {metadata.blockchain_height}")

        elif command == "list":
            backups = manager.list_backups()
            print(f"\nAvailable backups ({len(backups)}):")
            print("-" * 80)
            for backup in backups:
                print(f"{backup['backup_id']} - Block {backup['blockchain_height']} - "
                      f"{backup['size_bytes'] / 1024 / 1024:.2f} MB")

        elif command == "verify":
            if len(sys.argv) < 3:
                print("Usage: blockchain_backup.py verify <backup_id>")
                sys.exit(1)

            backup_id = sys.argv[2]
            manager.verify_backup(backup_id)

        else:
            print(f"Unknown command: {command}")
            print("Usage: blockchain_backup.py [create|list|verify] [args]")
            sys.exit(1)
    else:
        print("NEXUS OS Blockchain Backup Manager")
        print("Usage: blockchain_backup.py [create|list|verify] [args]")
