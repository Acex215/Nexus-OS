"""Compound token minter and batch flush orchestrator."""

import json
import struct
import threading
import time
from collections import Counter

import sys
sys.path.insert(0, '/opt/nexus')

from libnexus.behavioral_client import BehavioralClient


class CompoundMinter:
    """
    Every 5 minutes, reads the last 5 minutes of on-chain actions
    and mints a single compound token that wraps them.

    The compound token's aggregate data contains:
    - action_count: total actions in the window
    - channels: {channel_id: count} distribution
    - dominant: channel with the most actions
    - intensity: LOW (<20 actions), MEDIUM (20-100), HIGH (>100)
    - channel_diversity: number of distinct channels active
    """

    COMPOUND_INTERVAL = 300  # 5 minutes

    def __init__(self, client: BehavioralClient = None):
        self.client = client or BehavioralClient()
        self._thread = None
        self.active = False
        self._last_action_id = None
        self.compounds_minted = 0

    def start(self):
        """Start the compound minting loop."""
        if self.active:
            return
        self.active = True
        self._thread = threading.Thread(target=self._run, daemon=True, name='compound-minter')
        self._thread.start()
        print("[CompoundMinter] Started (minting every 5 min)")

    def stop(self):
        """Stop the compound minter."""
        self.active = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        print(f"[CompoundMinter] Stopped ({self.compounds_minted} compounds minted)")

    def _run(self):
        """Main minting loop."""
        # Initialize: get current action count as baseline
        try:
            total = self.client.get_total_actions()
            self._last_action_id = total - 1 if total > 0 else -1
        except Exception as e:
            print(f"[CompoundMinter] Init failed: {e}")
            self._last_action_id = -1

        while self.active:
            time.sleep(self.COMPOUND_INTERVAL)
            if not self.active:
                break

            try:
                self._mint_compound()
            except Exception as e:
                print(f"[CompoundMinter] Error: {e}")

    def _mint_compound(self):
        """Mint a compound token for the last 5-minute window."""
        try:
            total = self.client.get_total_actions()
        except Exception:
            return

        if total <= 0:
            return

        current_last = total - 1

        # No new actions since last compound
        if current_last <= self._last_action_id:
            return

        start_id = self._last_action_id + 1
        end_id = current_last

        # Read actions in the window
        channel_counts = Counter()
        action_count = 0

        for aid in range(start_id, end_id + 1):
            try:
                action = self.client.get_action(aid)
                channel_counts[action['channelId']] += 1
                action_count += 1
            except Exception:
                pass

        if action_count == 0:
            self._last_action_id = end_id
            return

        # Compute aggregate data
        dominant = channel_counts.most_common(1)[0][0] if channel_counts else 0

        if action_count < 20:
            intensity = 'LOW'
        elif action_count <= 100:
            intensity = 'MEDIUM'
        else:
            intensity = 'HIGH'

        channel_diversity = len(channel_counts)

        aggregate = {
            'action_count': action_count,
            'channels': dict(channel_counts),
            'dominant': dominant,
            'intensity': intensity,
            'channel_diversity': channel_diversity,
            'window_s': self.COMPOUND_INTERVAL,
            'minted_at': int(time.time()),
        }

        aggregate_bytes = json.dumps(aggregate).encode('utf-8')

        # Get unique channel IDs for the compound
        channel_ids = sorted(channel_counts.keys())

        # Mint the compound token on-chain
        try:
            compound_id = self.client.mint_compound(
                start_id, end_id, channel_ids, aggregate_bytes
            )
            self.compounds_minted += 1
            print(f"[CompoundMinter] Minted compound #{compound_id}: "
                  f"{action_count} actions, {channel_diversity} channels, "
                  f"dominant=ch{dominant}, intensity={intensity}")
        except Exception as e:
            print(f"[CompoundMinter] Mint failed: {e}")

        self._last_action_id = end_id

    def get_stats(self):
        """Return minting statistics."""
        return {
            'active': self.active,
            'compounds_minted': self.compounds_minted,
            'last_action_id': self._last_action_id,
            'interval_s': self.COMPOUND_INTERVAL,
        }


class BatchFlushOrchestrator:
    """
    Every 1 second, flushes all pending high-frequency batches
    (keystrokes, mouse positions, scroll events) to the chain.

    This runs as a single thread that calls client.flush_all_batches()
    on a 1-second interval, ensuring that high-frequency channels
    don't accumulate unbounded in-memory buffers.
    """

    FLUSH_INTERVAL = 1.0  # seconds

    def __init__(self, client: BehavioralClient = None):
        self.client = client or BehavioralClient()
        self._thread = None
        self.active = False
        self.flush_count = 0
        self.total_flushed_batches = 0

    def start(self):
        """Start the batch flush loop."""
        if self.active:
            return
        self.active = True
        self._thread = threading.Thread(target=self._run, daemon=True, name='batch-flush')
        self._thread.start()
        print("[BatchFlushOrchestrator] Started (flushing every 1s)")

    def stop(self):
        """Stop the batch flusher."""
        self.active = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        # Final flush
        try:
            self.client.flush_all_batches()
        except Exception:
            pass
        print(f"[BatchFlushOrchestrator] Stopped ({self.flush_count} flush cycles)")

    def _run(self):
        """Main flush loop."""
        while self.active:
            try:
                # Count pending batches before flush
                pending = len([k for k, v in self.client._pending_batch.items() if v])

                if pending > 0:
                    self.client.flush_all_batches()
                    self.total_flushed_batches += pending
                    self.flush_count += 1
            except Exception as e:
                pass  # Don't crash the orchestrator on transient errors
            time.sleep(self.FLUSH_INTERVAL)

    def get_stats(self):
        """Return flush statistics."""
        pending = 0
        try:
            pending = len([k for k, v in self.client._pending_batch.items() if v])
        except Exception:
            pass

        return {
            'active': self.active,
            'flush_cycles': self.flush_count,
            'total_batches_flushed': self.total_flushed_batches,
            'pending_batches': pending,
            'interval_s': self.FLUSH_INTERVAL,
        }
