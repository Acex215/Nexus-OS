"""
NEXUS OS Service Framework — adapted from FreedomBox Plinth app.py

Replaces Django ORM with SQLite, Django views with FastAPI, and
Django signals with asyncio events. Privileged operations use
subprocess+sudo pattern from FreedomBox.

Each NexusService represents a system service (e.g. nfs-server, geth,
ipfs) with configuration stored in SQLite and hashes anchored on-chain
via the ServiceRegistry contract.
"""

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from web3 import Web3

logger = logging.getLogger(__name__)

# Paths
DB_PATH = '/opt/nexus/core/services.db'
ACTIONS_DIR = '/opt/nexus/core/actions'

# Lazy kernel singleton
_kernel = None


def get_kernel():
    """Get or create NexusKernel singleton."""
    global _kernel
    if _kernel is None:
        import sys
        if '/opt/nexus' not in sys.path:
            sys.path.insert(0, '/opt/nexus')
        from libnexus import NexusKernel
        wallet = os.environ.get(
            'NEXUS_WALLET',
            '0x817B0842B208B76A7665948F8D1A0592F9b1e958'
        )
        _kernel = NexusKernel(wallet=wallet)
    return _kernel


def _init_db():
    """Initialize SQLite database for service configs."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS services (
        name TEXT PRIMARY KEY,
        config TEXT NOT NULL DEFAULT '{}',
        config_hash TEXT NOT NULL DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )''')
    conn.commit()
    return conn


def config_to_hash(config_dict: dict) -> bytes:
    """Compute keccak256 hash of config dict (deterministic JSON)."""
    canonical = json.dumps(config_dict, sort_keys=True, separators=(',', ':'))
    return Web3.keccak(text=canonical)


# === Privileged Actions (FreedomBox sudo pattern) ===

def run_privileged(action_name: str, *args: str) -> subprocess.CompletedProcess:
    """
    Run a privileged action script via sudo.

    Adapted from FreedomBox's action execution pattern. Each action
    is a standalone script in ACTIONS_DIR that performs a single
    privileged operation (start/stop service, modify config files, etc).

    Args:
        action_name: Name of the script in actions/
        *args: Arguments to pass to the script

    Returns:
        CompletedProcess with stdout/stderr
    """
    script = os.path.join(ACTIONS_DIR, action_name)
    if not os.path.isfile(script):
        raise FileNotFoundError(f"Action script not found: {script}")

    cmd = ['sudo', script] + list(args)
    logger.info("Running privileged action: %s", ' '.join(cmd))

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=120
    )

    if result.returncode != 0:
        logger.error("Action %s failed: %s", action_name, result.stderr)

    return result


# === Service Registry (global) ===

_all_services: dict[str, 'NexusService'] = {}

# Asyncio events for service lifecycle
service_enabled = asyncio.Event()
service_disabled = asyncio.Event()
service_configured = asyncio.Event()


class NexusService:
    """
    Base class for all NEXUS OS services.

    Adapted from FreedomBox App class. Each service can be enabled,
    disabled, and configured. Configuration is stored locally in SQLite
    and its hash is anchored on-chain via ServiceRegistry.

    Subclass this for specific services (NFS, Geth, IPFS, etc).
    """

    service_id: str = ''
    description: str = ''
    systemd_unit: str = ''  # e.g. 'nfs-server.service'
    can_be_disabled: bool = True

    def __init__(self):
        if not self.service_id:
            raise ValueError("service_id must be set")
        _all_services[self.service_id] = self

    @classmethod
    def get(cls, service_id: str) -> 'NexusService':
        """Look up a registered service by ID."""
        if service_id not in _all_services:
            raise KeyError(f"Service '{service_id}' not registered")
        return _all_services[service_id]

    @classmethod
    def list_all(cls) -> list[str]:
        """List all registered service IDs."""
        return list(_all_services.keys())

    def enable(self) -> dict:
        """
        Enable this service:
        1. Start systemd unit (if configured) via privileged action
        2. Register on-chain via ServiceRegistry
        3. Update local DB
        """
        # Start the systemd service if configured
        if self.systemd_unit:
            run_privileged('service-ctl', 'enable', self.systemd_unit)

        # Get current config hash
        config = self._load_config()
        config_hash = config_to_hash(config)

        # Register on-chain
        kernel = get_kernel()
        receipt = kernel.register_service(self.service_id, config_hash)

        # Update local DB
        conn = _init_db()
        conn.execute(
            'INSERT OR REPLACE INTO services (name, config, config_hash, enabled, updated_at) '
            'VALUES (?, ?, ?, 1, datetime("now"))',
            (self.service_id, json.dumps(config), '0x' + config_hash.hex())
        )
        conn.commit()
        conn.close()

        logger.info("Service %s enabled (tx: %s)", self.service_id, receipt['tx_hash'])
        service_enabled.set()
        service_enabled.clear()

        return receipt

    def disable(self) -> dict:
        """
        Disable this service:
        1. Stop systemd unit via privileged action
        2. Deregister on-chain
        3. Update local DB
        """
        if not self.can_be_disabled:
            raise RuntimeError(f"Service {self.service_id} cannot be disabled")

        if self.systemd_unit:
            run_privileged('service-ctl', 'disable', self.systemd_unit)

        kernel = get_kernel()
        receipt = kernel.deregister_service(self.service_id)

        conn = _init_db()
        conn.execute(
            'UPDATE services SET enabled = 0, updated_at = datetime("now") WHERE name = ?',
            (self.service_id,)
        )
        conn.commit()
        conn.close()

        logger.info("Service %s disabled (tx: %s)", self.service_id, receipt['tx_hash'])
        service_disabled.set()
        service_disabled.clear()

        return receipt

    def configure(self, config_dict: dict) -> dict:
        """
        Update service configuration:
        1. Hash config via keccak256
        2. Store hash on-chain via ServiceRegistry.register()
        3. Store full config in SQLite
        """
        config_hash = config_to_hash(config_dict)

        kernel = get_kernel()
        receipt = kernel.register_service(self.service_id, config_hash)

        conn = _init_db()
        conn.execute(
            'INSERT OR REPLACE INTO services (name, config, config_hash, enabled, updated_at) '
            'VALUES (?, ?, ?, COALESCE((SELECT enabled FROM services WHERE name = ?), 0), datetime("now"))',
            (self.service_id, json.dumps(config_dict), '0x' + config_hash.hex(), self.service_id)
        )
        conn.commit()
        conn.close()

        logger.info("Service %s configured (tx: %s)", self.service_id, receipt['tx_hash'])
        service_configured.set()
        service_configured.clear()

        return receipt

    def status(self) -> dict:
        """
        Get service status from on-chain state + local DB.

        Returns:
            dict with active, config_hash, timestamp (on-chain)
            plus config, enabled (local)
        """
        kernel = get_kernel()
        on_chain = kernel.get_service(self.service_id)

        local = self._load_local_state()

        return {
            'service_id': self.service_id,
            'on_chain': on_chain,
            'local': local,
            'systemd_unit': self.systemd_unit
        }

    def _load_config(self) -> dict:
        """Load config from local DB."""
        conn = _init_db()
        row = conn.execute(
            'SELECT config FROM services WHERE name = ?', (self.service_id,)
        ).fetchone()
        conn.close()
        return json.loads(row[0]) if row else {}

    def _load_local_state(self) -> dict:
        """Load full local state from DB."""
        conn = _init_db()
        row = conn.execute(
            'SELECT config, config_hash, enabled, updated_at FROM services WHERE name = ?',
            (self.service_id,)
        ).fetchone()
        conn.close()
        if not row:
            return {'config': {}, 'config_hash': '', 'enabled': False, 'updated_at': None}
        return {
            'config': json.loads(row[0]),
            'config_hash': row[1],
            'enabled': bool(row[2]),
            'updated_at': row[3]
        }


# === FastAPI App (replaces Django views) ===

def create_api():
    """Create FastAPI app for service management."""
    from fastapi import FastAPI, HTTPException

    app = FastAPI(title="NEXUS OS Service Manager", version="0.1.0")

    @app.get("/services")
    async def list_services():
        return {"services": NexusService.list_all()}

    @app.get("/services/{service_id}")
    async def get_service_status(service_id: str):
        try:
            svc = NexusService.get(service_id)
        except KeyError:
            raise HTTPException(404, f"Service '{service_id}' not found")
        return svc.status()

    @app.post("/services/{service_id}/enable")
    async def enable_service(service_id: str):
        try:
            svc = NexusService.get(service_id)
        except KeyError:
            raise HTTPException(404, f"Service '{service_id}' not found")
        return svc.enable()

    @app.post("/services/{service_id}/disable")
    async def disable_service(service_id: str):
        try:
            svc = NexusService.get(service_id)
        except KeyError:
            raise HTTPException(404, f"Service '{service_id}' not found")
        return svc.disable()

    @app.post("/services/{service_id}/configure")
    async def configure_service(service_id: str, config: dict):
        try:
            svc = NexusService.get(service_id)
        except KeyError:
            raise HTTPException(404, f"Service '{service_id}' not found")
        return svc.configure(config)

    return app
