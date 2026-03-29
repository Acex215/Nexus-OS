"""Hardware behavioral collection channels — Audio, Display, Power, Peripheral, Notification."""

import json
import os
import re
import subprocess
import time
from pathlib import Path

from modules.channels.base_channel import BaseChannel


# ═══════════════════════════════════════════
# Channel 14: AUDIO
# ═══════════════════════════════════════════

class AudioChannel(BaseChannel):
    """
    Audio state monitoring via PulseAudio/PipeWire (pactl).

    Records:
    - AUDIO_VOLUME_UP (1): Volume increased
    - AUDIO_VOLUME_DOWN (2): Volume decreased
    - AUDIO_MUTE (3): Audio muted
    - AUDIO_UNMUTE (4): Audio unmuted
    - AUDIO_OUTPUT_CHANGE (5): Output device changed (speaker → headphones etc)
    - AUDIO_PLAYBACK_START (6): Audio playback started
    - AUDIO_PLAYBACK_STOP (7): Audio playback stopped
    """

    def __init__(self, client):
        super().__init__(client, 14, 'audio')
        self._prev_volume = None
        self._prev_mute = None
        self._prev_sink_name = None
        self._prev_playing = False
        self._poll_interval = 2.0

    def _get_default_sink(self):
        """Get the default audio sink name."""
        try:
            result = subprocess.run(
                ['pactl', 'get-default-sink'],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    def _get_sink_info(self, sink_name):
        """Get volume and mute state for a sink."""
        try:
            result = subprocess.run(
                ['pactl', 'list', 'sinks'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return None

            info = {'volume': None, 'mute': None, 'description': '', 'name': sink_name}
            in_target = False

            for line in result.stdout.split('\n'):
                line = line.strip()

                if line.startswith('Name:'):
                    in_target = line.split(':', 1)[1].strip() == sink_name

                if not in_target:
                    continue

                if line.startswith('Description:'):
                    info['description'] = line.split(':', 1)[1].strip()

                elif line.startswith('Mute:'):
                    info['mute'] = 'yes' in line.lower()

                elif line.startswith('Volume:'):
                    match = re.search(r'(\d+)%', line)
                    if match:
                        info['volume'] = int(match.group(1))

            return info if info['volume'] is not None else None

        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    def _get_playback_active(self):
        """Check if any audio stream is currently playing."""
        try:
            result = subprocess.run(
                ['pactl', 'list', 'sink-inputs', 'short'],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
                return len(lines) > 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return False

    def _run(self):
        """Main audio monitoring loop."""
        sink = self._get_default_sink()
        if not sink:
            print(f"[{self.name}] No PulseAudio/PipeWire sink found")
            return

        print(f"[{self.name}] Monitoring sink: {sink} (polling every {self._poll_interval}s)")

        # Initialize baseline
        info = self._get_sink_info(sink)
        if info:
            self._prev_volume = info['volume']
            self._prev_mute = info['mute']
            self._prev_sink_name = sink
        self._prev_playing = self._get_playback_active()

        while self.active:
            try:
                # Check if default sink changed
                current_sink = self._get_default_sink()
                if current_sink and current_sink != self._prev_sink_name:
                    new_info = self._get_sink_info(current_sink)
                    if new_info:
                        self._record_output_change(self._prev_sink_name, current_sink,
                                                   new_info.get('description', ''))
                        self._prev_sink_name = current_sink
                        self._prev_volume = new_info['volume']
                        self._prev_mute = new_info['mute']
                        sink = current_sink

                info = self._get_sink_info(sink)
                if info:
                    # Volume change
                    if self._prev_volume is not None and info['volume'] != self._prev_volume:
                        if info['volume'] > self._prev_volume:
                            self._record_volume_up(self._prev_volume, info['volume'])
                        else:
                            self._record_volume_down(self._prev_volume, info['volume'])
                        self._prev_volume = info['volume']

                    # Mute change
                    if self._prev_mute is not None and info['mute'] != self._prev_mute:
                        if info['mute']:
                            self._record_mute()
                        else:
                            self._record_unmute(info['volume'])
                        self._prev_mute = info['mute']

                # Playback state
                playing = self._get_playback_active()
                if playing and not self._prev_playing:
                    self._record_playback_start()
                elif not playing and self._prev_playing:
                    self._record_playback_stop()
                self._prev_playing = playing

            except Exception as e:
                self.errors += 1
            time.sleep(self._poll_interval)

    def _record_volume_up(self, old, new):
        data = json.dumps({'old_volume': old, 'new_volume': new}).encode('utf-8')
        self._record(1, data)

    def _record_volume_down(self, old, new):
        data = json.dumps({'old_volume': old, 'new_volume': new}).encode('utf-8')
        self._record(2, data)

    def _record_mute(self):
        data = json.dumps({'muted': True}).encode('utf-8')
        self._record(3, data)

    def _record_unmute(self, volume):
        data = json.dumps({'muted': False, 'volume': volume}).encode('utf-8')
        self._record(4, data)

    def _record_output_change(self, old_sink, new_sink, description):
        data = json.dumps({
            'old_sink': old_sink or '',
            'new_sink': new_sink,
            'description': description,
        }).encode('utf-8')
        self._record(5, data)

    def _record_playback_start(self):
        data = json.dumps({'playing': True}).encode('utf-8')
        self._record(6, data)

    def _record_playback_stop(self):
        data = json.dumps({'playing': False}).encode('utf-8')
        self._record(7, data)


# ═══════════════════════════════════════════
# Channel 15: DISPLAY
# ═══════════════════════════════════════════

class DisplayChannel(BaseChannel):
    """
    Display state monitoring via sysfs backlight + xrandr.

    Records:
    - DISP_BRIGHTNESS_UP (1): Brightness increased
    - DISP_BRIGHTNESS_DOWN (2): Brightness decreased
    - DISP_RESOLUTION_CHANGE (3): Resolution changed
    - DISP_MONITOR_CONNECT (4): External monitor connected
    - DISP_MONITOR_DISCONNECT (5): External monitor disconnected
    - DISP_SCREENSHOT (6): Screenshot taken (detected via file creation)
    """

    def __init__(self, client):
        super().__init__(client, 15, 'display')
        self._prev_brightness = None
        self._prev_monitors = {}
        self._backlight_path = None
        self._max_brightness = 1
        self._poll_interval = 5.0

    def _find_backlight(self):
        """Find the backlight sysfs path."""
        backlight_base = Path('/sys/class/backlight')
        if not backlight_base.exists():
            return None
        for entry in backlight_base.iterdir():
            brightness_file = entry / 'brightness'
            if brightness_file.exists():
                return entry
        return None

    def _get_brightness(self):
        """Read current brightness as a percentage."""
        if not self._backlight_path:
            return None
        try:
            brightness = int((self._backlight_path / 'brightness').read_text().strip())
            return round(brightness / self._max_brightness * 100, 1)
        except Exception:
            return None

    def _get_monitors(self):
        """Get connected monitors and their resolutions via xrandr."""
        monitors = {}
        try:
            result = subprocess.run(
                ['xrandr', '--query'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return monitors

            current_output = None
            for line in result.stdout.split('\n'):
                # Output line: "HDMI-1 connected 1920x1080+0+0 ..."
                match = re.match(r'^(\S+)\s+(connected|disconnected)', line)
                if match:
                    name = match.group(1)
                    connected = match.group(2) == 'connected'
                    if connected:
                        current_output = name
                        # Extract resolution from the same line
                        res_match = re.search(r'(\d+x\d+)', line)
                        monitors[name] = {
                            'connected': True,
                            'resolution': res_match.group(1) if res_match else 'unknown',
                            'primary': 'primary' in line,
                        }
                    else:
                        current_output = None

                # Active resolution line (marked with *)
                elif current_output and '*' in line:
                    res_match = re.match(r'\s+(\d+x\d+)', line)
                    if res_match and current_output in monitors:
                        monitors[current_output]['resolution'] = res_match.group(1)

        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return monitors

    def _run(self):
        """Main display monitoring loop."""
        self._backlight_path = self._find_backlight()
        if self._backlight_path:
            try:
                self._max_brightness = int(
                    (self._backlight_path / 'max_brightness').read_text().strip()
                )
            except Exception:
                self._max_brightness = 255
            print(f"[{self.name}] Backlight: {self._backlight_path.name} (max={self._max_brightness})")
        else:
            print(f"[{self.name}] No backlight found — monitoring xrandr only")

        # Initialize baseline
        self._prev_brightness = self._get_brightness()
        self._prev_monitors = self._get_monitors()

        print(f"[{self.name}] Monitoring displays (polling every {self._poll_interval}s)")

        while self.active:
            try:
                # Brightness
                brightness = self._get_brightness()
                if brightness is not None and self._prev_brightness is not None:
                    if brightness != self._prev_brightness:
                        if brightness > self._prev_brightness:
                            self._record_brightness_up(self._prev_brightness, brightness)
                        else:
                            self._record_brightness_down(self._prev_brightness, brightness)
                        self._prev_brightness = brightness

                # Monitor changes
                monitors = self._get_monitors()
                current_names = set(monitors.keys())
                prev_names = set(self._prev_monitors.keys())

                for name in current_names - prev_names:
                    self._record_monitor_connect(name, monitors[name])

                for name in prev_names - current_names:
                    self._record_monitor_disconnect(name)

                # Resolution changes on existing monitors
                for name in current_names & prev_names:
                    if monitors[name]['resolution'] != self._prev_monitors[name]['resolution']:
                        self._record_resolution_change(
                            name,
                            self._prev_monitors[name]['resolution'],
                            monitors[name]['resolution']
                        )

                self._prev_monitors = monitors

            except Exception as e:
                self.errors += 1
            time.sleep(self._poll_interval)

    def _record_brightness_up(self, old, new):
        data = json.dumps({'old_pct': old, 'new_pct': new}).encode('utf-8')
        self._record(1, data)

    def _record_brightness_down(self, old, new):
        data = json.dumps({'old_pct': old, 'new_pct': new}).encode('utf-8')
        self._record(2, data)

    def _record_resolution_change(self, output, old_res, new_res):
        data = json.dumps({
            'output': output,
            'old_resolution': old_res,
            'new_resolution': new_res,
        }).encode('utf-8')
        self._record(3, data)

    def _record_monitor_connect(self, name, info):
        data = json.dumps({
            'output': name,
            'resolution': info.get('resolution', 'unknown'),
            'primary': info.get('primary', False),
        }).encode('utf-8')
        self._record(4, data)

    def _record_monitor_disconnect(self, name):
        data = json.dumps({'output': name}).encode('utf-8')
        self._record(5, data)

    def record_screenshot(self, path=''):
        """Called externally when a screenshot is detected."""
        data = json.dumps({'path': path[:500]}).encode('utf-8')
        self._record(6, data)


# ═══════════════════════════════════════════
# Channel 16: POWER
# ═══════════════════════════════════════════

class PowerChannel(BaseChannel):
    """
    Power state monitoring via /sys/class/power_supply.

    Records:
    - PWR_BATTERY_LEVEL (1): Battery percentage reading
    - PWR_CHARGING_START (2): Charger connected
    - PWR_CHARGING_STOP (3): Charger disconnected
    - PWR_SLEEP (4): System entering sleep
    - PWR_WAKE (5): System waking from sleep
    - PWR_SHUTDOWN_INIT (6): Shutdown initiated
    - PWR_REBOOT_INIT (7): Reboot initiated
    """

    POWER_SUPPLY_BASE = Path('/sys/class/power_supply')

    def __init__(self, client):
        super().__init__(client, 16, 'power')
        self._battery_path = None
        self._ac_path = None
        self._prev_status = None
        self._prev_capacity = None
        self._prev_uptime = None
        self._poll_interval = 30.0

    def _find_power_supply(self):
        """Find battery and AC adapter sysfs paths."""
        if not self.POWER_SUPPLY_BASE.exists():
            return

        for entry in self.POWER_SUPPLY_BASE.iterdir():
            try:
                supply_type = (entry / 'type').read_text().strip()
                if supply_type == 'Battery':
                    self._battery_path = entry
                elif supply_type in ('Mains', 'USB'):
                    self._ac_path = entry
            except Exception:
                pass

    def _get_battery_info(self):
        """Read battery status and capacity."""
        if not self._battery_path:
            return None

        info = {}
        try:
            status_file = self._battery_path / 'status'
            if status_file.exists():
                info['status'] = status_file.read_text().strip()

            capacity_file = self._battery_path / 'capacity'
            if capacity_file.exists():
                info['capacity'] = int(capacity_file.read_text().strip())

            voltage_file = self._battery_path / 'voltage_now'
            if voltage_file.exists():
                info['voltage_v'] = round(int(voltage_file.read_text().strip()) / 1000000, 3)

            current_file = self._battery_path / 'current_now'
            if current_file.exists():
                info['current_ma'] = round(int(current_file.read_text().strip()) / 1000, 1)

            energy_file = self._battery_path / 'energy_now'
            if energy_file.exists():
                info['energy_wh'] = round(int(energy_file.read_text().strip()) / 1000000, 3)

            power_file = self._battery_path / 'power_now'
            if power_file.exists():
                info['power_w'] = round(int(power_file.read_text().strip()) / 1000000, 3)

        except Exception:
            pass
        return info if info else None

    def _get_ac_online(self):
        """Check if AC adapter is connected."""
        if not self._ac_path:
            return None
        try:
            online_file = self._ac_path / 'online'
            if online_file.exists():
                return int(online_file.read_text().strip()) == 1
        except Exception:
            pass
        return None

    def _get_system_uptime(self):
        """Read system uptime for sleep/wake detection."""
        try:
            with open('/proc/uptime', 'r') as f:
                return float(f.read().split()[0])
        except Exception:
            return None

    def _run(self):
        """Main power monitoring loop."""
        self._find_power_supply()

        if self._battery_path:
            print(f"[{self.name}] Battery: {self._battery_path.name}")
        else:
            print(f"[{self.name}] No battery found — monitoring AC + sleep/wake only")

        if self._ac_path:
            print(f"[{self.name}] AC: {self._ac_path.name}")

        # Initialize baseline
        bat = self._get_battery_info()
        if bat:
            self._prev_status = bat.get('status')
            self._prev_capacity = bat.get('capacity')
        self._prev_uptime = self._get_system_uptime()

        while self.active:
            try:
                bat = self._get_battery_info()
                if bat:
                    # Battery level
                    capacity = bat.get('capacity')
                    if capacity is not None:
                        self._record_battery_level(bat)
                        self._prev_capacity = capacity

                    # Charging state change
                    status = bat.get('status')
                    if status and status != self._prev_status:
                        if status in ('Charging', 'Full'):
                            self._record_charging_start(bat)
                        elif status == 'Discharging' and self._prev_status in ('Charging', 'Full'):
                            self._record_charging_stop(bat)
                        self._prev_status = status

                # Sleep/wake detection via uptime gap
                uptime = self._get_system_uptime()
                if uptime is not None and self._prev_uptime is not None:
                    expected = self._prev_uptime + self._poll_interval
                    # If uptime advanced much less than poll interval, system was asleep
                    # If uptime advanced much more, we missed a cycle (also sleep/wake)
                    gap = uptime - self._prev_uptime
                    if gap < self._poll_interval * 0.3:
                        # Uptime barely moved — system was likely suspended
                        self._record_wake(gap)
                    elif gap > self._poll_interval * 3:
                        # Large gap — system was sleeping
                        sleep_duration = gap - self._poll_interval
                        self._record_sleep(sleep_duration)
                        self._record_wake(sleep_duration)
                self._prev_uptime = uptime

            except Exception as e:
                self.errors += 1
            time.sleep(self._poll_interval)

    def _record_battery_level(self, bat):
        data = json.dumps({
            'capacity_pct': bat.get('capacity'),
            'status': bat.get('status', ''),
            'voltage_v': bat.get('voltage_v'),
            'power_w': bat.get('power_w'),
        }).encode('utf-8')
        self._record(1, data)  # PWR_BATTERY_LEVEL

    def _record_charging_start(self, bat):
        data = json.dumps({
            'capacity_pct': bat.get('capacity'),
            'voltage_v': bat.get('voltage_v'),
        }).encode('utf-8')
        self._record(2, data)  # PWR_CHARGING_START

    def _record_charging_stop(self, bat):
        data = json.dumps({
            'capacity_pct': bat.get('capacity'),
            'voltage_v': bat.get('voltage_v'),
        }).encode('utf-8')
        self._record(3, data)  # PWR_CHARGING_STOP

    def _record_sleep(self, duration):
        data = json.dumps({'duration_s': round(duration, 1)}).encode('utf-8')
        self._record(4, data)  # PWR_SLEEP

    def _record_wake(self, sleep_duration):
        data = json.dumps({'sleep_duration_s': round(sleep_duration, 1)}).encode('utf-8')
        self._record(5, data)  # PWR_WAKE


# ═══════════════════════════════════════════
# Channel 17: PERIPHERAL
# ═══════════════════════════════════════════

class PeripheralChannel(BaseChannel):
    """
    USB and Bluetooth device connect/disconnect via udevadm monitor.

    Records:
    - PERIPH_USB_CONNECT (1): USB device plugged in
    - PERIPH_USB_DISCONNECT (2): USB device removed
    - PERIPH_BLUETOOTH_CONNECT (3): Bluetooth device connected
    - PERIPH_BLUETOOTH_DISCONNECT (4): Bluetooth device disconnected
    - PERIPH_PRINTER_JOB (5): Print job detected
    """

    def __init__(self, client):
        super().__init__(client, 17, 'peripheral')
        self._process = None
        self._known_usb = set()
        self._known_bt = set()

    def _get_usb_device_info(self, devpath):
        """Read USB device info from sysfs."""
        info = {}
        sysfs = Path(f'/sys{devpath}')
        try:
            for attr in ('idVendor', 'idProduct', 'manufacturer', 'product', 'serial'):
                attr_file = sysfs / attr
                if attr_file.exists():
                    info[attr] = attr_file.read_text().strip()
        except Exception:
            pass
        return info

    def _init_usb_baseline(self):
        """Get currently connected USB devices."""
        try:
            usb_base = Path('/sys/bus/usb/devices')
            if usb_base.exists():
                for dev in usb_base.iterdir():
                    product = dev / 'product'
                    if product.exists():
                        self._known_usb.add(dev.name)
        except Exception:
            pass

    def _init_bt_baseline(self):
        """Get currently connected Bluetooth devices."""
        try:
            result = subprocess.run(
                ['bluetoothctl', 'devices', 'Connected'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        parts = line.split()
                        if len(parts) >= 2:
                            self._known_bt.add(parts[1])
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    def _run(self):
        """Main peripheral monitoring via udevadm monitor."""
        self._init_usb_baseline()
        self._init_bt_baseline()

        cmd = [
            'udevadm', 'monitor',
            '--kernel', '--subsystem-match=usb', '--subsystem-match=bluetooth',
            '--property',
        ]

        try:
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
            )
        except FileNotFoundError:
            print(f"[{self.name}] udevadm not found — falling back to polling")
            self._run_polling_fallback()
            return

        print(f"[{self.name}] Monitoring udev events (USB + Bluetooth)")

        event_props = {}
        for line in self._process.stdout:
            if not self.active:
                break

            line = line.strip()

            if line.startswith('KERNEL'):
                # New event — process previous if any
                if event_props:
                    self._process_udev_event(event_props)
                event_props = {}
                # Parse: KERNEL[timestamp] action devpath (subsystem)
                match = re.match(r'KERNEL\[[\d.]+\]\s+(\w+)\s+(\S+)\s+\((\w+)\)', line)
                if match:
                    event_props['action'] = match.group(1)
                    event_props['devpath'] = match.group(2)
                    event_props['subsystem'] = match.group(3)

            elif '=' in line:
                key, _, value = line.partition('=')
                event_props[key] = value

        # Process last event
        if event_props:
            self._process_udev_event(event_props)

        if self._process:
            self._process.terminate()

    def _run_polling_fallback(self):
        """Fallback: poll /sys/bus/usb/devices and bluetoothctl."""
        print(f"[{self.name}] Polling USB + Bluetooth (5s interval)")
        while self.active:
            try:
                # USB
                current_usb = set()
                usb_base = Path('/sys/bus/usb/devices')
                if usb_base.exists():
                    for dev in usb_base.iterdir():
                        product = dev / 'product'
                        if product.exists():
                            current_usb.add(dev.name)

                for name in current_usb - self._known_usb:
                    info = self._get_usb_device_info(f'/bus/usb/devices/{name}')
                    self._record_usb_connect(name, info)
                for name in self._known_usb - current_usb:
                    self._record_usb_disconnect(name)
                self._known_usb = current_usb

                # Bluetooth
                current_bt = set()
                try:
                    result = subprocess.run(
                        ['bluetoothctl', 'devices', 'Connected'],
                        capture_output=True, text=True, timeout=5,
                    )
                    if result.returncode == 0:
                        for line in result.stdout.strip().split('\n'):
                            parts = line.split()
                            if len(parts) >= 2:
                                current_bt.add(parts[1])
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    pass

                for addr in current_bt - self._known_bt:
                    self._record_bt_connect(addr, '')
                for addr in self._known_bt - current_bt:
                    self._record_bt_disconnect(addr)
                self._known_bt = current_bt

            except Exception as e:
                self.errors += 1
            time.sleep(5.0)

    def stop(self):
        """Override stop to kill udevadm subprocess."""
        self.active = False
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
        super().stop()

    def _process_udev_event(self, props):
        """Process a single udev event."""
        action = props.get('action', '')
        subsystem = props.get('subsystem', '')
        devpath = props.get('devpath', '')

        if subsystem == 'usb':
            if action == 'add':
                info = self._get_usb_device_info(devpath)
                if info:
                    self._record_usb_connect(devpath, info)
            elif action == 'remove':
                self._record_usb_disconnect(devpath)

        elif subsystem == 'bluetooth':
            name = props.get('NAME', '').strip('"')
            addr = props.get('UNIQ', '') or devpath.split('/')[-1]
            if action == 'add':
                self._record_bt_connect(addr, name)
            elif action == 'remove':
                self._record_bt_disconnect(addr)

    def _record_usb_connect(self, devpath, info):
        data = json.dumps({
            'devpath': str(devpath)[:200],
            'vendor': info.get('idVendor', ''),
            'product_id': info.get('idProduct', ''),
            'manufacturer': info.get('manufacturer', ''),
            'product': info.get('product', ''),
        }).encode('utf-8')
        self._record(1, data)  # PERIPH_USB_CONNECT

    def _record_usb_disconnect(self, devpath):
        data = json.dumps({'devpath': str(devpath)[:200]}).encode('utf-8')
        self._record(2, data)  # PERIPH_USB_DISCONNECT

    def _record_bt_connect(self, address, name):
        data = json.dumps({'address': address, 'name': name}).encode('utf-8')
        self._record(3, data)  # PERIPH_BLUETOOTH_CONNECT

    def _record_bt_disconnect(self, address):
        data = json.dumps({'address': address}).encode('utf-8')
        self._record(4, data)  # PERIPH_BLUETOOTH_DISCONNECT


# ═══════════════════════════════════════════
# Channel 18: NOTIFICATION
# ═══════════════════════════════════════════

class NotificationChannel(BaseChannel):
    """
    Desktop notification tracking via dbus-monitor.

    Captures all desktop notifications from all applications.
    This is separate from MessageChannel — it captures ALL notifications,
    not just messaging ones.

    Records:
    - NOTIF_RECEIVED (1): Notification appeared
    - NOTIF_CLICKED (2): User clicked/interacted with notification
    - NOTIF_DISMISSED (3): User dismissed notification
    - NOTIF_TIMEOUT (4): Notification expired without user interaction
    """

    def __init__(self, client):
        super().__init__(client, 18, 'notification')
        self._process = None
        self._active_notifications = {}  # id → {'app': str, 'summary': str, 'time': float}

    def _run(self):
        """Monitor notifications via dbus-monitor."""
        cmd = [
            'dbus-monitor',
            '--session',
            "type='method_call',interface='org.freedesktop.Notifications',member='Notify'",
            "type='method_call',interface='org.freedesktop.Notifications',member='CloseNotification'",
            "type='signal',interface='org.freedesktop.Notifications',member='NotificationClosed'",
        ]

        try:
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
            )
        except FileNotFoundError:
            print(f"[{self.name}] dbus-monitor not found")
            return

        print(f"[{self.name}] Listening for desktop notifications")

        buffer = []
        in_notify = False
        in_close = False

        for line in self._process.stdout:
            if not self.active:
                break

            line = line.strip()

            # Detect Notify method call
            if 'member=Notify' in line and 'method_call' in line:
                in_notify = True
                in_close = False
                buffer = []
                continue

            # Detect CloseNotification or NotificationClosed
            if ('member=CloseNotification' in line or
                'member=NotificationClosed' in line):
                in_close = True
                in_notify = False
                buffer = []
                continue

            if in_notify:
                buffer.append(line)
                # Notify has: app_name, replaces_id, icon, summary, body, actions, hints, timeout
                # We need at least the string args
                strings = [l for l in buffer if 'string "' in l]
                if len(strings) >= 4:
                    try:
                        app_name = self._extract_string(strings[0])
                        icon = self._extract_string(strings[1])
                        summary = self._extract_string(strings[2])
                        body = self._extract_string(strings[3]) if len(strings) > 3 else ''

                        self._record_received(app_name, summary, body, icon)

                        # Track for close detection
                        notif_id = len(self._active_notifications)
                        self._active_notifications[notif_id] = {
                            'app': app_name,
                            'summary': summary,
                            'time': time.time(),
                        }
                    except Exception:
                        self.errors += 1
                    in_notify = False
                    buffer = []

            elif in_close:
                # Extract notification ID and reason
                uints = [l for l in buffer if 'uint32' in l]
                if uints:
                    try:
                        match = re.search(r'uint32\s+(\d+)', uints[0])
                        if match:
                            notif_id = int(match.group(1))
                            # Reason: 1=expired, 2=dismissed, 3=closed by app, 4=undefined
                            reason = 4
                            if len(uints) > 1:
                                rmatch = re.search(r'uint32\s+(\d+)', uints[1])
                                if rmatch:
                                    reason = int(rmatch.group(1))

                            if reason == 1:
                                self._record_timeout(notif_id)
                            elif reason == 2:
                                self._record_dismissed(notif_id)
                            elif reason == 3:
                                self._record_clicked(notif_id)
                    except Exception:
                        self.errors += 1
                    in_close = False
                    buffer = []

        if self._process:
            self._process.terminate()

    def stop(self):
        """Override stop to kill dbus-monitor subprocess."""
        self.active = False
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
        super().stop()

    def _extract_string(self, line):
        """Extract a string value from a dbus-monitor output line."""
        match = re.search(r'string "([^"]*)"', line)
        return match.group(1) if match else ''

    def _record_received(self, app, summary, body, icon):
        data = json.dumps({
            'app': app[:200],
            'summary': summary[:500],
            'body': body[:1000],
            'icon': icon[:200],
        }).encode('utf-8')
        self._record(1, data)  # NOTIF_RECEIVED

    def _record_clicked(self, notif_id):
        info = self._active_notifications.pop(notif_id, {})
        data = json.dumps({
            'notification_id': notif_id,
            'app': info.get('app', ''),
            'summary': info.get('summary', ''),
            'age_s': round(time.time() - info.get('time', time.time()), 1),
        }).encode('utf-8')
        self._record(2, data)  # NOTIF_CLICKED

    def _record_dismissed(self, notif_id):
        info = self._active_notifications.pop(notif_id, {})
        data = json.dumps({
            'notification_id': notif_id,
            'app': info.get('app', ''),
            'summary': info.get('summary', ''),
            'age_s': round(time.time() - info.get('time', time.time()), 1),
        }).encode('utf-8')
        self._record(3, data)  # NOTIF_DISMISSED

    def _record_timeout(self, notif_id):
        info = self._active_notifications.pop(notif_id, {})
        data = json.dumps({
            'notification_id': notif_id,
            'app': info.get('app', ''),
            'summary': info.get('summary', ''),
            'age_s': round(time.time() - info.get('time', time.time()), 1),
        }).encode('utf-8')
        self._record(4, data)  # NOTIF_TIMEOUT
