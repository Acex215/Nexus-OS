"""Base class for all behavioral collection channels."""

import threading
import time


class BaseChannel:
    """
    Base class for behavioral collection channels.

    Each channel:
    - Runs in a daemon thread
    - Records actions via self.client (BehavioralClient)
    - Tracks event count and uptime
    - Can be started/stopped independently
    """

    def __init__(self, client, channel_id, name):
        self.client = client
        self.channel_id = channel_id
        self.name = name
        self.active = False
        self._thread = None
        self.event_count = 0
        self.start_time = None
        self.errors = 0

    def start(self):
        """Start the collection channel in a background thread."""
        if self.active:
            return
        self.active = True
        self.start_time = time.time()
        self._thread = threading.Thread(target=self._safe_run, daemon=True, name=f"ch-{self.name}")
        self._thread.start()
        print(f"[{self.name}] Started (channel {self.channel_id})")

    def stop(self):
        """Stop the collection channel."""
        self.active = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        print(f"[{self.name}] Stopped ({self.event_count} events captured)")

    def _safe_run(self):
        """Wrapper that catches exceptions so one channel can't crash the collector."""
        try:
            self._run()
        except Exception as e:
            self.errors += 1
            import traceback
            print(f"[{self.name}] Fatal error: {type(e).__name__}: {e}")
            traceback.print_exc()

    def _run(self):
        """Override this in each channel implementation."""
        raise NotImplementedError

    def get_stats(self):
        """Return channel statistics (safe to expose — no raw data)."""
        uptime = time.time() - self.start_time if self.start_time else 0
        return {
            'channel_id': self.channel_id,
            'name': self.name,
            'active': self.active,
            'event_count': self.event_count,
            'errors': self.errors,
            'uptime_seconds': int(uptime),
            'events_per_minute': round(self.event_count / max(uptime / 60, 1), 1) if uptime > 60 else 0
        }

    def _record(self, action_type, data_bytes):
        """Record a single significant action on-chain."""
        try:
            action_id = self.client.record_action(self.channel_id, action_type, data_bytes)
            self.event_count += 1
            return action_id
        except Exception as e:
            self.errors += 1
            if self.errors <= 3 or self.errors % 100 == 0:
                print(f"[{self.name}] _record error #{self.errors}: {type(e).__name__}: {e}")
            return None

    def _batch(self, action_type, micro_data):
        """Add a micro-action to the current 1-second batch."""
        try:
            self.client.add_to_batch(self.channel_id, action_type, micro_data)
            self.event_count += 1
        except Exception as e:
            self.errors += 1
            if self.errors <= 3 or self.errors % 100 == 0:
                print(f"[{self.name}] _batch error #{self.errors}: {type(e).__name__}: {e}")
