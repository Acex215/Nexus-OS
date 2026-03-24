"""
NEXUS OS — Offline Operation Queue

When the Gateway or blockchain is unreachable, operations are queued
locally in an append-only JSONL file and drained when connectivity
returns.

Integration points:
  - token_hooks.py: when blockchain is unreachable, enqueue ECT/RST
    operations instead of silently skipping them
  - node_agent.py: when Gateway WS disconnects, heartbeats and command
    responses queue locally; on reconnect, drain immediately

Storage: /opt/nexus/logs/offline_queue.jsonl (append-only JSONL)
Each line: {id, timestamp, operation, status, retry_count, error, tx_hash}
"""

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

import requests

log = logging.getLogger("nexus.offline_queue")

QUEUE_PATH = Path("/opt/nexus/logs/offline_queue.jsonl")
MAX_RETRIES = 5
DEFAULT_GATEWAY_URL = "http://10.0.20.3:3000"
DEFAULT_RPC_URL = "http://10.0.20.3:8545"


class OfflineQueue:
    """
    Append-only JSONL queue for operations that failed due to
    Gateway or blockchain unavailability.
    """

    def __init__(self, queue_path=None):
        self._path = Path(queue_path) if queue_path else QUEUE_PATH
        self._lock = Lock()

    # ── Enqueue ─────────────────────────────────────────────────────────────

    def enqueue(self, operation):
        """
        Append an operation to the offline queue.

        Args:
            operation: dict describing the operation. Expected keys vary by
                       type but typically include:
                       - op_type: str ("ect_spend", "rst_update", "heartbeat",
                                       "command_response", "block_write")
                       - requester_wallet: str
                       - Any operation-specific fields

        Returns:
            str: the generated queue entry ID
        """
        now = time.time()
        entry_id = "oq-" + hashlib.sha256(
            f"{now}:{json.dumps(operation, sort_keys=True)}".encode()
        ).hexdigest()[:12]

        entry = {
            "id": entry_id,
            "timestamp": now,
            "datetime": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "status": "pending",
            "retry_count": 0,
            "error": None,
            "tx_hash": None,
        }

        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(self._path, "a") as f:
                    f.write(json.dumps(entry) + "\n")
            except OSError as e:
                log.error("Failed to enqueue operation: %s", e)
                return ""

        log.info("[OFFLINE] Enqueued %s: %s", entry_id, operation.get("op_type", "unknown"))
        return entry_id

    # ── Drain ───────────────────────────────────────────────────────────────

    def drain(self, gateway_url=None, token_client=None):
        """
        Process all pending operations in the queue.

        For each pending entry:
          - Try to execute via Gateway/blockchain
          - Success: mark status="completed" with tx_hash
          - Failure: mark status="retry", increment retry_count
          - retry_count > MAX_RETRIES: mark status="failed_permanent"

        Args:
            gateway_url: Gateway HTTP URL for heartbeat/command operations
            token_client: TokenClient instance for ECT/RST operations.
                         If None, attempts lazy initialization.

        Returns:
            dict: {processed, completed, retried, failed_permanent}
        """
        entries = self._read_all()
        pending = [e for e in entries if e.get("status") == "pending"
                   or e.get("status") == "retry"]

        if not pending:
            return {"processed": 0, "completed": 0, "retried": 0, "failed_permanent": 0}

        log.info("[OFFLINE] Draining queue: %d pending operations", len(pending))

        completed = 0
        retried = 0
        failed_permanent = 0

        updates = {}  # id → updated entry

        for entry in pending:
            entry_id = entry["id"]
            operation = entry.get("operation", {})
            op_type = operation.get("op_type", "unknown")

            try:
                tx_hash = self._execute_operation(operation, gateway_url, token_client)
                entry["status"] = "completed"
                entry["tx_hash"] = tx_hash
                entry["error"] = None
                completed += 1
                log.info("[OFFLINE] Completed %s (%s)", entry_id, op_type)

            except Exception as e:
                entry["retry_count"] = entry.get("retry_count", 0) + 1
                entry["error"] = str(e)

                if entry["retry_count"] > MAX_RETRIES:
                    entry["status"] = "failed_permanent"
                    failed_permanent += 1
                    log.warning("[OFFLINE] Permanently failed %s after %d retries: %s",
                                entry_id, MAX_RETRIES, e)
                else:
                    entry["status"] = "retry"
                    retried += 1
                    log.info("[OFFLINE] Retry %d/%d for %s: %s",
                             entry["retry_count"], MAX_RETRIES, entry_id, e)

            updates[entry_id] = entry

        # Rewrite the queue file with updated statuses
        if updates:
            self._apply_updates(entries, updates)

        result = {
            "processed": len(pending),
            "completed": completed,
            "retried": retried,
            "failed_permanent": failed_permanent,
        }
        log.info("[OFFLINE] Drain result: %s", result)
        return result

    def _execute_operation(self, operation, gateway_url, token_client):
        """
        Execute a single queued operation. Returns tx_hash or None.
        Raises on failure.
        """
        op_type = operation.get("op_type", "")

        if op_type == "ect_spend":
            return self._exec_ect_spend(operation, token_client)
        elif op_type == "rst_update":
            return self._exec_rst_update(operation, token_client)
        elif op_type == "heartbeat":
            return self._exec_heartbeat(operation, gateway_url)
        elif op_type == "command_response":
            return self._exec_command_response(operation, gateway_url)
        elif op_type == "block_write":
            return self._exec_block_write(operation)
        else:
            raise ValueError(f"Unknown operation type: {op_type}")

    def _exec_ect_spend(self, operation, token_client):
        """Execute a deferred ECT spend."""
        if token_client is None:
            token_client = self._get_token_client()
        wallet = operation["requester_wallet"]
        cost = operation["cost"]
        task_id = bytes.fromhex(operation["task_id"]) if "task_id" in operation else b'\x00' * 32
        token_client.spend_ect(wallet, cost, task_id)
        return None

    def _exec_rst_update(self, operation, token_client):
        """Execute a deferred RST earn/slash."""
        if token_client is None:
            token_client = self._get_token_client()
        wallet = operation["node_wallet"]
        amount = operation["amount"]
        reason = operation.get("reason", "offline queue replay")
        if operation.get("action") == "earn":
            token_client.earn_rst(wallet, amount, reason)
        elif operation.get("action") == "slash":
            token_client.slash_rst(wallet, amount, reason)
        return None

    def _exec_heartbeat(self, operation, gateway_url):
        """Send a deferred heartbeat to the Gateway."""
        url = gateway_url or DEFAULT_GATEWAY_URL
        r = requests.post(
            f"{url}/api/heartbeat",
            json=operation.get("payload", {}),
            timeout=10,
        )
        r.raise_for_status()
        return None

    def _exec_command_response(self, operation, gateway_url):
        """Send a deferred command response to the Gateway."""
        url = gateway_url or DEFAULT_GATEWAY_URL
        r = requests.post(
            f"{url}/api/command-response",
            json=operation.get("payload", {}),
            timeout=10,
        )
        r.raise_for_status()
        return None

    def _exec_block_write(self, operation):
        """Execute a deferred on-chain write via ReasoningLedger."""
        import sys
        if '/opt/nexus' not in sys.path:
            sys.path.insert(0, '/opt/nexus')
        from libnexus import NexusKernel
        kernel = NexusKernel(
            rpc_url=DEFAULT_RPC_URL,
            wallet="0x817B0842B208B76A7665948F8D1A0592F9b1e958",
        )
        decision = operation.get("decision", "offline_replay")
        reasoning = operation.get("reasoning", "")
        result = kernel.log_reasoning(decision, reasoning)
        return result.get("tx_hash")

    def _get_token_client(self):
        """Lazy-load TokenClient."""
        import sys
        if '/opt/nexus' not in sys.path:
            sys.path.insert(0, '/opt/nexus')
        from libnexus.token_client import TokenClient
        return TokenClient(wallet="0x817B0842B208B76A7665948F8D1A0592F9b1e958")

    # ── Status queries ──────────────────────────────────────────────────────

    def get_pending_count(self):
        """Return the number of pending/retry operations in the queue."""
        entries = self._read_all()
        return sum(1 for e in entries
                   if e.get("status") in ("pending", "retry"))

    def get_queue_status(self):
        """
        Full queue status.

        Returns:
            dict: {pending, completed, failed, oldest_pending_timestamp}
        """
        entries = self._read_all()

        pending = 0
        completed = 0
        failed = 0
        oldest_ts = None

        for e in entries:
            status = e.get("status", "pending")
            if status in ("pending", "retry"):
                pending += 1
                ts = e.get("timestamp", 0)
                if oldest_ts is None or ts < oldest_ts:
                    oldest_ts = ts
            elif status == "completed":
                completed += 1
            elif status == "failed_permanent":
                failed += 1

        oldest_iso = None
        if oldest_ts:
            oldest_iso = datetime.fromtimestamp(oldest_ts, tz=timezone.utc).isoformat()

        return {
            "pending": pending,
            "completed": completed,
            "failed": failed,
            "oldest_pending_timestamp": oldest_iso,
        }

    # ── Online check ────────────────────────────────────────────────────────

    def is_online(self, gateway_url=None, rpc_url=None):
        """
        Quick connectivity health check.

        Returns True if BOTH the Gateway and the blockchain RPC are reachable.
        If either is down, new operations should go to the queue.
        """
        gw_url = gateway_url or DEFAULT_GATEWAY_URL
        rpc = rpc_url or DEFAULT_RPC_URL

        gateway_ok = False
        try:
            r = requests.get(f"{gw_url}/health", timeout=5)
            gateway_ok = r.status_code < 500
        except Exception:
            pass

        chain_ok = False
        try:
            r = requests.post(
                rpc,
                json={"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1},
                timeout=5,
            )
            chain_ok = r.status_code == 200 and "result" in r.json()
        except Exception:
            pass

        return gateway_ok and chain_ok

    # ── File I/O helpers ────────────────────────────────────────────────────

    def _read_all(self):
        """Read all entries from the queue file."""
        if not self._path.exists():
            return []

        entries = []
        try:
            with open(self._path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass
        return entries

    def _apply_updates(self, all_entries, updates):
        """Rewrite the queue file with updated entries."""
        with self._lock:
            try:
                tmp = str(self._path) + ".tmp"
                with open(tmp, "w") as f:
                    for entry in all_entries:
                        entry_id = entry.get("id", "")
                        if entry_id in updates:
                            f.write(json.dumps(updates[entry_id]) + "\n")
                        else:
                            f.write(json.dumps(entry) + "\n")
                os.replace(tmp, str(self._path))
            except OSError as e:
                log.error("Failed to update queue file: %s", e)


# ── Singleton ───────────────────────────────────────────────────────────

_instance = None
_instance_lock = Lock()


def get_offline_queue(queue_path=None):
    """Get or create the singleton OfflineQueue instance."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = OfflineQueue(queue_path=queue_path)
        return _instance


# ── Main demo ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile
    logging.basicConfig(level=logging.INFO, format="%(name)s  %(message)s")

    print("=== NEXUS Offline Queue Demo ===\n")

    # Use temp file for demo
    tmp_path = Path(tempfile.mktemp(suffix=".jsonl"))
    queue = OfflineQueue(queue_path=tmp_path)

    # Check online status
    print("--- Online check ---")
    online = queue.is_online()
    print(f"  Gateway + blockchain reachable: {online}")

    # Enqueue some operations
    print("\n--- Enqueue operations ---")
    ops = [
        {"op_type": "ect_spend", "requester_wallet": "0xAlice",
         "cost": 5, "task_id": "a" * 64, "operation": "exec"},
        {"op_type": "rst_update", "node_wallet": "0xBob",
         "action": "earn", "amount": 1, "reason": "task completed"},
        {"op_type": "heartbeat", "payload": {"node": "nexus-admin", "cpu": 45.2}},
        {"op_type": "block_write", "decision": "test_op", "reasoning": "offline demo"},
        {"op_type": "command_response", "payload": {"cmd_id": "123", "output": "OK"}},
    ]

    for op in ops:
        entry_id = queue.enqueue(op)
        print(f"  Enqueued: {entry_id} ({op['op_type']})")

    # Check status
    print("\n--- Queue status ---")
    status = queue.get_queue_status()
    print(f"  Pending:   {status['pending']}")
    print(f"  Completed: {status['completed']}")
    print(f"  Failed:    {status['failed']}")
    print(f"  Oldest:    {status['oldest_pending_timestamp']}")

    print(f"\n  Pending count: {queue.get_pending_count()}")

    # Attempt drain (will fail since services are targeted at default URLs)
    print("\n--- Drain attempt ---")
    result = queue.drain(gateway_url="http://127.0.0.1:9999")  # intentionally wrong
    print(f"  Processed:        {result['processed']}")
    print(f"  Completed:        {result['completed']}")
    print(f"  Retried:          {result['retried']}")
    print(f"  Failed permanent: {result['failed_permanent']}")

    # Check status after drain
    print("\n--- Queue status after drain ---")
    status = queue.get_queue_status()
    print(f"  Pending:   {status['pending']}")
    print(f"  Completed: {status['completed']}")
    print(f"  Failed:    {status['failed']}")

    # Simulate exhausting retries
    print("\n--- Exhaust retries (drain 5 more times) ---")
    for i in range(5):
        queue.drain(gateway_url="http://127.0.0.1:9999")
    status = queue.get_queue_status()
    print(f"  Pending:   {status['pending']}")
    print(f"  Failed:    {status['failed']}")

    # Cleanup
    tmp_path.unlink(missing_ok=True)
    print("\nDone.")
