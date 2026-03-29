"""Session behavioral channel — idle/active state, breaks, session boundaries."""

import json
import os
import subprocess
import time
from datetime import datetime, timezone

from modules.channels.base_channel import BaseChannel


class SessionChannel(BaseChannel):
    """
    Tracks the macro-structure of device usage: sessions, breaks, idle time.

    Records:
    - SESS_LOGIN (1): User logged in (with method)
    - SESS_LOGOUT (2): User logged out
    - SESS_LOCK (3): Screen locked
    - SESS_UNLOCK (4): Screen unlocked
    - SESS_IDLE_START (5): No input > 30 seconds (micro-idle)
    - SESS_IDLE_END (6): Input resumed after micro-idle
    - SESS_BREAK_START (7): No input > 5 minutes (break)
    - SESS_BREAK_END (8): Input resumed after break

    Also tracks internally (not separate action types, but included
    in compound token metadata):
    - Away detection (> 30 min idle)
    - Session boundaries (idle > 5 min = new session)
    - First activity of day
    - Session count, duration, inter-session gaps
    """

    IDLE_CHECK_INTERVAL = 5     # seconds between idle checks
    MICRO_IDLE_THRESHOLD = 30   # seconds: micro-idle (thinking/reading)
    BREAK_THRESHOLD = 300       # seconds: break (5 min)
    AWAY_THRESHOLD = 1800       # seconds: away (30 min)
    SESSION_BOUNDARY = 300      # seconds: gap that defines a new session

    def __init__(self, client):
        super().__init__(client, 9, 'session')
        self._idle_state = 'active'  # active, micro_idle, break, away
        self._idle_start_time = None
        self._last_active_time = time.time()
        self._screen_locked = False
        self._session_start = time.time()
        self._session_count = 0
        self._today_first_activity = False
        self._today_date = None
        self._prev_idle_ms = 0
        self._total_active_time = 0
        self._total_idle_time = 0
        self._session_durations = []
        self._inter_session_gaps = []

    def _get_idle_ms(self):
        """Get idle time in milliseconds via xprintidle."""
        try:
            result = subprocess.run(
                ['xprintidle'],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                return int(result.stdout.strip())
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            pass

        # Fallback: read from /proc/interrupts delta (very rough)
        return None

    def _is_screen_locked(self):
        """Check if the screen is locked via loginctl."""
        try:
            result = subprocess.run(
                ['loginctl', 'show-session', 'auto', '--property=LockedHint'],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                return 'yes' in result.stdout.lower()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Fallback: check for common lock screen processes
        try:
            result = subprocess.run(
                ['pgrep', '-x', 'swaylock|i3lock|light-locker|xscreensaver'],
                capture_output=True, text=True, timeout=3,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return False

    def _get_login_method(self):
        """Determine how the user logged in."""
        try:
            result = subprocess.run(
                ['loginctl', 'show-session', 'auto',
                 '--property=Type', '--property=Remote', '--property=Service'],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                props = {}
                for line in result.stdout.strip().split('\n'):
                    if '=' in line:
                        k, v = line.split('=', 1)
                        props[k] = v

                if props.get('Remote') == 'yes':
                    return 'ssh'
                session_type = props.get('Type', '')
                if session_type in ('x11', 'wayland', 'mir'):
                    return 'gui'
                if session_type == 'tty':
                    return 'console'
                return session_type or 'unknown'
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return 'unknown'

    def _check_first_activity_of_day(self):
        """Check if this is the first activity of the calendar day."""
        today = datetime.now(timezone.utc).date()
        if self._today_date != today:
            self._today_date = today
            self._today_first_activity = False

        if not self._today_first_activity:
            self._today_first_activity = True
            return True
        return False

    def _run(self):
        """Main session monitoring loop."""
        print(f"[{self.name}] Monitoring idle state (check every {self.IDLE_CHECK_INTERVAL}s)")

        # Record initial login
        method = self._get_login_method()
        self._record_login(method)
        self._session_count = 1
        self._session_start = time.time()

        while self.active:
            try:
                self._poll_cycle()
            except Exception as e:
                self.errors += 1
            time.sleep(self.IDLE_CHECK_INTERVAL)

    def _poll_cycle(self):
        """Single idle check cycle."""
        now = time.time()
        idle_ms = self._get_idle_ms()

        if idle_ms is None:
            return

        idle_s = idle_ms / 1000.0

        # Screen lock detection
        locked = self._is_screen_locked()
        if locked and not self._screen_locked:
            self._screen_locked = True
            self._record_lock()
        elif not locked and self._screen_locked:
            self._screen_locked = False
            self._record_unlock()

        # State machine: active → micro_idle → break → away
        prev_state = self._idle_state

        if idle_s < self.MICRO_IDLE_THRESHOLD:
            new_state = 'active'
        elif idle_s < self.BREAK_THRESHOLD:
            new_state = 'micro_idle'
        elif idle_s < self.AWAY_THRESHOLD:
            new_state = 'break'
        else:
            new_state = 'away'

        # Handle state transitions
        if new_state != prev_state:
            self._handle_transition(prev_state, new_state, idle_s, now)
            self._idle_state = new_state

        # Track active/idle time
        if new_state == 'active':
            self._total_active_time += self.IDLE_CHECK_INTERVAL
        else:
            self._total_idle_time += self.IDLE_CHECK_INTERVAL

        self._prev_idle_ms = idle_ms

    def _handle_transition(self, old_state, new_state, idle_s, now):
        """Handle a state transition."""

        # Becoming active from any idle state
        if new_state == 'active' and old_state != 'active':
            idle_duration = now - self._idle_start_time if self._idle_start_time else 0

            if old_state == 'micro_idle':
                self._record_idle_end(idle_duration)
            elif old_state == 'break':
                self._record_break_end(idle_duration)
            elif old_state == 'away':
                self._record_break_end(idle_duration)

            # Session boundary detection
            if idle_duration >= self.SESSION_BOUNDARY:
                # End previous session
                session_duration = self._idle_start_time - self._session_start if self._idle_start_time else 0
                self._session_durations.append(session_duration)
                self._inter_session_gaps.append(idle_duration)

                # Start new session
                self._session_count += 1
                self._session_start = now

            # First activity of day
            if self._check_first_activity_of_day():
                self._record_first_activity()

            self._last_active_time = now
            self._idle_start_time = None

        # Entering micro-idle
        elif new_state == 'micro_idle' and old_state == 'active':
            self._idle_start_time = now
            self._record_idle_start()

        # Entering break from micro-idle
        elif new_state == 'break' and old_state == 'micro_idle':
            self._record_break_start(idle_s)

        # Entering away from break
        elif new_state == 'away' and old_state == 'break':
            # Already in break — just continues. Away is tracked in compound metadata.
            pass

        # Direct jump to break (shouldn't happen normally, but handle it)
        elif new_state == 'break' and old_state == 'active':
            self._idle_start_time = now
            self._record_idle_start()
            self._record_break_start(idle_s)

    def _record_login(self, method):
        data = json.dumps({
            'method': method,
            'session_count': self._session_count,
        }).encode('utf-8')
        self._record(1, data)  # SESS_LOGIN

    def _record_logout(self):
        session_duration = time.time() - self._session_start
        data = json.dumps({
            'session_duration_s': round(session_duration, 1),
            'session_count': self._session_count,
        }).encode('utf-8')
        self._record(2, data)  # SESS_LOGOUT

    def _record_lock(self):
        data = json.dumps({'locked': True}).encode('utf-8')
        self._record(3, data)  # SESS_LOCK

    def _record_unlock(self):
        data = json.dumps({'locked': False}).encode('utf-8')
        self._record(4, data)  # SESS_UNLOCK

    def _record_idle_start(self):
        data = json.dumps({
            'threshold_s': self.MICRO_IDLE_THRESHOLD,
        }).encode('utf-8')
        self._record(5, data)  # SESS_IDLE_START

    def _record_idle_end(self, duration):
        data = json.dumps({
            'idle_duration_s': round(duration, 1),
        }).encode('utf-8')
        self._record(6, data)  # SESS_IDLE_END

    def _record_break_start(self, idle_s):
        data = json.dumps({
            'idle_s': round(idle_s, 1),
            'threshold_s': self.BREAK_THRESHOLD,
        }).encode('utf-8')
        self._record(7, data)  # SESS_BREAK_START

    def _record_break_end(self, duration):
        data = json.dumps({
            'break_duration_s': round(duration, 1),
            'was_away': duration >= self.AWAY_THRESHOLD,
        }).encode('utf-8')
        self._record(8, data)  # SESS_BREAK_END

    def _record_first_activity(self):
        """Record the first activity of the calendar day (internal — uses idle_end type)."""
        now = datetime.now(timezone.utc)
        data = json.dumps({
            'first_activity': True,
            'time_utc': now.strftime('%H:%M:%S'),
            'session_count_today': self._session_count,
        }).encode('utf-8')
        self._record(6, data)  # SESS_IDLE_END (with first_activity flag)

    def get_session_stats(self):
        """Return session-level statistics for compound token metadata."""
        now = time.time()
        current_session_duration = now - self._session_start
        total_time = self._total_active_time + self._total_idle_time

        return {
            'session_count': self._session_count,
            'current_session_s': round(current_session_duration, 1),
            'idle_state': self._idle_state,
            'total_active_s': round(self._total_active_time, 1),
            'total_idle_s': round(self._total_idle_time, 1),
            'active_pct': round(self._total_active_time / max(total_time, 1) * 100, 1),
            'avg_session_s': round(
                sum(self._session_durations) / max(len(self._session_durations), 1), 1
            ),
            'avg_gap_s': round(
                sum(self._inter_session_gaps) / max(len(self._inter_session_gaps), 1), 1
            ),
            'screen_locked': self._screen_locked,
        }

    def stop(self):
        """Override stop to record logout."""
        if self.active:
            self._record_logout()
        super().stop()
