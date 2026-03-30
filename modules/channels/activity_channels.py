"""Activity behavioral collection channels — Web, File, Message, AppLifecycle."""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

from modules.channels.base_channel import BaseChannel

try:
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    HAS_DBUS = True
except ImportError:
    HAS_DBUS = False

try:
    from gi.repository import GLib
    HAS_GLIB = True
except ImportError:
    HAS_GLIB = False


# ═══════════════════════════════════════════
# Channel 4: WEB
# ═══════════════════════════════════════════

class WebChannel(BaseChannel):
    """
    Web browsing activity via Chromium/Firefox SQLite history polling.

    Records:
    - WEB_URL_VISIT (1): New URL loaded (full URL, title, visit count)
    - WEB_SEARCH (2): Search query submitted (extracted from URL)
    - WEB_TAB_OPEN (3): New tab detected
    - WEB_TAB_CLOSE (4): Tab closed
    - WEB_TAB_SWITCH (5): Active tab changed
    - WEB_SCROLL_DEPTH (6): Scroll depth checkpoint
    - WEB_FORM_SUBMIT (7): Form submission detected
    - WEB_DOWNLOAD (8): Download initiated
    - WEB_PAGE_RELOAD (9): Page reload (same URL visited again within 10s)
    - WEB_BACK (10): Back navigation
    - WEB_FORWARD (11): Forward navigation
    - WEB_BOOKMARK (12): Bookmark action
    """

    # Search engine URL patterns → query parameter
    SEARCH_PATTERNS = {
        r'google\.\w+/search': 'q',
        r'bing\.com/search': 'q',
        r'duckduckgo\.com/': 'q',
        r'search\.yahoo\.com/search': 'p',
        r'startpage\.com/do/search': 'query',
        r'searx': 'q',
        r'brave\.com/search': 'q',
    }

    def __init__(self, client):
        super().__init__(client, 4, 'web')
        self._chromium_history = None
        self._firefox_history = None
        self._last_visit_id_chromium = 0
        self._last_visit_id_firefox = 0
        self._recent_urls = {}  # url → last_visit_timestamp (for reload detection)
        self._poll_interval = 2.0  # seconds

    def _find_chromium_history(self):
        """Find Chromium/Chrome history database."""
        candidates = [
            Path.home() / '.config' / 'chromium' / 'Default' / 'History',
            Path.home() / '.config' / 'google-chrome' / 'Default' / 'History',
            Path.home() / 'snap' / 'chromium' / 'common' / 'chromium' / 'Default' / 'History',
        ]
        for p in candidates:
            if p.exists():
                return p
        return None

    def _find_firefox_history(self):
        """Find Firefox history database."""
        firefox_dir = Path.home() / '.mozilla' / 'firefox'
        if not firefox_dir.exists():
            return None
        for profile in firefox_dir.iterdir():
            if profile.is_dir() and '.default' in profile.name:
                places = profile / 'places.sqlite'
                if places.exists():
                    return places
        return None

    def _safe_read_db(self, db_path, query, params=()):
        """
        Safely read a browser SQLite database.
        Copies to temp file first to avoid locking issues with the browser.
        """
        try:
            tmp = tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False)
            tmp.close()
            shutil.copy2(str(db_path), tmp.name)

            conn = sqlite3.connect(f'file:{tmp.name}?mode=ro', uri=True)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            conn.close()
            os.unlink(tmp.name)
            return rows
        except Exception:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
            return []

    def _extract_search_query(self, url):
        """Extract search query from a search engine URL."""
        from urllib.parse import urlparse, parse_qs
        for pattern, param in self.SEARCH_PATTERNS.items():
            if re.search(pattern, url):
                parsed = urlparse(url)
                qs = parse_qs(parsed.query)
                if param in qs:
                    return qs[param][0]
        return None

    def _run(self):
        """Main web history polling loop."""
        self._chromium_history = self._find_chromium_history()
        self._firefox_history = self._find_firefox_history()

        if not self._chromium_history and not self._firefox_history:
            print(f"[{self.name}] No browser history database found")
            return

        sources = []
        if self._chromium_history:
            sources.append(f"Chromium ({self._chromium_history})")
            self._init_chromium_baseline()
        if self._firefox_history:
            sources.append(f"Firefox ({self._firefox_history})")
            self._init_firefox_baseline()

        print(f"[{self.name}] Monitoring: {', '.join(sources)}")

        while self.active:
            try:
                if self._chromium_history:
                    self._poll_chromium()
                if self._firefox_history:
                    self._poll_firefox()
                self._expire_recent_urls()
            except Exception as e:
                self.errors += 1
            time.sleep(self._poll_interval)

    def _init_chromium_baseline(self):
        """Get the latest visit ID from Chromium to avoid replaying history."""
        rows = self._safe_read_db(
            self._chromium_history,
            "SELECT MAX(id) as max_id FROM visits"
        )
        if rows and rows[0]['max_id']:
            self._last_visit_id_chromium = rows[0]['max_id']

    def _init_firefox_baseline(self):
        """Get the latest visit ID from Firefox."""
        rows = self._safe_read_db(
            self._firefox_history,
            "SELECT MAX(id) as max_id FROM moz_historyvisits"
        )
        if rows and rows[0]['max_id']:
            self._last_visit_id_firefox = rows[0]['max_id']

    def _poll_chromium(self):
        """Poll for new Chromium history entries."""
        rows = self._safe_read_db(
            self._chromium_history,
            """SELECT v.id, u.url, u.title, v.visit_time, v.transition
               FROM visits v JOIN urls u ON v.url = u.id
               WHERE v.id > ?
               ORDER BY v.id ASC LIMIT 50""",
            (self._last_visit_id_chromium,)
        )
        for row in rows:
            self._process_visit(
                row['url'], row['title'] or '',
                row['id'], 'chromium',
                row['transition'] if 'transition' in row.keys() else 0
            )
            self._last_visit_id_chromium = row['id']

    def _poll_firefox(self):
        """Poll for new Firefox history entries."""
        rows = self._safe_read_db(
            self._firefox_history,
            """SELECT v.id, p.url, p.title, v.visit_date, v.visit_type
               FROM moz_historyvisits v JOIN moz_places p ON v.place_id = p.id
               WHERE v.id > ?
               ORDER BY v.id ASC LIMIT 50""",
            (self._last_visit_id_firefox,)
        )
        for row in rows:
            self._process_visit(
                row['url'], row['title'] or '',
                row['id'], 'firefox',
                row['visit_type'] if 'visit_type' in row.keys() else 0
            )
            self._last_visit_id_firefox = row['id']

    def _process_visit(self, url, title, visit_id, browser, transition):
        """Process a single browser visit."""
        now = time.time()

        # Reload detection: same URL visited within 10 seconds
        if url in self._recent_urls:
            if now - self._recent_urls[url] < 10.0:
                self._record_reload(url, title)
                self._recent_urls[url] = now
                return

        self._recent_urls[url] = now

        # Search query detection
        query = self._extract_search_query(url)
        if query:
            self._record_search(url, query, browser)

        # Regular URL visit
        self._record_url_visit(url, title, browser, transition)

    def _expire_recent_urls(self):
        """Remove URLs older than 30 seconds from reload tracking."""
        now = time.time()
        expired = [u for u, t in self._recent_urls.items() if now - t > 30]
        for u in expired:
            del self._recent_urls[u]

    def _record_url_visit(self, url, title, browser, transition):
        data = json.dumps({
            'url': url[:2000],
            'title': title[:500],
            'browser': browser,
            'transition': transition,
        }).encode('utf-8')
        self._record(1, data)  # WEB_URL_VISIT

    def _record_search(self, url, query, browser):
        data = json.dumps({
            'query': query[:500],
            'engine_url': url[:500],
            'browser': browser,
        }).encode('utf-8')
        self._record(2, data)  # WEB_SEARCH

    def _record_reload(self, url, title):
        data = json.dumps({
            'url': url[:2000],
            'title': title[:500],
        }).encode('utf-8')
        self._record(9, data)  # WEB_PAGE_RELOAD


# ═══════════════════════════════════════════
# Channel 5: MESSAGE (via D-Bus notifications)
# ═══════════════════════════════════════════

class MessageChannel(BaseChannel):
    """
    Desktop notification capture via D-Bus.

    Captures notifications from all apps (Slack, Discord, email clients,
    chat apps, system alerts) through the freedesktop notification spec.

    Records:
    - MSG_SENT (1): Outgoing message detected (via app-specific heuristics)
    - MSG_RECEIVED (2): Incoming notification with content
    - MSG_READ (3): Notification dismissed/clicked (user acknowledged)
    - MSG_TYPING_START (4): Typing indicator (from keystroke channel cross-ref)
    - MSG_TYPING_STOP (5): Typing stopped
    - MSG_DELETE (6): Message deleted
    - MSG_REACTION (7): Emoji reaction
    - MSG_CALL_START (8): Call started (detected via notification)
    - MSG_CALL_END (9): Call ended
    """

    # Apps that send messaging-related notifications
    MESSAGING_APPS = {
        'discord', 'slack', 'telegram', 'signal', 'whatsapp',
        'thunderbird', 'evolution', 'geary', 'kmail',
        'element', 'nheko', 'fractal',
        'pidgin', 'hexchat', 'irssi',
    }

    CALL_KEYWORDS = ['incoming call', 'calling', 'video call', 'voice call', 'ringing']

    def __init__(self, client):
        super().__init__(client, 5, 'message')
        self._notification_count = 0

    def _run(self):
        """Main D-Bus notification listener."""
        if not HAS_DBUS or not HAS_GLIB:
            print(f"[{self.name}] D-Bus or GLib not available — falling back to polling")
            self._run_fallback()
            return

        DBusGMainLoop(set_as_default=True)
        bus = dbus.SessionBus()

        bus.add_match_string(
            "type='method_call',"
            "interface='org.freedesktop.Notifications',"
            "member='Notify'"
        )
        bus.add_message_filter(self._notification_filter)

        print(f"[{self.name}] Listening on D-Bus for notifications")

        loop = GLib.MainLoop()
        import threading
        loop_thread = threading.Thread(target=loop.run, daemon=True)
        loop_thread.start()

        while self.active:
            time.sleep(1.0)

        loop.quit()

    def _notification_filter(self, bus, message):
        """Filter D-Bus messages for notifications."""
        try:
            args = message.get_args_list()
            if len(args) < 5:
                return

            app_name = str(args[0]) if args[0] else 'unknown'
            replaces_id = int(args[1]) if args[1] else 0
            icon = str(args[2]) if args[2] else ''
            summary = str(args[3]) if args[3] else ''
            body = str(args[4]) if args[4] else ''

            app_lower = app_name.lower()

            # Check for call-related notifications
            text_lower = (summary + ' ' + body).lower()
            if any(kw in text_lower for kw in self.CALL_KEYWORDS):
                self._record_call_start(app_name, summary, body)
                return

            # Determine if this is a messaging app
            is_messaging = any(ma in app_lower for ma in self.MESSAGING_APPS)

            if is_messaging:
                self._record_message_received(app_name, summary, body, icon)
            else:
                # Non-messaging notification — still record as received
                self._record_message_received(app_name, summary, body, icon)

            self._notification_count += 1

        except Exception as e:
            self.errors += 1

    def _run_fallback(self):
        """Fallback: monitor notification log files if D-Bus unavailable."""
        print(f"[{self.name}] Using notification log fallback (limited capture)")
        while self.active:
            # Check dunst history or similar
            try:
                result = subprocess.run(
                    ['dunstctl', 'history'],
                    capture_output=True, text=True, timeout=3,
                )
                if result.returncode == 0:
                    try:
                        history = json.loads(result.stdout)
                        for item in history.get('data', [[]])[0]:
                            summary = item.get('summary', {}).get('data', '')
                            body = item.get('body', {}).get('data', '')
                            app = item.get('appname', {}).get('data', 'unknown')
                            if summary:
                                self._record_message_received(app, summary, body, '')
                    except json.JSONDecodeError:
                        pass
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
            time.sleep(5.0)

    def _record_message_received(self, app_name, summary, body, icon):
        data = json.dumps({
            'app': app_name,
            'summary': summary[:500],
            'body': body[:1000],
            'icon': icon[:200],
        }).encode('utf-8')
        self._record(2, data)  # MSG_RECEIVED

    def _record_call_start(self, app_name, summary, body):
        data = json.dumps({
            'app': app_name,
            'summary': summary[:500],
            'body': body[:500],
        }).encode('utf-8')
        self._record(8, data)  # MSG_CALL_START

    def record_message_sent(self, app_name, window_title):
        """Called externally when a message send is detected (e.g. Enter in messaging app)."""
        data = json.dumps({
            'app': app_name,
            'window': window_title[:500],
        }).encode('utf-8')
        self._record(1, data)  # MSG_SENT

    def record_message_read(self, app_name, notification_id=0):
        """Called when a notification is dismissed/clicked."""
        data = json.dumps({
            'app': app_name,
            'notification_id': notification_id,
        }).encode('utf-8')
        self._record(3, data)  # MSG_READ


# ═══════════════════════════════════════════
# Channel 6: FILE
# ═══════════════════════════════════════════

class FileChannel(BaseChannel):
    """
    File system activity monitoring via inotifywait.

    Watches the user's home directory tree for file operations.

    Records:
    - FILE_OPEN (1): File opened (detected via access events)
    - FILE_CLOSE (2): File closed after writing
    - FILE_SAVE (3): File modified (write completed)
    - FILE_CREATE (4): New file created
    - FILE_DELETE (5): File deleted
    - FILE_RENAME (6): File renamed (moved_from + moved_to)
    - FILE_MOVE (7): File moved between directories
    - FILE_COPY (8): File copied (create + same content heuristic)
    - FILE_DOWNLOAD (9): File appeared in Downloads directory
    - FILE_UPLOAD (10): File read from common upload paths
    - FILE_PERMISSION (11): Permission change detected
    """

    # Directories to exclude (noisy, not behavioral)
    EXCLUDE_PATTERNS = [
        r'\.cache', r'\.local/share/Trash', r'\.mozilla/.*/cache',
        r'\.config/chromium/.*/Cache', r'\.config/google-chrome/.*/Cache',
        r'node_modules', r'__pycache__', r'\.git/objects',
        r'\.thumbnails', r'\.dbus', r'/proc', r'/sys', r'/tmp',
    ]

    def __init__(self, client):
        super().__init__(client, 6, 'file')
        self._process = None
        self._pending_move_from = None
        self._pending_move_time = 0
        self._downloads_dir = str(Path.home() / 'Downloads')

    def _build_exclude_regex(self):
        """Build regex for inotifywait --exclude."""
        return '|'.join(f'({p})' for p in self.EXCLUDE_PATTERNS)

    def _run(self):
        """Main file monitoring loop via inotifywait."""
        watch_dir = str(Path.home())
        exclude = self._build_exclude_regex()

        cmd = [
            'inotifywait', '-m', '-r',
            '--format', '%w%f\t%e\t%T',
            '--timefmt', '%s',
            '--exclude', exclude,
            '-e', 'create,delete,modify,close_write,moved_from,moved_to,attrib,access',
            watch_dir,
        ]

        try:
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
            )
        except FileNotFoundError:
            print(f"[{self.name}] inotifywait not found — install inotify-tools")
            return

        print(f"[{self.name}] Watching: {watch_dir}")

        for line in self._process.stdout:
            if not self.active:
                break

            line = line.strip()
            if not line:
                continue

            try:
                self._process_event(line)
            except Exception as e:
                self.errors += 1
                if self.errors <= 3 or self.errors % 100 == 0:
                    print(f"[{self.name}] Event error #{self.errors}: {type(e).__name__}: {e}")

        if self._process:
            self._process.terminate()

    def stop(self):
        """Override stop to kill inotifywait subprocess."""
        self.active = False
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
        super().stop()

    def _process_event(self, line):
        """Process a single inotifywait event line."""
        parts = line.split('\t')
        if len(parts) < 2:
            return

        filepath = parts[0]
        events = parts[1].split(',')
        timestamp = int(parts[2]) if len(parts) > 2 else int(time.time())

        filename = os.path.basename(filepath)
        directory = os.path.dirname(filepath)
        extension = os.path.splitext(filename)[1].lower()

        for event in events:
            event = event.strip()

            if event == 'CREATE':
                # Check if it's a download
                if directory.startswith(self._downloads_dir):
                    self._record_download(filepath, filename, extension)
                else:
                    self._record_create(filepath, filename, extension)

            elif event == 'DELETE':
                self._record_delete(filepath, filename, extension)

            elif event == 'CLOSE_WRITE' or event == 'MODIFY':
                self._record_save(filepath, filename, extension)

            elif event == 'MOVED_FROM':
                self._pending_move_from = filepath
                self._pending_move_time = time.time()

            elif event == 'MOVED_TO':
                if self._pending_move_from and time.time() - self._pending_move_time < 1.0:
                    old_dir = os.path.dirname(self._pending_move_from)
                    new_dir = os.path.dirname(filepath)
                    if old_dir == new_dir:
                        # Same directory = rename
                        self._record_rename(self._pending_move_from, filepath, filename)
                    else:
                        # Different directory = move
                        self._record_move(self._pending_move_from, filepath, filename)
                    self._pending_move_from = None
                else:
                    # No matching MOVED_FROM — treat as create
                    self._record_create(filepath, filename, extension)

            elif event == 'ACCESS':
                self._record_open(filepath, filename, extension)

            elif event == 'ATTRIB':
                self._record_permission(filepath, filename)

    def _record_open(self, filepath, filename, extension):
        data = json.dumps({
            'path': filepath[:1000],
            'filename': filename,
            'extension': extension,
        }).encode('utf-8')
        self._record(1, data)  # FILE_OPEN

    def _record_save(self, filepath, filename, extension):
        try:
            size = os.path.getsize(filepath)
        except OSError:
            size = 0
        data = json.dumps({
            'path': filepath[:1000],
            'filename': filename,
            'extension': extension,
            'size': size,
        }).encode('utf-8')
        self._record(3, data)  # FILE_SAVE

    def _record_create(self, filepath, filename, extension):
        data = json.dumps({
            'path': filepath[:1000],
            'filename': filename,
            'extension': extension,
        }).encode('utf-8')
        self._record(4, data)  # FILE_CREATE

    def _record_delete(self, filepath, filename, extension):
        data = json.dumps({
            'path': filepath[:1000],
            'filename': filename,
            'extension': extension,
        }).encode('utf-8')
        self._record(5, data)  # FILE_DELETE

    def _record_rename(self, old_path, new_path, filename):
        data = json.dumps({
            'old_path': old_path[:1000],
            'new_path': new_path[:1000],
            'filename': filename,
        }).encode('utf-8')
        self._record(6, data)  # FILE_RENAME

    def _record_move(self, old_path, new_path, filename):
        data = json.dumps({
            'old_path': old_path[:1000],
            'new_path': new_path[:1000],
            'filename': filename,
        }).encode('utf-8')
        self._record(7, data)  # FILE_MOVE

    def _record_download(self, filepath, filename, extension):
        try:
            size = os.path.getsize(filepath)
        except OSError:
            size = 0
        data = json.dumps({
            'path': filepath[:1000],
            'filename': filename,
            'extension': extension,
            'size': size,
        }).encode('utf-8')
        self._record(9, data)  # FILE_DOWNLOAD

    def _record_permission(self, filepath, filename):
        try:
            stat = os.stat(filepath)
            mode = oct(stat.st_mode)[-3:]
        except OSError:
            mode = '???'
        data = json.dumps({
            'path': filepath[:1000],
            'filename': filename,
            'mode': mode,
        }).encode('utf-8')
        self._record(11, data)  # FILE_PERMISSION


# ═══════════════════════════════════════════
# Channel 10: APP LIFECYCLE
# ═══════════════════════════════════════════

class AppLifecycleChannel(BaseChannel):
    """
    Application start/exit monitoring via /proc polling.

    Records:
    - APP_LAUNCH (1): New process detected (name, PID, cmdline)
    - APP_EXIT (2): Process exited (name, PID, runtime)
    - APP_CRASH (3): Process exited with non-zero (detected via disappearance pattern)
    - APP_INSTALL (4): New package installed (dpkg log monitoring)
    - APP_UNINSTALL (5): Package removed
    - APP_UPDATE (6): Package updated
    """

    # Only track "interesting" processes (not kernel threads, system daemons)
    IGNORE_PREFIXES = {
        'kworker', 'ksoftirqd', 'migration', 'watchdog', 'cpuhp',
        'rcu_', 'mm_', 'writeback', 'kcompactd', 'khugepaged',
        'kdevtmpfs', 'netns', 'kauditd', 'kswapd', 'ecryptfs',
    }

    # Track these apps specifically (GUI/user apps)
    INTERESTING_APPS = {
        'chromium', 'chrome', 'firefox', 'code', 'vim', 'nano', 'emacs',
        'gimp', 'inkscape', 'libreoffice', 'thunderbird', 'evolution',
        'vlc', 'mpv', 'spotify', 'discord', 'slack', 'telegram',
        'nautilus', 'thunar', 'dolphin', 'terminal', 'alacritty',
        'kitty', 'gnome-terminal', 'konsole', 'xterm',
        'python', 'python3', 'node', 'java', 'cargo', 'go', 'rustc',
        'gcc', 'g++', 'make', 'cmake', 'npm', 'pip',
        'ssh', 'scp', 'rsync', 'wget', 'curl',
    }

    def __init__(self, client):
        super().__init__(client, 10, 'app_lifecycle')
        self._known_pids = {}  # pid → {'name': str, 'cmdline': str, 'start_time': float}
        self._poll_interval = 2.0
        self._dpkg_log_pos = 0

    def _get_process_info(self, pid):
        """Read process info from /proc."""
        try:
            proc_dir = Path(f'/proc/{pid}')
            if not proc_dir.exists():
                return None

            # Process name
            comm_path = proc_dir / 'comm'
            name = comm_path.read_text().strip() if comm_path.exists() else ''

            # Command line
            cmdline_path = proc_dir / 'cmdline'
            if cmdline_path.exists():
                raw = cmdline_path.read_bytes()
                cmdline = raw.replace(b'\x00', b' ').decode('utf-8', errors='replace').strip()
            else:
                cmdline = name

            # Start time (from /proc/[pid]/stat field 22)
            stat_path = proc_dir / 'stat'
            start_time = 0
            if stat_path.exists():
                try:
                    stat_content = stat_path.read_text()
                    # Find the closing paren to handle comm fields with spaces
                    close_paren = stat_content.rfind(')')
                    if close_paren > 0:
                        fields = stat_content[close_paren+2:].split()
                        if len(fields) >= 20:
                            start_time = int(fields[19])
                except Exception:
                    pass

            return {
                'name': name,
                'cmdline': cmdline[:500],
                'start_time': start_time,
            }
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            return None

    def _is_interesting(self, name):
        """Check if this process is worth tracking."""
        if not name:
            return False
        name_lower = name.lower()

        # Skip kernel threads
        for prefix in self.IGNORE_PREFIXES:
            if name_lower.startswith(prefix):
                return False

        # Always track known interesting apps
        for app in self.INTERESTING_APPS:
            if app in name_lower:
                return True

        # Track any process that has a terminal or X11 connection
        # (heuristic: if it's in the user's session, it's likely interactive)
        return True

    def _scan_processes(self):
        """Scan /proc for current process list."""
        current = {}
        try:
            for entry in os.listdir('/proc'):
                if entry.isdigit():
                    pid = int(entry)
                    info = self._get_process_info(pid)
                    if info and self._is_interesting(info['name']):
                        current[pid] = info
        except Exception:
            pass
        return current

    def _run(self):
        """Main process monitoring loop."""
        print(f"[{self.name}] Scanning /proc every {self._poll_interval}s")

        # Initialize baseline
        self._known_pids = self._scan_processes()
        self._init_dpkg_log()

        while self.active:
            try:
                self._poll_cycle()
            except Exception as e:
                self.errors += 1
                if self.errors <= 3 or self.errors % 100 == 0:
                    print(f"[{self.name}] Poll error #{self.errors}: {type(e).__name__}: {e}")
            try:
                self._check_dpkg_log()
            except Exception as e:
                self.errors += 1
                if self.errors <= 3 or self.errors % 100 == 0:
                    print(f"[{self.name}] dpkg check error #{self.errors}: {type(e).__name__}: {e}")
            time.sleep(self._poll_interval)

    def _poll_cycle(self):
        """Single poll — detect new and exited processes."""
        current = self._scan_processes()
        current_set = set(current.keys())
        known_set = set(self._known_pids.keys())

        # New processes
        for pid in current_set - known_set:
            info = current[pid]
            try:
                self._record_launch(pid, info)
            except Exception as e:
                self.errors += 1
                if self.errors <= 3 or self.errors % 100 == 0:
                    print(f"[{self.name}] Launch record error #{self.errors} (pid {pid}): {type(e).__name__}: {e}")

        # Exited processes
        for pid in known_set - current_set:
            info = self._known_pids[pid]
            runtime = time.time() - info.get('tracked_since', time.time())
            try:
                self._record_exit(pid, info, runtime)
            except Exception as e:
                self.errors += 1
                if self.errors <= 3 or self.errors % 100 == 0:
                    print(f"[{self.name}] Exit record error #{self.errors} (pid {pid}): {type(e).__name__}: {e}")

        # Update known pids
        for pid in current_set - known_set:
            current[pid]['tracked_since'] = time.time()
        self._known_pids = current

    def _init_dpkg_log(self):
        """Initialize dpkg log position for package install tracking."""
        dpkg_log = Path('/var/log/dpkg.log')
        if dpkg_log.exists():
            self._dpkg_log_pos = dpkg_log.stat().st_size

    def _check_dpkg_log(self):
        """Check dpkg log for new package installs/removes/upgrades."""
        dpkg_log = Path('/var/log/dpkg.log')
        if not dpkg_log.exists():
            return

        current_size = dpkg_log.stat().st_size
        if current_size <= self._dpkg_log_pos:
            return

        try:
            with open(dpkg_log, 'r') as f:
                f.seek(self._dpkg_log_pos)
                new_lines = f.readlines()
            self._dpkg_log_pos = current_size

            for line in new_lines:
                line = line.strip()
                if ' install ' in line:
                    parts = line.split()
                    if len(parts) >= 4:
                        self._record_install(parts[3], parts[4] if len(parts) > 4 else '')
                elif ' remove ' in line:
                    parts = line.split()
                    if len(parts) >= 4:
                        self._record_uninstall(parts[3])
                elif ' upgrade ' in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        self._record_update(parts[3], parts[4] if len(parts) > 4 else '')
        except Exception:
            pass

    def _record_launch(self, pid, info):
        data = json.dumps({
            'pid': pid,
            'name': info['name'],
            'cmdline': info['cmdline'],
        }).encode('utf-8')
        self._record(1, data)  # APP_LAUNCH

    def _record_exit(self, pid, info, runtime):
        data = json.dumps({
            'pid': pid,
            'name': info['name'],
            'runtime_s': round(runtime, 1),
        }).encode('utf-8')
        self._record(2, data)  # APP_EXIT

    def _record_install(self, package, version):
        data = json.dumps({
            'package': package,
            'version': version,
        }).encode('utf-8')
        self._record(4, data)  # APP_INSTALL

    def _record_uninstall(self, package):
        data = json.dumps({'package': package}).encode('utf-8')
        self._record(5, data)  # APP_UNINSTALL

    def _record_update(self, package, version):
        data = json.dumps({
            'package': package,
            'version': version,
        }).encode('utf-8')
        self._record(6, data)  # APP_UPDATE
