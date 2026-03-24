"""
NEXUS OS — Circuit Breaker Module

Agent safety framework. Independently toggleable circuit breakers that
prevent AI agents from causing cascading damage. State is persisted to
disk and optionally logged on-chain via ReasoningLedger.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from threading import Lock

log = logging.getLogger("nexus.circuit_breaker")

STATE_FILE = Path("/opt/nexus/config/circuit_breakers.json")
RPC_URL = "http://10.0.20.3:8545"
DEPLOYER = "0x817B0842B208B76A7665948F8D1A0592F9b1e958"

# Breaker names
PAUSE_REPAIRS = "PAUSE_REPAIRS"
PAUSE_TOKEN_ACTIONS = "PAUSE_TOKEN_ACTIONS"
PAUSE_DEPLOYMENTS = "PAUSE_DEPLOYMENTS"
PAUSE_INFERENCE = "PAUSE_INFERENCE"
SAFE_MODE = "SAFE_MODE"

ALL_BREAKERS = [PAUSE_REPAIRS, PAUSE_TOKEN_ACTIONS, PAUSE_DEPLOYMENTS, PAUSE_INFERENCE, SAFE_MODE]

DEFAULT_STATE = {
    name: {
        "paused": False,
        "reason": "",
        "triggered_by": "",
        "timestamp": 0,
    }
    for name in ALL_BREAKERS
}


class CircuitBreaker:
    """Agent safety circuit breakers with auto-trigger support."""

    def __init__(self, state_file=None, log_on_chain=True):
        self._state_file = Path(state_file) if state_file else STATE_FILE
        self._lock = Lock()
        self._auto_triggers = {}  # breaker_name → list of (condition_fn, description)
        self._log_on_chain = log_on_chain
        self._state = self._load_state()

    def _load_state(self):
        """Load breaker state from disk, creating defaults if needed."""
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        if self._state_file.exists():
            try:
                with open(self._state_file) as f:
                    state = json.load(f)
                # Ensure all breakers exist
                for name in ALL_BREAKERS:
                    if name not in state:
                        state[name] = DEFAULT_STATE[name].copy()
                return state
            except (json.JSONDecodeError, OSError) as e:
                log.warning("Corrupt breaker state, resetting: %s", e)
        return {k: v.copy() for k, v in DEFAULT_STATE.items()}

    def _save_state(self):
        """Persist breaker state to disk."""
        try:
            with open(self._state_file, "w") as f:
                json.dump(self._state, f, indent=2)
        except OSError as e:
            log.error("Failed to save breaker state: %s", e)

    def _log_to_chain(self, decision, reasoning):
        """Log breaker event to ReasoningLedger on-chain."""
        if not self._log_on_chain:
            return
        try:
            if '/opt/nexus' not in sys.path:
                sys.path.insert(0, '/opt/nexus')
            from libnexus import NexusKernel
            kernel = NexusKernel(rpc_url=RPC_URL, wallet=DEPLOYER)
            result = kernel.log_reasoning(decision, reasoning)
            log.info("Circuit breaker event logged on-chain: block=%d", result['block'])
        except Exception as exc:
            log.warning("On-chain logging failed: %s", exc)

    # ── Core API ──────────────────────────────────────────────────────

    def is_paused(self, breaker_name):
        """Check if a breaker is currently paused.

        Args:
            breaker_name: one of ALL_BREAKERS constants

        Returns:
            bool: True if paused
        """
        with self._lock:
            breaker = self._state.get(breaker_name, {})
            return breaker.get("paused", False)

    def get_reason(self, breaker_name):
        """Get the reason a breaker was triggered."""
        with self._lock:
            breaker = self._state.get(breaker_name, {})
            return breaker.get("reason", "")

    def pause(self, breaker_name, reason, triggered_by="system"):
        """Pause a circuit breaker.

        Args:
            breaker_name: breaker to pause
            reason: human-readable reason
            triggered_by: who/what triggered the pause

        Returns:
            bool: True if state changed (was not already paused)
        """
        if breaker_name not in ALL_BREAKERS:
            log.error("Unknown breaker: %s", breaker_name)
            return False

        with self._lock:
            breaker = self._state.get(breaker_name, {})
            was_paused = breaker.get("paused", False)

            self._state[breaker_name] = {
                "paused": True,
                "reason": reason,
                "triggered_by": triggered_by,
                "timestamp": int(time.time()),
            }
            self._save_state()

        if not was_paused:
            log.warning("[CB] %s PAUSED by %s: %s", breaker_name, triggered_by, reason)
            self._log_to_chain(
                f"Circuit breaker {breaker_name} PAUSED",
                f"Triggered by {triggered_by}: {reason}"
            )
        return not was_paused

    def resume(self, breaker_name, reason, triggered_by="admin"):
        """Resume a circuit breaker.

        Args:
            breaker_name: breaker to resume
            reason: human-readable reason
            triggered_by: who/what triggered the resume

        Returns:
            bool: True if state changed (was paused)
        """
        if breaker_name not in ALL_BREAKERS:
            log.error("Unknown breaker: %s", breaker_name)
            return False

        with self._lock:
            breaker = self._state.get(breaker_name, {})
            was_paused = breaker.get("paused", False)

            self._state[breaker_name] = {
                "paused": False,
                "reason": reason,
                "triggered_by": triggered_by,
                "timestamp": int(time.time()),
            }
            self._save_state()

        if was_paused:
            log.info("[CB] %s RESUMED by %s: %s", breaker_name, triggered_by, reason)
            self._log_to_chain(
                f"Circuit breaker {breaker_name} RESUMED",
                f"Triggered by {triggered_by}: {reason}"
            )
        return was_paused

    def get_status(self):
        """Get status of all circuit breakers.

        Returns:
            dict: {breaker_name: {paused, reason, triggered_by, timestamp}}
        """
        with self._lock:
            return {k: dict(v) for k, v in self._state.items()}

    # ── Safe mode ───────────────────────────────────────────────────

    @property
    def safe_mode_active(self):
        """Check if safe mode is currently active.
        When active, ALL automated operations require manual approval."""
        return self.is_paused(SAFE_MODE)

    def activate_safe_mode(self, reason, triggered_by="system"):
        """Activate safe mode: pause ALL breakers and flag for manual resume.

        Args:
            reason: human-readable reason
            triggered_by: who/what triggered safe mode

        Returns:
            bool: True if state changed
        """
        changed = False
        # Pause every individual breaker
        for breaker in [PAUSE_REPAIRS, PAUSE_TOKEN_ACTIONS, PAUSE_DEPLOYMENTS, PAUSE_INFERENCE]:
            if not self.is_paused(breaker):
                self.pause(breaker, f"SAFE MODE: {reason}", triggered_by)
                changed = True
        # Set the SAFE_MODE flag itself
        if not self.is_paused(SAFE_MODE):
            self.pause(SAFE_MODE, reason, triggered_by)
            changed = True
        if changed:
            log.critical("[CB] SAFE MODE ACTIVATED by %s: %s", triggered_by, reason)
        return changed

    def deactivate_safe_mode(self, reason="manual resume", triggered_by="admin"):
        """Deactivate safe mode. Individual breakers must be resumed separately.

        Only clears the SAFE_MODE flag. Individual breakers remain paused
        and must be explicitly resumed one-by-one for safety.

        Args:
            reason: human-readable reason
            triggered_by: who/what deactivated safe mode

        Returns:
            bool: True if state changed
        """
        changed = self.resume(SAFE_MODE, reason, triggered_by)
        if changed:
            log.info("[CB] SAFE MODE DEACTIVATED by %s: %s — "
                     "individual breakers still paused, resume each manually",
                     triggered_by, reason)
        return changed

    # ── Auto-trigger ──────────────────────────────────────────────────

    def auto_trigger(self, breaker_name, condition_fn, description=""):
        """Register a condition function that auto-pauses a breaker if met.

        Args:
            breaker_name: breaker to pause if condition is True
            condition_fn: callable() → bool (True means trigger pause)
            description: human-readable description of the condition
        """
        if breaker_name not in ALL_BREAKERS:
            log.error("Unknown breaker: %s", breaker_name)
            return

        if breaker_name not in self._auto_triggers:
            self._auto_triggers[breaker_name] = []

        self._auto_triggers[breaker_name].append((condition_fn, description))
        log.info("[CB] Registered auto-trigger for %s: %s", breaker_name, description)

    def check_auto_triggers(self):
        """Evaluate all registered auto-trigger conditions.
        Should be called periodically (e.g., every minute).

        Returns:
            list: names of breakers that were auto-triggered
        """
        triggered = []
        for breaker_name, conditions in self._auto_triggers.items():
            if self.is_paused(breaker_name):
                continue
            for condition_fn, description in conditions:
                try:
                    if condition_fn():
                        self.pause(
                            breaker_name,
                            reason=f"Auto-trigger: {description}",
                            triggered_by="auto_trigger"
                        )
                        triggered.append(breaker_name)
                        break  # One trigger is enough per breaker
                except Exception as exc:
                    log.warning("[CB] Auto-trigger check failed for %s: %s",
                                breaker_name, exc)
        return triggered


# ── Singleton ─────────────────────────────────────────────────────────

_instance = None
_instance_lock = Lock()


def get_circuit_breaker(log_on_chain=True):
    """Get or create the singleton CircuitBreaker instance."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = CircuitBreaker(log_on_chain=log_on_chain)
        return _instance


# ── Default auto-trigger condition helpers ────────────────────────────

def _make_ect_spend_rate_checker(threshold=500):
    """Returns a condition_fn that checks if ECT spend rate > threshold/hour."""
    _history = []

    def check():
        try:
            if '/opt/nexus' not in sys.path:
                sys.path.insert(0, '/opt/nexus')
            from libnexus.token_client import TokenClient
            tc = TokenClient()
            totals = tc.get_totals()
            now = time.time()
            _history.append((now, totals['ect_spent']))

            # Keep only last hour
            cutoff = now - 3600
            while _history and _history[0][0] < cutoff:
                _history.pop(0)

            if len(_history) < 2:
                return False

            rate = _history[-1][1] - _history[0][1]
            if rate > threshold:
                log.warning("[CB] ECT spend rate: %d/hour (threshold: %d)", rate, threshold)
                return True
            return False
        except Exception:
            return False

    return check


def _make_repair_rate_checker(threshold=10):
    """Returns a condition_fn that checks repair request rate."""
    _log_path = Path("/opt/nexus/logs/repair_requests.jsonl")

    def check():
        if not _log_path.exists():
            return False
        try:
            cutoff = time.time() - 3600
            count = 0
            with open(_log_path) as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get("timestamp", 0) > cutoff:
                            count += 1
                    except json.JSONDecodeError:
                        continue
            if count > threshold:
                log.warning("[CB] Repair requests: %d/hour (threshold: %d)", count, threshold)
                return True
            return False
        except Exception:
            return False

    return check


def _make_agent_failure_checker(threshold=5, window=600):
    """Returns a condition_fn that checks agent failures in the last N seconds."""
    _log_path = Path("/opt/nexus/agents/logs/task_log.jsonl")

    def check():
        if not _log_path.exists():
            return False
        try:
            cutoff = time.time() - window
            failures = 0
            with open(_log_path) as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        ts = entry.get("timestamp", 0)
                        if isinstance(ts, str):
                            continue
                        if ts > cutoff and not entry.get("success", True):
                            failures += 1
                    except json.JSONDecodeError:
                        continue
            if failures > threshold:
                log.warning("[CB] Agent failures: %d in %ds (threshold: %d)",
                            failures, window, threshold)
                return True
            return False
        except Exception:
            return False

    return check


def register_default_triggers(cb=None):
    """Register the standard auto-trigger conditions."""
    if cb is None:
        cb = get_circuit_breaker()

    cb.auto_trigger(
        PAUSE_TOKEN_ACTIONS,
        _make_ect_spend_rate_checker(500),
        "ECT spend rate > 500/hour"
    )
    cb.auto_trigger(
        PAUSE_REPAIRS,
        _make_repair_rate_checker(10),
        "Storage repair requests > 10/hour"
    )
    cb.auto_trigger(
        PAUSE_INFERENCE,
        _make_agent_failure_checker(5, 600),
        "Agent failures > 5 in 10 minutes"
    )

    log.info("[CB] Default auto-triggers registered")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    print("=== NEXUS Circuit Breaker Demo ===\n")

    # Use a temp state file so we don't affect production
    cb = CircuitBreaker(state_file="/tmp/nexus_cb_test.json", log_on_chain=False)

    # 1. Check initial status
    print("--- Initial Status ---")
    status = cb.get_status()
    for name, info in status.items():
        print(f"  {name}: {'PAUSED' if info['paused'] else 'OK'}")

    # 2. Pause a breaker
    print("\n--- Pause PAUSE_TOKEN_ACTIONS ---")
    changed = cb.pause(PAUSE_TOKEN_ACTIONS, "ECT drain detected", "auto_trigger")
    print(f"  Changed: {changed}")
    print(f"  is_paused: {cb.is_paused(PAUSE_TOKEN_ACTIONS)}")
    print(f"  Reason: {cb.get_reason(PAUSE_TOKEN_ACTIONS)}")

    # 3. Check in cost_check simulation
    print("\n--- Simulated cost_check ---")
    if cb.is_paused(PAUSE_TOKEN_ACTIONS):
        print("  [CB] Token actions paused — skipping ECT spend")
    else:
        print("  ECT spend would proceed")

    # 4. Resume
    print("\n--- Resume PAUSE_TOKEN_ACTIONS ---")
    changed = cb.resume(PAUSE_TOKEN_ACTIONS, "Manual override", "admin")
    print(f"  Changed: {changed}")
    print(f"  is_paused: {cb.is_paused(PAUSE_TOKEN_ACTIONS)}")

    # 5. Auto-trigger
    print("\n--- Auto-trigger Test ---")
    trigger_count = [0]

    def always_true():
        trigger_count[0] += 1
        return True

    cb.auto_trigger(PAUSE_INFERENCE, always_true, "test condition (always true)")
    triggered = cb.check_auto_triggers()
    print(f"  Triggered: {triggered}")
    print(f"  PAUSE_INFERENCE paused: {cb.is_paused(PAUSE_INFERENCE)}")
    print(f"  Reason: {cb.get_reason(PAUSE_INFERENCE)}")

    # 6. Final status
    print("\n--- Final Status ---")
    status = cb.get_status()
    for name, info in status.items():
        state = "PAUSED" if info["paused"] else "OK"
        extra = f" ({info['reason']})" if info['reason'] else ""
        print(f"  {name}: {state}{extra}")

    # Cleanup
    os.unlink("/tmp/nexus_cb_test.json")
    print("\n=== Done ===")
