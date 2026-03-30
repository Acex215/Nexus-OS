"""Daily differential privacy budget manager.

Tracks ε spending per day, auto-resets at UTC midnight.
Budget state persisted to JSON for crash recovery.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone

log = logging.getLogger('nexus.privacy_budget')

DEFAULT_BUDGET_FILE = '/opt/nexus/config/privacy_budget.json'


class PrivacyBudgetManager:
    """Manage daily differential privacy budget (ε)."""

    def __init__(self, daily_epsilon: float = 1.0, budget_file: str = DEFAULT_BUDGET_FILE):
        self.daily_epsilon = daily_epsilon
        self.budget_file = budget_file
        self._state = self._load_state()
        self._maybe_reset()

    def get_remaining(self) -> float:
        """Return remaining ε for today. Auto-resets if new day."""
        self._maybe_reset()
        return self._state['remaining']

    def spend(self, epsilon: float, operation: str = 'unknown') -> bool:
        """Attempt to spend ε from today's budget.

        Args:
            epsilon: amount to spend.
            operation: label for the spend log.

        Returns:
            True if budget was sufficient and spent, False if exhausted.
        """
        self._maybe_reset()

        if epsilon <= 0:
            return True

        if self._state['remaining'] < epsilon:
            log.warning('Privacy budget exhausted: requested %.4f, remaining %.4f',
                       epsilon, self._state['remaining'])
            return False

        self._state['remaining'] -= epsilon
        self._state['remaining'] = max(self._state['remaining'], 0.0)

        entry = {
            'time': int(time.time()),
            'amount': epsilon,
            'remaining': round(self._state['remaining'], 6),
            'op': operation,
        }
        self._state['spends'].append(entry)

        log.info('Privacy spend: ε=%.4f for %s, remaining=%.4f',
                epsilon, operation, self._state['remaining'])

        self._save_state()
        return True

    def reset(self):
        """Reset budget to daily_epsilon. Clears spend log."""
        today = _today_str()
        self._state = {
            'daily_epsilon': self.daily_epsilon,
            'remaining': self.daily_epsilon,
            'last_reset': today,
            'spends': [],
        }
        self._save_state()
        log.info('Privacy budget reset: ε=%.4f for %s', self.daily_epsilon, today)

    def get_history(self) -> list:
        """Return today's spend log."""
        self._maybe_reset()
        return list(self._state['spends'])

    def get_optimal_epsilon(self, remaining_operations: int = 1) -> float:
        """Suggest optimal ε per operation for remaining budget.

        Args:
            remaining_operations: how many more operations planned today.

        Returns:
            Recommended ε per operation.
        """
        self._maybe_reset()
        return self._state['remaining'] / max(remaining_operations, 1)

    def _maybe_reset(self):
        """Auto-reset if a new UTC day has started."""
        today = _today_str()
        if self._state.get('last_reset') != today:
            old_date = self._state.get('last_reset', 'never')
            self.reset()
            if old_date != 'never':
                log.info('Auto-reset: new day %s (was %s)', today, old_date)

    def _load_state(self) -> dict:
        """Load budget state from file, or create default."""
        if os.path.exists(self.budget_file):
            try:
                with open(self.budget_file, 'r') as f:
                    state = json.load(f)
                # Validate required fields
                if all(k in state for k in ('daily_epsilon', 'remaining', 'last_reset', 'spends')):
                    # Sync daily_epsilon in case it changed
                    state['daily_epsilon'] = self.daily_epsilon
                    return state
            except (json.JSONDecodeError, IOError) as e:
                log.warning('Cannot load budget file: %s — creating fresh state', e)

        return {
            'daily_epsilon': self.daily_epsilon,
            'remaining': self.daily_epsilon,
            'last_reset': _today_str(),
            'spends': [],
        }

    def _save_state(self):
        """Persist budget state to file."""
        try:
            os.makedirs(os.path.dirname(self.budget_file), exist_ok=True)
            with open(self.budget_file, 'w') as f:
                json.dump(self._state, f, indent=2)
        except IOError as e:
            log.error('Cannot save budget file: %s', e)


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')
