"""Input behavioral collection channels — Keystroke, Mouse, Window, Clipboard."""

import json
import struct
import subprocess
import time
import os

from modules.channels.base_channel import BaseChannel

try:
    import evdev
    from evdev import InputDevice, categorize, ecodes
    HAS_EVDEV = True
except ImportError:
    HAS_EVDEV = False


# ═══════════════════════════════════════════
# Channel 1: KEYSTROKE
# ═══════════════════════════════════════════

class KeystrokeChannel(BaseChannel):
    """
    Full keycode capture via evdev.

    Records:
    - KS_BATCH (1): 1-second aggregate of all keycodes + modifiers + inter-key intervals
    - KS_BURST_START (2): Fast typing burst detected (>5 keys/sec sustained)
    - KS_BURST_END (3): Fast typing burst ended
    - KS_LONG_PAUSE (4): No keystrokes for >5 seconds (thinking/reading)
    - KS_DELETE_BURST (5): Rapid deletion (>3 deletes in 2 seconds)
    - KS_SHORTCUT (6): Keyboard shortcut (Ctrl/Alt/Super + key)
    """

    # Modifier keycodes
    MODIFIER_CODES = {
        ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL,
        ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT,
        ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT,
        ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA,
    } if HAS_EVDEV else set()

    DELETE_CODES = {
        ecodes.KEY_BACKSPACE, ecodes.KEY_DELETE,
    } if HAS_EVDEV else set()

    def __init__(self, client):
        super().__init__(client, 1, 'keystroke')
        self._device = None
        self._active_modifiers = set()
        self._batch_keys = []
        self._batch_start = time.time()
        self._last_key_time = 0
        self._inter_key_intervals = []
        self._in_burst = False
        self._burst_start_time = 0
        self._burst_key_count = 0
        self._delete_times = []
        self._pause_reported = False

    def _find_keyboard(self):
        """Find the first keyboard input device."""
        if not HAS_EVDEV:
            return None
        devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
        for dev in devices:
            caps = dev.capabilities(verbose=True)
            for cap_name, events in caps.items():
                if cap_name == ('EV_KEY', 1):
                    # Check if it has letter keys (not just a mouse with buttons)
                    event_codes = [e[0] if isinstance(e, tuple) else e for e in events]
                    key_names = [str(e) for e in event_codes]
                    if any('KEY_A' in str(k) for k in key_names):
                        return dev
        return None

    def _run(self):
        """Main keystroke capture loop."""
        self._device = self._find_keyboard()
        if not self._device:
            print(f"[{self.name}] No keyboard device found")
            return

        print(f"[{self.name}] Capturing from: {self._device.name}")
        self._batch_start = time.time()

        for event in self._device.read_loop():
            if not self.active:
                break

            now = time.time()

            # Check for long pause
            if self._last_key_time > 0 and not self._pause_reported:
                gap = now - self._last_key_time
                if gap > 5.0:
                    self._record_long_pause(gap)
                    self._pause_reported = True

            # Only process key events
            if event.type != ecodes.EV_KEY:
                continue

            key_event = categorize(event)

            # Key press (value=1) or autorepeat (value=2)
            if key_event.keystate in (key_event.key_down, key_event.key_hold):
                keycode = event.code
                keyname = ecodes.KEY.get(keycode, f'KEY_{keycode}')
                if isinstance(keyname, list):
                    keyname = keyname[0]

                # Track modifiers
                if keycode in self.MODIFIER_CODES:
                    self._active_modifiers.add(keycode)
                    continue

                # Check for shortcut (modifier + key)
                if self._active_modifiers:
                    self._record_shortcut(keycode, keyname)

                # Inter-key interval
                if self._last_key_time > 0:
                    iki = now - self._last_key_time
                    self._inter_key_intervals.append(iki)
                self._last_key_time = now
                self._pause_reported = False

                # Add to batch
                self._batch_keys.append({
                    'code': keycode,
                    'name': str(keyname),
                    'mods': list(self._active_modifiers),
                    't': round((now - self._batch_start) * 1000),
                })

                # Delete burst detection
                if keycode in self.DELETE_CODES:
                    self._delete_times.append(now)
                    self._delete_times = [t for t in self._delete_times if now - t < 2.0]
                    if len(self._delete_times) >= 3:
                        self._record_delete_burst()
                        self._delete_times = []

                # Typing burst detection
                self._burst_key_count += 1
                if not self._in_burst:
                    if self._burst_key_count >= 5 and len(self._inter_key_intervals) >= 4:
                        recent_iki = self._inter_key_intervals[-4:]
                        avg_iki = sum(recent_iki) / len(recent_iki)
                        if avg_iki < 0.2:  # >5 keys/sec
                            self._in_burst = True
                            self._burst_start_time = now
                            self._record_burst_start()
                else:
                    if len(self._inter_key_intervals) >= 2:
                        if self._inter_key_intervals[-1] > 0.5:
                            self._record_burst_end(now - self._burst_start_time)
                            self._in_burst = False
                            self._burst_key_count = 0

                # Flush batch every 1 second
                if now - self._batch_start >= 1.0:
                    self._flush_batch()

            # Key release (value=0)
            elif key_event.keystate == key_event.key_up:
                keycode = event.code
                self._active_modifiers.discard(keycode)

    def _flush_batch(self):
        """Flush the 1-second keystroke batch to blockchain."""
        if not self._batch_keys:
            self._batch_start = time.time()
            return

        batch_data = {
            'keys': self._batch_keys,
            'count': len(self._batch_keys),
            'iki_avg': round(sum(self._inter_key_intervals[-len(self._batch_keys):]) /
                            max(len(self._batch_keys) - 1, 1) * 1000, 1)
                       if len(self._batch_keys) > 1 else 0,
        }
        data_bytes = json.dumps(batch_data).encode('utf-8')
        self._batch(1, data_bytes)  # KS_BATCH

        self._batch_keys = []
        self._batch_start = time.time()
        self._inter_key_intervals = self._inter_key_intervals[-20:]  # Keep last 20

    def _record_burst_start(self):
        """Record start of fast typing burst."""
        data = json.dumps({'avg_iki_ms': round(
            sum(self._inter_key_intervals[-4:]) / 4 * 1000, 1
        )}).encode('utf-8')
        self._record(2, data)  # KS_BURST_START

    def _record_burst_end(self, duration):
        """Record end of fast typing burst."""
        data = json.dumps({
            'duration_s': round(duration, 2),
            'keys_in_burst': self._burst_key_count,
        }).encode('utf-8')
        self._record(3, data)  # KS_BURST_END

    def _record_long_pause(self, gap):
        """Record a long pause (>5 seconds without keystrokes)."""
        data = json.dumps({'pause_s': round(gap, 2)}).encode('utf-8')
        self._record(4, data)  # KS_LONG_PAUSE

    def _record_delete_burst(self):
        """Record rapid deletion (self-editing signal)."""
        data = json.dumps({
            'deletes': len(self._delete_times),
            'window_s': 2.0,
        }).encode('utf-8')
        self._record(5, data)  # KS_DELETE_BURST

    def _record_shortcut(self, keycode, keyname):
        """Record a keyboard shortcut."""
        mod_names = []
        for m in self._active_modifiers:
            mn = ecodes.KEY.get(m, f'KEY_{m}')
            if isinstance(mn, list):
                mn = mn[0]
            mod_names.append(str(mn))
        data = json.dumps({
            'key': str(keyname),
            'modifiers': mod_names,
        }).encode('utf-8')
        self._record(6, data)  # KS_SHORTCUT


# ═══════════════════════════════════════════
# Channel 2: MOUSE
# ═══════════════════════════════════════════

class MouseChannel(BaseChannel):
    """
    Mouse movement, clicks, scroll, and hover detection via evdev.

    Records:
    - MS_BATCH (1): 1-second position/movement aggregate
    - MS_CLICK (2): Left click with absolute coordinates
    - MS_DOUBLE_CLICK (3): Double-click detected (<300ms between clicks)
    - MS_RIGHT_CLICK (4): Right click
    - MS_DRAG_START (5): Mouse button down + movement
    - MS_DRAG_END (6): Mouse button up after drag
    - MS_SCROLL (7): Scroll event batch (1-second aggregate)
    - MS_HOVER_LONG (8): Cursor stationary >2 seconds (decision hesitation)
    """

    def __init__(self, client):
        super().__init__(client, 2, 'mouse')
        self._device = None
        self._x = 0
        self._y = 0
        self._positions = []
        self._batch_start = time.time()
        self._last_click_time = 0
        self._last_click_btn = None
        self._button_down = False
        self._drag_active = False
        self._drag_start_pos = (0, 0)
        self._last_move_time = 0
        self._hover_reported = False
        self._scroll_batch = []
        self._scroll_batch_start = time.time()

    def _find_mouse(self):
        """Find the first mouse/pointer input device."""
        if not HAS_EVDEV:
            return None
        devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
        for dev in devices:
            caps = dev.capabilities()
            # Look for REL_X/REL_Y (relative mouse) or ABS_X/ABS_Y (touchpad)
            if ecodes.EV_REL in caps:
                rel_codes = [c for c in caps[ecodes.EV_REL]]
                if ecodes.REL_X in rel_codes and ecodes.REL_Y in rel_codes:
                    return dev
        return None

    def _run(self):
        """Main mouse capture loop."""
        self._device = self._find_mouse()
        if not self._device:
            print(f"[{self.name}] No mouse device found")
            return

        print(f"[{self.name}] Capturing from: {self._device.name}")
        self._batch_start = time.time()

        for event in self._device.read_loop():
            if not self.active:
                break

            now = time.time()

            # Hover detection (check on every event)
            if self._last_move_time > 0 and not self._hover_reported:
                if now - self._last_move_time > 2.0:
                    self._record_hover(now - self._last_move_time)
                    self._hover_reported = True

            # Relative movement
            if event.type == ecodes.EV_REL:
                if event.code == ecodes.REL_X:
                    self._x += event.value
                elif event.code == ecodes.REL_Y:
                    self._y += event.value
                elif event.code in (ecodes.REL_WHEEL, ecodes.REL_HWHEEL):
                    self._scroll_batch.append({
                        'axis': 'v' if event.code == ecodes.REL_WHEEL else 'h',
                        'value': event.value,
                        't': round((now - self._scroll_batch_start) * 1000),
                    })

                self._last_move_time = now
                self._hover_reported = False

                # Track position for batch
                self._positions.append({
                    'x': self._x, 'y': self._y,
                    't': round((now - self._batch_start) * 1000),
                })

                # Drag detection
                if self._button_down and not self._drag_active:
                    dx = abs(self._x - self._drag_start_pos[0])
                    dy = abs(self._y - self._drag_start_pos[1])
                    if dx > 10 or dy > 10:
                        self._drag_active = True
                        self._record_drag_start()

            # Button events
            elif event.type == ecodes.EV_KEY:
                if event.code == ecodes.BTN_LEFT:
                    if event.value == 1:  # Press
                        self._button_down = True
                        self._drag_start_pos = (self._x, self._y)

                        # Double-click detection
                        if now - self._last_click_time < 0.3 and self._last_click_btn == 'left':
                            self._record_double_click()
                        else:
                            self._record_click('left')

                        self._last_click_time = now
                        self._last_click_btn = 'left'

                    elif event.value == 0:  # Release
                        if self._drag_active:
                            self._record_drag_end()
                            self._drag_active = False
                        self._button_down = False

                elif event.code == ecodes.BTN_RIGHT:
                    if event.value == 1:
                        self._record_right_click()
                        self._last_click_time = now
                        self._last_click_btn = 'right'

                elif event.code == ecodes.BTN_MIDDLE:
                    if event.value == 1:
                        self._record_click('middle')

            # Flush batches every 1 second
            if now - self._batch_start >= 1.0:
                self._flush_position_batch()
            if now - self._scroll_batch_start >= 1.0:
                self._flush_scroll_batch()

    def _flush_position_batch(self):
        """Flush 1-second position batch."""
        if not self._positions:
            self._batch_start = time.time()
            return

        # Calculate movement stats
        total_dist = 0
        for i in range(1, len(self._positions)):
            dx = self._positions[i]['x'] - self._positions[i-1]['x']
            dy = self._positions[i]['y'] - self._positions[i-1]['y']
            total_dist += (dx*dx + dy*dy) ** 0.5

        batch_data = {
            'samples': len(self._positions),
            'start': {'x': self._positions[0]['x'], 'y': self._positions[0]['y']},
            'end': {'x': self._positions[-1]['x'], 'y': self._positions[-1]['y']},
            'distance': round(total_dist, 1),
        }
        data_bytes = json.dumps(batch_data).encode('utf-8')
        self._batch(1, data_bytes)  # MS_BATCH

        self._positions = []
        self._batch_start = time.time()

    def _flush_scroll_batch(self):
        """Flush 1-second scroll batch."""
        if not self._scroll_batch:
            self._scroll_batch_start = time.time()
            return

        total_v = sum(s['value'] for s in self._scroll_batch if s['axis'] == 'v')
        total_h = sum(s['value'] for s in self._scroll_batch if s['axis'] == 'h')
        data = json.dumps({
            'events': len(self._scroll_batch),
            'total_v': total_v,
            'total_h': total_h,
        }).encode('utf-8')
        self._batch(7, data)  # MS_SCROLL

        self._scroll_batch = []
        self._scroll_batch_start = time.time()

    def _record_click(self, button):
        data = json.dumps({'button': button, 'x': self._x, 'y': self._y}).encode('utf-8')
        self._record(2, data)  # MS_CLICK

    def _record_double_click(self):
        data = json.dumps({'x': self._x, 'y': self._y}).encode('utf-8')
        self._record(3, data)  # MS_DOUBLE_CLICK

    def _record_right_click(self):
        data = json.dumps({'x': self._x, 'y': self._y}).encode('utf-8')
        self._record(4, data)  # MS_RIGHT_CLICK

    def _record_drag_start(self):
        data = json.dumps({
            'start_x': self._drag_start_pos[0],
            'start_y': self._drag_start_pos[1],
        }).encode('utf-8')
        self._record(5, data)  # MS_DRAG_START

    def _record_drag_end(self):
        dx = abs(self._x - self._drag_start_pos[0])
        dy = abs(self._y - self._drag_start_pos[1])
        data = json.dumps({
            'end_x': self._x, 'end_y': self._y,
            'distance': round((dx*dx + dy*dy) ** 0.5, 1),
        }).encode('utf-8')
        self._record(6, data)  # MS_DRAG_END

    def _record_hover(self, duration):
        data = json.dumps({
            'x': self._x, 'y': self._y,
            'duration_s': round(duration, 2),
        }).encode('utf-8')
        self._record(8, data)  # MS_HOVER_LONG


# ═══════════════════════════════════════════
# Channel 3: WINDOW
# ═══════════════════════════════════════════

class WindowChannel(BaseChannel):
    """
    Window focus, title, and application tracking via xdotool.

    Records:
    - WIN_FOCUS (1): Window gained focus (full title, app class, PID)
    - WIN_BLUR (2): Window lost focus
    - WIN_OPEN (3): New window detected
    - WIN_CLOSE (4): Window disappeared
    - WIN_RESIZE (5): Window geometry changed
    - WIN_MOVE (6): Window position changed
    - WIN_MINIMIZE (7): Window minimized
    - WIN_MAXIMIZE (8): Window maximized
    - WIN_TITLE_CHANGE (9): Title changed (e.g. new tab in browser)
    """

    def __init__(self, client):
        super().__init__(client, 3, 'window')
        self._current_window_id = None
        self._current_title = None
        self._current_class = None
        self._current_pid = None
        self._known_windows = set()
        self._window_geometries = {}

    def _get_active_window(self):
        """Get the currently focused window ID."""
        try:
            result = subprocess.run(
                ['xdotool', 'getactivewindow'],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def _get_window_info(self, window_id):
        """Get window title, class, and PID."""
        info = {'title': '', 'class': '', 'pid': 0}
        try:
            # Title
            result = subprocess.run(
                ['xdotool', 'getwindowname', window_id],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0:
                info['title'] = result.stdout.strip()

            # PID
            result = subprocess.run(
                ['xdotool', 'getwindowpid', window_id],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0:
                info['pid'] = int(result.stdout.strip())

            # Class (WM_CLASS)
            result = subprocess.run(
                ['xprop', '-id', window_id, 'WM_CLASS'],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0 and '=' in result.stdout:
                info['class'] = result.stdout.split('=', 1)[1].strip().strip('"')
        except Exception:
            pass
        return info

    def _get_window_geometry(self, window_id):
        """Get window position and size."""
        try:
            result = subprocess.run(
                ['xdotool', 'getwindowgeometry', '--shell', window_id],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0:
                geo = {}
                for line in result.stdout.strip().split('\n'):
                    if '=' in line:
                        k, v = line.split('=', 1)
                        geo[k.strip()] = int(v.strip())
                return geo
        except Exception:
            pass
        return None

    def _get_all_windows(self):
        """Get list of all window IDs."""
        try:
            result = subprocess.run(
                ['xdotool', 'search', '--onlyvisible', '--name', ''],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                return set(result.stdout.strip().split('\n'))
        except Exception:
            pass
        return set()

    def _run(self):
        """Main window tracking loop — polls every 250ms."""
        print(f"[{self.name}] Polling window changes (250ms interval)")

        # Initialize known windows
        self._known_windows = self._get_all_windows()

        while self.active:
            try:
                self._poll_cycle()
            except Exception as e:
                self.errors += 1
            time.sleep(0.25)

    def _poll_cycle(self):
        """Single poll cycle — check focus, title, window list."""
        # Check active window
        active_id = self._get_active_window()
        if active_id and active_id != self._current_window_id:
            # Focus changed
            if self._current_window_id:
                self._record_blur()
            info = self._get_window_info(active_id)
            self._record_focus(active_id, info)
            self._current_window_id = active_id
            self._current_title = info['title']
            self._current_class = info['class']
            self._current_pid = info['pid']

        # Check title change (same window, different title — e.g. browser tab switch)
        elif active_id and active_id == self._current_window_id:
            info = self._get_window_info(active_id)
            if info['title'] != self._current_title and info['title']:
                old_title = self._current_title
                self._current_title = info['title']
                self._record_title_change(active_id, old_title, info['title'])

        # Check for new/closed windows
        current_windows = self._get_all_windows()
        new_windows = current_windows - self._known_windows
        closed_windows = self._known_windows - current_windows

        for wid in new_windows:
            if wid:
                info = self._get_window_info(wid)
                self._record_open(wid, info)

        for wid in closed_windows:
            if wid:
                self._record_close(wid)

        self._known_windows = current_windows

        # Check geometry changes for active window
        if active_id:
            geo = self._get_window_geometry(active_id)
            if geo and active_id in self._window_geometries:
                old_geo = self._window_geometries[active_id]
                if (geo.get('WIDTH') != old_geo.get('WIDTH') or
                    geo.get('HEIGHT') != old_geo.get('HEIGHT')):
                    self._record_resize(active_id, old_geo, geo)
                elif (geo.get('X') != old_geo.get('X') or
                      geo.get('Y') != old_geo.get('Y')):
                    self._record_move(active_id, old_geo, geo)
            if geo:
                self._window_geometries[active_id] = geo

    def _record_focus(self, window_id, info):
        data = json.dumps({
            'window_id': window_id,
            'title': info['title'],
            'class': info['class'],
            'pid': info['pid'],
        }).encode('utf-8')
        self._record(1, data)  # WIN_FOCUS

    def _record_blur(self):
        data = json.dumps({
            'window_id': self._current_window_id,
            'title': self._current_title,
        }).encode('utf-8')
        self._record(2, data)  # WIN_BLUR

    def _record_open(self, window_id, info):
        data = json.dumps({
            'window_id': window_id,
            'title': info['title'],
            'class': info['class'],
            'pid': info['pid'],
        }).encode('utf-8')
        self._record(3, data)  # WIN_OPEN

    def _record_close(self, window_id):
        data = json.dumps({'window_id': window_id}).encode('utf-8')
        self._record(4, data)  # WIN_CLOSE
        self._window_geometries.pop(window_id, None)

    def _record_resize(self, window_id, old_geo, new_geo):
        data = json.dumps({
            'window_id': window_id,
            'old_w': old_geo.get('WIDTH', 0), 'old_h': old_geo.get('HEIGHT', 0),
            'new_w': new_geo.get('WIDTH', 0), 'new_h': new_geo.get('HEIGHT', 0),
        }).encode('utf-8')
        self._record(5, data)  # WIN_RESIZE

    def _record_move(self, window_id, old_geo, new_geo):
        data = json.dumps({
            'window_id': window_id,
            'old_x': old_geo.get('X', 0), 'old_y': old_geo.get('Y', 0),
            'new_x': new_geo.get('X', 0), 'new_y': new_geo.get('Y', 0),
        }).encode('utf-8')
        self._record(6, data)  # WIN_MOVE

    def _record_title_change(self, window_id, old_title, new_title):
        data = json.dumps({
            'window_id': window_id,
            'old_title': old_title,
            'new_title': new_title,
        }).encode('utf-8')
        self._record(9, data)  # WIN_TITLE_CHANGE


# ═══════════════════════════════════════════
# Channel 7: CLIPBOARD
# ═══════════════════════════════════════════

class ClipboardChannel(BaseChannel):
    """
    Clipboard copy/paste tracking via xclip.

    Records:
    - CLIP_COPY (1): Content copied to clipboard (with source window)
    - CLIP_CUT (2): Content cut (detected via Ctrl+X preceding clipboard change)
    - CLIP_PASTE (3): Content pasted from clipboard (with destination window)
    - CLIP_CLEAR (4): Clipboard cleared
    """

    def __init__(self, client):
        super().__init__(client, 7, 'clipboard')
        self._last_content = None
        self._last_content_hash = None
        self._pending_cut = False
        self._cut_expire_time = 0

    def _get_clipboard(self):
        """Read current clipboard content via xclip."""
        try:
            result = subprocess.run(
                ['xclip', '-selection', 'clipboard', '-o'],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0:
                return result.stdout
        except Exception:
            pass
        return None

    def _get_active_window_title(self):
        """Get the title of the currently focused window."""
        try:
            result = subprocess.run(
                ['xdotool', 'getactivewindow', 'getwindowname'],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return 'unknown'

    def _content_hash(self, content):
        """Hash clipboard content for change detection."""
        if content is None:
            return None
        import hashlib
        return hashlib.sha256(content.encode('utf-8', errors='replace')).hexdigest()[:16]

    def mark_cut(self):
        """Called by keystroke channel when Ctrl+X is detected."""
        self._pending_cut = True
        self._cut_expire_time = time.time() + 1.0  # Cut flag expires after 1 second

    def _run(self):
        """Main clipboard monitoring loop — polls every 500ms."""
        print(f"[{self.name}] Polling clipboard changes (500ms interval)")

        # Initialize with current clipboard
        self._last_content = self._get_clipboard()
        self._last_content_hash = self._content_hash(self._last_content)

        while self.active:
            try:
                self._poll_cycle()
            except Exception as e:
                self.errors += 1
            time.sleep(0.5)

    def _poll_cycle(self):
        """Single poll — check if clipboard changed."""
        current = self._get_clipboard()
        current_hash = self._content_hash(current)

        if current_hash != self._last_content_hash:
            if current is None or current == '':
                # Clipboard cleared
                self._record_clear()
            else:
                window_title = self._get_active_window_title()
                content_len = len(current) if current else 0
                content_type = self._detect_content_type(current)

                # Check if this was a cut (Ctrl+X was pressed recently)
                if self._pending_cut and time.time() < self._cut_expire_time:
                    self._record_cut(current, window_title, content_len, content_type)
                    self._pending_cut = False
                else:
                    self._record_copy(current, window_title, content_len, content_type)

            self._last_content = current
            self._last_content_hash = current_hash

    def _detect_content_type(self, content):
        """Classify clipboard content type."""
        if not content:
            return 'empty'
        if content.startswith(('http://', 'https://', 'ftp://')):
            return 'url'
        if content.startswith('/') or content.startswith('~'):
            return 'path'
        if '\n' in content and len(content) > 100:
            return 'multiline'
        if any(c in content for c in ['{', '}', '()', 'def ', 'class ', 'import ', 'function']):
            return 'code'
        return 'text'

    def _record_copy(self, content, window_title, content_len, content_type):
        data = json.dumps({
            'content': content[:1000],  # Cap at 1KB
            'length': content_len,
            'type': content_type,
            'source_window': window_title,
        }).encode('utf-8')
        self._record(1, data)  # CLIP_COPY

    def _record_cut(self, content, window_title, content_len, content_type):
        data = json.dumps({
            'content': content[:1000],
            'length': content_len,
            'type': content_type,
            'source_window': window_title,
        }).encode('utf-8')
        self._record(2, data)  # CLIP_CUT

    def _record_paste(self, window_title):
        """Record a paste event. Called externally when Ctrl+V detected."""
        data = json.dumps({
            'content_hash': self._last_content_hash,
            'length': len(self._last_content) if self._last_content else 0,
            'dest_window': window_title,
        }).encode('utf-8')
        self._record(3, data)  # CLIP_PASTE

    def _record_clear(self):
        data = json.dumps({'cleared': True}).encode('utf-8')
        self._record(4, data)  # CLIP_CLEAR
