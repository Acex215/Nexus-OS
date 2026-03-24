#!/usr/bin/env python3
# Phase 2 health check placeholder
"""NEXUS OS Blockchain Logger — log agent decisions to ReasoningLedger.

Every agent decision produces a SHA256 reasoning hash. This module logs a
short summary + the hash on-chain to ReasoningLedger so the blockchain
serves as an immutable audit trail. Full decision text stays off-chain in
per-agent JSONL files; the on-chain hash proves integrity.

Uses the deployer wallet unlocked on Geth (same as libnexus.kernel).
Web3 calls are synchronous, so we run them in a thread executor to avoid
blocking the async event loop.
"""
import asyncio
import json
import logging
import threading
from functools import partial
from typing import Dict, List, Optional

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

logger = logging.getLogger("blockchain_logger")

# ── Contract + RPC configuration ──────────────────────────────────────

RPC_URL = "http://10.0.20.3:8545"
CONTRACT_PATH = "/opt/nexus/contracts/deployed/ReasoningLedger.json"
DEPLOYER = "0x817B0842B208B76A7665948F8D1A0592F9b1e958"


class BlockchainLogger:
    """Log agent decisions to ReasoningLedger on-chain."""

    def __init__(self):
        # Web3 connection
        self.w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 10}))
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        self.wallet = Web3.to_checksum_address(DEPLOYER)

        # Load contract ABI
        with open(CONTRACT_PATH) as f:
            data = json.load(f)
        self.contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(data["address"]),
            abi=data["abi"],
        )
        self.contract_address = data["address"]

        # Nonce lock — prevents concurrent tx nonce conflicts
        self._nonce_lock = threading.Lock()

        # Retry queue for failed submissions
        self.pending_logs: List[Dict] = []

        logger.info(
            "BlockchainLogger ready: rpc=%s contract=%s wallet=%s",
            RPC_URL, self.contract_address, self.wallet,
        )

    # ── Connection health ─────────────────────────────────────────────

    def is_connected(self) -> bool:
        try:
            return self.w3.is_connected()
        except Exception:
            return False

    # ── Core: log decision on-chain ───────────────────────────────────

    def _get_time_source(self) -> tuple:
        """Get authoritative timestamp and source name from TimeAuthority."""
        try:
            import sys
            if '/opt/nexus/modules' not in sys.path:
                sys.path.insert(0, '/opt/nexus/modules')
            from time_authority import get_time_authority
            ta = get_time_authority()
            auth_time = ta.get_authoritative_time()
            return auth_time.isoformat(), ta.last_source
        except Exception:
            from datetime import datetime, timezone
            return datetime.now(timezone.utc).isoformat(), "local"

    def _log_decision_sync(
        self,
        agent_id: str,
        task: str,
        reasoning_hash: str,
        ect_cost: int,
    ) -> Optional[str]:
        """Synchronous blockchain write — runs in thread executor.

        Stores a short decision string and the reasoning hash on-chain.
        The contract computes its own keccak256 entryHash from the two
        strings; we pass the SHA256 reasoning_hash as the "reasoning"
        field so it is permanently recorded.

        Includes authoritative timestamp source in the reasoning field
        for forensic verification.
        """
        # Get authoritative time and source
        auth_ts, ts_source = self._get_time_source()

        # Build decision string: "agent_id: task_summary (ECT cost)"
        decision_str = f"{agent_id}: {task[:80]} (ect={ect_cost})"
        reasoning_str = f"{reasoning_hash}|timestamp_source:{ts_source}|ts:{auth_ts}"

        with self._nonce_lock:
            try:
                tx_hash = self.contract.functions.logReasoning(
                    decision_str,
                    reasoning_str,
                ).transact({
                    "from": self.wallet,
                    "gas": 300000,
                })

                receipt = self.w3.eth.wait_for_transaction_receipt(
                    tx_hash, timeout=30,
                )

                if receipt["status"] == 1:
                    hex_hash = tx_hash.hex()
                    logger.info(
                        "On-chain: %s entry=%d tx=%s… gas=%d",
                        agent_id,
                        self.get_entry_count() - 1,
                        hex_hash[:16],
                        receipt["gasUsed"],
                    )
                    return hex_hash
                else:
                    logger.error("Tx reverted: %s", tx_hash.hex())
                    return None

            except Exception as exc:
                logger.error("Blockchain write failed: %s", exc)
                return None

    async def log_decision(
        self,
        agent_id: str,
        task: str,
        reasoning_hash: str,
        ect_cost: int,
    ) -> Optional[str]:
        """Async wrapper — submits blockchain tx in a thread.

        Returns tx hash hex string on success, None on failure.
        Failed entries are queued for retry.
        """
        if not self.is_connected():
            logger.warning("Blockchain unavailable, queueing %s", agent_id)
            self.pending_logs.append({
                "agent_id": agent_id,
                "task": task,
                "reasoning_hash": reasoning_hash,
                "ect_cost": ect_cost,
            })
            return None

        loop = asyncio.get_running_loop()
        tx_hash = await loop.run_in_executor(
            None,
            partial(
                self._log_decision_sync,
                agent_id, task, reasoning_hash, ect_cost,
            ),
        )

        if tx_hash is None:
            self.pending_logs.append({
                "agent_id": agent_id,
                "task": task,
                "reasoning_hash": reasoning_hash,
                "ect_cost": ect_cost,
            })

        return tx_hash

    # ── Retry pending entries ─────────────────────────────────────────

    async def process_pending(self) -> int:
        """Retry queued entries. Returns number still pending."""
        if not self.pending_logs:
            return 0

        batch = list(self.pending_logs)
        self.pending_logs.clear()
        logger.info("Retrying %d pending blockchain logs…", len(batch))

        for entry in batch:
            tx = await self.log_decision(**entry)
            if tx is None:
                # Already re-queued by log_decision
                pass

        remaining = len(self.pending_logs)
        if remaining:
            logger.warning("%d entries still pending after retry", remaining)
        return remaining

    # ── Read queries (synchronous, fast) ──────────────────────────────

    def get_entry_count(self) -> int:
        try:
            return self.contract.functions.getEntryCount().call()
        except Exception:
            return -1

    def get_entry(self, entry_id: int) -> Optional[Dict]:
        try:
            e = self.contract.functions.getEntry(entry_id).call()
            return {
                "agent": e[0],
                "timestamp": e[1],
                "decision": e[2],
                "reasoning": e[3],
                "entry_hash": e[4].hex(),
            }
        except Exception:
            return None

    def get_latest_entry(self) -> Optional[Dict]:
        count = self.get_entry_count()
        if count <= 0:
            return None
        return self.get_entry(count - 1)

    def verify_hash(self, entry_id: int, expected_hash: str) -> bool:
        """Check that the reasoning field on-chain matches expected hash."""
        entry = self.get_entry(entry_id)
        if not entry:
            return False
        return entry["reasoning"] == expected_hash


# ── Singleton ─────────────────────────────────────────────────────────

_instance: Optional[BlockchainLogger] = None


def get_blockchain_logger() -> BlockchainLogger:
    global _instance
    if _instance is None:
        _instance = BlockchainLogger()
    return _instance


def reset_blockchain_logger():
    global _instance
    _instance = None
