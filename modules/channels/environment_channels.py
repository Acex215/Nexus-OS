"""Environment behavioral collection channels — GPS, Weather, WiFi."""

import json
import math
import os
import re
import subprocess
import time

from modules.channels.base_channel import BaseChannel

try:
    import urllib.request
    import urllib.error
    HAS_URLLIB = True
except ImportError:
    HAS_URLLIB = False


# ═══════════════════════════════════════════
# Channel 11: GPS
# ═══════════════════════════════════════════

class GPSChannel(BaseChannel):
    """
    Position tracking via gpsd or IP-geolocation fallback.

    Records:
    - GPS_POSITION (1): Lat/lon every 30s
    - GPS_SPEED (2): Movement speed when moving
    - GPS_GEOFENCE_ENTER (3): Entered a known location radius
    - GPS_GEOFENCE_EXIT (4): Exited a known location radius
    """

    GEOFENCE_RADIUS_M = 100  # meters

    def __init__(self, client):
        super().__init__(client, 11, 'gps')
        self._last_lat = None
        self._last_lon = None
        self._last_position_time = 0
        self._geofences = {}  # name → {'lat': float, 'lon': float, 'radius_m': float}
        self._inside_geofences = set()  # names of geofences we're currently inside
        self._poll_interval = 30.0
        self._has_gpsd = False
        self._load_geofences()

    def _load_geofences(self):
        """Load user-defined geofences from config."""
        config_path = '/opt/nexus/config/geofences.json'
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    self._geofences = json.load(f)
        except Exception:
            pass

    @staticmethod
    def haversine(lat1, lon1, lat2, lon2):
        """
        Calculate the great-circle distance between two points
        on Earth (in meters) using the Haversine formula.
        """
        R = 6371000  # Earth radius in meters
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)

        a = (math.sin(dphi / 2) ** 2 +
             math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def _check_gpsd(self):
        """Check if gpsd is running and accessible."""
        try:
            result = subprocess.run(
                ['gpspipe', '-w', '-n', '1'],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _get_position_gpsd(self):
        """Get position from gpsd via gpspipe."""
        try:
            result = subprocess.run(
                ['gpspipe', '-w', '-n', '5'],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return None

            for line in result.stdout.strip().split('\n'):
                try:
                    data = json.loads(line)
                    if data.get('class') == 'TPV':
                        lat = data.get('lat')
                        lon = data.get('lon')
                        if lat is not None and lon is not None:
                            return {
                                'lat': lat,
                                'lon': lon,
                                'alt': data.get('alt', 0),
                                'speed': data.get('speed', 0),
                                'track': data.get('track', 0),
                                'mode': data.get('mode', 0),
                                'source': 'gpsd',
                            }
                except json.JSONDecodeError:
                    continue
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    def _get_position_ip(self):
        """Fallback: get approximate position from IP geolocation."""
        if not HAS_URLLIB:
            return None
        try:
            req = urllib.request.Request(
                'http://ip-api.com/json/?fields=lat,lon,city,regionName,country',
                headers={'User-Agent': 'NEXUS-OS/1.0'},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                if 'lat' in data and 'lon' in data:
                    return {
                        'lat': data['lat'],
                        'lon': data['lon'],
                        'alt': 0,
                        'speed': 0,
                        'track': 0,
                        'mode': 0,
                        'source': 'ip-geo',
                        'city': data.get('city', ''),
                        'region': data.get('regionName', ''),
                        'country': data.get('country', ''),
                    }
        except Exception:
            pass
        return None

    def _run(self):
        """Main GPS polling loop."""
        self._has_gpsd = self._check_gpsd()
        source = "gpsd" if self._has_gpsd else "IP-geolocation"
        print(f"[{self.name}] Using {source} (polling every {self._poll_interval}s)")

        while self.active:
            try:
                pos = None
                if self._has_gpsd:
                    pos = self._get_position_gpsd()
                if pos is None:
                    pos = self._get_position_ip()

                if pos:
                    self._process_position(pos)
            except Exception as e:
                self.errors += 1
            time.sleep(self._poll_interval)

    def _process_position(self, pos):
        """Process a new position reading."""
        lat = pos['lat']
        lon = pos['lon']
        now = time.time()

        # Record position
        self._record_position(pos)

        # Calculate speed if we have a previous position
        if self._last_lat is not None and self._last_lon is not None:
            dist = self.haversine(self._last_lat, self._last_lon, lat, lon)
            dt = now - self._last_position_time
            if dt > 0:
                speed_ms = dist / dt
                if speed_ms > 0.5:  # Moving faster than 0.5 m/s (~2 km/h)
                    self._record_speed(speed_ms, dist, dt)

        # Geofence checks
        for name, fence in self._geofences.items():
            radius = fence.get('radius_m', self.GEOFENCE_RADIUS_M)
            dist = self.haversine(lat, lon, fence['lat'], fence['lon'])
            inside = dist <= radius

            if inside and name not in self._inside_geofences:
                self._inside_geofences.add(name)
                self._record_geofence_enter(name, fence, dist)
            elif not inside and name in self._inside_geofences:
                self._inside_geofences.discard(name)
                self._record_geofence_exit(name, fence, dist)

        self._last_lat = lat
        self._last_lon = lon
        self._last_position_time = now

    def _record_position(self, pos):
        data = json.dumps({
            'lat': round(pos['lat'], 6),
            'lon': round(pos['lon'], 6),
            'alt': round(pos.get('alt', 0), 1),
            'speed': round(pos.get('speed', 0), 2),
            'track': round(pos.get('track', 0), 1),
            'source': pos.get('source', 'unknown'),
        }).encode('utf-8')
        self._record(1, data)  # GPS_POSITION

    def _record_speed(self, speed_ms, distance, dt):
        data = json.dumps({
            'speed_ms': round(speed_ms, 2),
            'speed_kmh': round(speed_ms * 3.6, 1),
            'distance_m': round(distance, 1),
            'interval_s': round(dt, 1),
        }).encode('utf-8')
        self._record(2, data)  # GPS_SPEED

    def _record_geofence_enter(self, name, fence, distance):
        data = json.dumps({
            'geofence': name,
            'lat': fence['lat'],
            'lon': fence['lon'],
            'distance_m': round(distance, 1),
        }).encode('utf-8')
        self._record(3, data)  # GPS_GEOFENCE_ENTER

    def _record_geofence_exit(self, name, fence, distance):
        data = json.dumps({
            'geofence': name,
            'lat': fence['lat'],
            'lon': fence['lon'],
            'distance_m': round(distance, 1),
        }).encode('utf-8')
        self._record(4, data)  # GPS_GEOFENCE_EXIT


# ═══════════════════════════════════════════
# Channel 12: WEATHER
# ═══════════════════════════════════════════

class WeatherChannel(BaseChannel):
    """
    Weather conditions via Open-Meteo (free, no API key required).

    Records:
    - WEATHER_SNAPSHOT (1): Full weather every 15 minutes
    - WEATHER_ALERT (2): Significant weather change detected
    """

    OPEN_METEO_URL = (
        "https://api.open-meteo.com/v1/forecast?"
        "latitude={lat}&longitude={lon}"
        "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
        "precipitation,rain,cloud_cover,wind_speed_10m,wind_direction_10m,"
        "wind_gusts_10m,pressure_msl,uv_index"
        "&timezone=auto"
    )

    # Thresholds for weather alerts
    ALERT_TEMP_CHANGE = 5.0      # degrees C change between readings
    ALERT_WIND_SPEED = 50.0      # km/h
    ALERT_PRECIPITATION = 5.0    # mm
    ALERT_UV_INDEX = 8           # high UV

    def __init__(self, client):
        super().__init__(client, 12, 'weather')
        self._lat = None
        self._lon = None
        self._last_weather = None
        self._poll_interval = 900.0  # 15 minutes

    def set_location(self, lat, lon):
        """Set the location for weather queries."""
        self._lat = lat
        self._lon = lon

    def _get_location(self):
        """Get current location from GPS channel config or IP geolocation."""
        if self._lat is not None and self._lon is not None:
            return self._lat, self._lon

        # Try to read from node identity
        try:
            config_path = '/opt/nexus/config/node_identity.json'
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    identity = json.load(f)
                    caps = identity.get('capabilities', {})
                    if 'lat' in caps and 'lon' in caps:
                        return caps['lat'], caps['lon']
        except Exception:
            pass

        # IP geolocation fallback
        if HAS_URLLIB:
            try:
                req = urllib.request.Request(
                    'http://ip-api.com/json/?fields=lat,lon',
                    headers={'User-Agent': 'NEXUS-OS/1.0'},
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode())
                    if 'lat' in data and 'lon' in data:
                        self._lat = data['lat']
                        self._lon = data['lon']
                        return self._lat, self._lon
            except Exception:
                pass

        return None, None

    def _fetch_weather(self, lat, lon):
        """Fetch current weather from Open-Meteo."""
        if not HAS_URLLIB:
            return None
        try:
            url = self.OPEN_METEO_URL.format(lat=lat, lon=lon)
            req = urllib.request.Request(url, headers={'User-Agent': 'NEXUS-OS/1.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                current = data.get('current', {})
                return {
                    'temperature_c': current.get('temperature_2m'),
                    'feels_like_c': current.get('apparent_temperature'),
                    'humidity_pct': current.get('relative_humidity_2m'),
                    'precipitation_mm': current.get('precipitation'),
                    'rain_mm': current.get('rain'),
                    'cloud_cover_pct': current.get('cloud_cover'),
                    'wind_speed_kmh': current.get('wind_speed_10m'),
                    'wind_direction_deg': current.get('wind_direction_10m'),
                    'wind_gusts_kmh': current.get('wind_gusts_10m'),
                    'pressure_hpa': current.get('pressure_msl'),
                    'uv_index': current.get('uv_index'),
                    'lat': lat,
                    'lon': lon,
                }
        except Exception:
            return None

    def _run(self):
        """Main weather polling loop."""
        lat, lon = self._get_location()
        if lat is None or lon is None:
            print(f"[{self.name}] Cannot determine location — retrying in 60s")
            time.sleep(60)
            lat, lon = self._get_location()
            if lat is None:
                print(f"[{self.name}] No location available — stopping")
                return

        print(f"[{self.name}] Polling weather at ({lat:.4f}, {lon:.4f}) every {self._poll_interval/60:.0f}min")

        while self.active:
            try:
                weather = self._fetch_weather(lat, lon)
                if weather:
                    self._record_snapshot(weather)
                    self._check_alerts(weather)
                    self._last_weather = weather

                # Update location periodically (user might be moving)
                new_lat, new_lon = self._get_location()
                if new_lat is not None:
                    lat, lon = new_lat, new_lon
            except Exception as e:
                self.errors += 1
            time.sleep(self._poll_interval)

    def _check_alerts(self, weather):
        """Check for significant weather changes that warrant an alert."""
        if self._last_weather is None:
            return

        alerts = []

        # Temperature change
        old_temp = self._last_weather.get('temperature_c')
        new_temp = weather.get('temperature_c')
        if old_temp is not None and new_temp is not None:
            if abs(new_temp - old_temp) >= self.ALERT_TEMP_CHANGE:
                alerts.append(f"Temperature changed {new_temp - old_temp:+.1f}°C")

        # High wind
        wind = weather.get('wind_speed_kmh')
        if wind is not None and wind >= self.ALERT_WIND_SPEED:
            alerts.append(f"High wind: {wind:.0f} km/h")

        # Precipitation
        precip = weather.get('precipitation_mm')
        if precip is not None and precip >= self.ALERT_PRECIPITATION:
            alerts.append(f"Heavy precipitation: {precip:.1f} mm")

        # High UV
        uv = weather.get('uv_index')
        if uv is not None and uv >= self.ALERT_UV_INDEX:
            alerts.append(f"High UV index: {uv}")

        if alerts:
            self._record_alert(weather, alerts)

    def _record_snapshot(self, weather):
        data = json.dumps(weather).encode('utf-8')
        self._record(1, data)  # WEATHER_SNAPSHOT

    def _record_alert(self, weather, alerts):
        alert_data = dict(weather)
        alert_data['alerts'] = alerts
        data = json.dumps(alert_data).encode('utf-8')
        self._record(2, data)  # WEATHER_ALERT


# ═══════════════════════════════════════════
# Channel 13: WIFI
# ═══════════════════════════════════════════

class WiFiChannel(BaseChannel):
    """
    WiFi connection monitoring via iwconfig/nmcli.

    Records:
    - WIFI_CONNECTED (1): Connected to a network (SSID, BSSID, signal)
    - WIFI_DISCONNECTED (2): Disconnected from a network
    - WIFI_SCAN (3): Available networks snapshot
    - WIFI_SIGNAL_STRENGTH (4): RSSI reading every 60s
    """

    def __init__(self, client):
        super().__init__(client, 13, 'wifi')
        self._current_ssid = None
        self._current_bssid = None
        self._interface = 'wlan0'
        self._poll_interval = 60.0
        self._scan_interval = 300.0  # 5 minutes between scans
        self._last_scan_time = 0

    def _parse_iwconfig(self):
        """Parse iwconfig output for current connection info."""
        try:
            result = subprocess.run(
                ['iwconfig', self._interface],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return None

            output = result.stdout
            info = {
                'interface': self._interface,
                'ssid': None,
                'bssid': None,
                'frequency': None,
                'signal_dbm': None,
                'noise_dbm': None,
                'link_quality': None,
                'bit_rate': None,
                'mode': None,
            }

            # ESSID
            match = re.search(r'ESSID:"([^"]*)"', output)
            if match:
                ssid = match.group(1)
                if ssid and ssid != 'off/any':
                    info['ssid'] = ssid

            # Access Point (BSSID)
            match = re.search(r'Access Point:\s*([0-9A-Fa-f:]{17})', output)
            if match:
                info['bssid'] = match.group(1)

            # Frequency
            match = re.search(r'Frequency[=:](\d+\.?\d*)\s*GHz', output)
            if match:
                info['frequency'] = float(match.group(1))

            # Signal level
            match = re.search(r'Signal level[=:](-?\d+)\s*dBm', output)
            if match:
                info['signal_dbm'] = int(match.group(1))

            # Noise level
            match = re.search(r'Noise level[=:](-?\d+)\s*dBm', output)
            if match:
                info['noise_dbm'] = int(match.group(1))

            # Link Quality
            match = re.search(r'Link Quality[=:](\d+)/(\d+)', output)
            if match:
                info['link_quality'] = f"{match.group(1)}/{match.group(2)}"

            # Bit Rate
            match = re.search(r'Bit Rate[=:](\d+\.?\d*)\s*Mb/s', output)
            if match:
                info['bit_rate'] = float(match.group(1))

            # Mode
            match = re.search(r'Mode:(\w+)', output)
            if match:
                info['mode'] = match.group(1)

            return info

        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    def _scan_networks(self):
        """Scan for available WiFi networks."""
        try:
            result = subprocess.run(
                ['sudo', 'iwlist', self._interface, 'scan'],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                return []

            networks = []
            current = {}
            for line in result.stdout.split('\n'):
                line = line.strip()

                if line.startswith('Cell'):
                    if current:
                        networks.append(current)
                    current = {}
                    match = re.search(r'Address:\s*([0-9A-Fa-f:]{17})', line)
                    if match:
                        current['bssid'] = match.group(1)

                elif 'ESSID:' in line:
                    match = re.search(r'ESSID:"([^"]*)"', line)
                    if match:
                        current['ssid'] = match.group(1)

                elif 'Signal level' in line:
                    match = re.search(r'Signal level[=:](-?\d+)', line)
                    if match:
                        current['signal_dbm'] = int(match.group(1))

                elif 'Frequency:' in line:
                    match = re.search(r'Frequency:(\d+\.?\d*)', line)
                    if match:
                        current['frequency'] = float(match.group(1))

                elif 'Encryption key:' in line:
                    current['encrypted'] = 'on' in line.lower()

            if current:
                networks.append(current)

            return networks

        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []

    def _find_interface(self):
        """Find the wireless interface name."""
        try:
            for iface in os.listdir('/sys/class/net'):
                wireless_dir = f'/sys/class/net/{iface}/wireless'
                if os.path.isdir(wireless_dir):
                    return iface
        except Exception:
            pass
        return 'wlan0'

    def _run(self):
        """Main WiFi monitoring loop."""
        self._interface = self._find_interface()
        print(f"[{self.name}] Monitoring {self._interface} (polling every {self._poll_interval}s)")

        while self.active:
            try:
                info = self._parse_iwconfig()
                if info:
                    self._process_connection(info)
                    self._record_signal_strength(info)

                # Periodic network scan
                now = time.time()
                if now - self._last_scan_time >= self._scan_interval:
                    networks = self._scan_networks()
                    if networks:
                        self._record_scan(networks)
                    self._last_scan_time = now
            except Exception as e:
                self.errors += 1
            time.sleep(self._poll_interval)

    def _process_connection(self, info):
        """Detect connect/disconnect transitions."""
        ssid = info.get('ssid')

        if ssid and ssid != self._current_ssid:
            # Connected to a new network (or switched)
            if self._current_ssid is not None:
                self._record_disconnected(self._current_ssid, self._current_bssid)
            self._record_connected(info)
            self._current_ssid = ssid
            self._current_bssid = info.get('bssid')

        elif not ssid and self._current_ssid is not None:
            # Disconnected
            self._record_disconnected(self._current_ssid, self._current_bssid)
            self._current_ssid = None
            self._current_bssid = None

    def _record_connected(self, info):
        data = json.dumps({
            'ssid': info.get('ssid', ''),
            'bssid': info.get('bssid', ''),
            'frequency': info.get('frequency'),
            'signal_dbm': info.get('signal_dbm'),
            'bit_rate': info.get('bit_rate'),
            'mode': info.get('mode', ''),
        }).encode('utf-8')
        self._record(1, data)  # WIFI_CONNECTED

    def _record_disconnected(self, ssid, bssid):
        data = json.dumps({
            'ssid': ssid or '',
            'bssid': bssid or '',
        }).encode('utf-8')
        self._record(2, data)  # WIFI_DISCONNECTED

    def _record_scan(self, networks):
        scan_data = []
        for net in networks[:20]:  # Cap at 20 networks
            scan_data.append({
                'ssid': net.get('ssid', ''),
                'bssid': net.get('bssid', ''),
                'signal_dbm': net.get('signal_dbm'),
                'frequency': net.get('frequency'),
                'encrypted': net.get('encrypted', False),
            })
        data = json.dumps({
            'count': len(networks),
            'networks': scan_data,
        }).encode('utf-8')
        self._record(3, data)  # WIFI_SCAN

    def _record_signal_strength(self, info):
        signal = info.get('signal_dbm')
        if signal is None:
            return
        data = json.dumps({
            'ssid': info.get('ssid', ''),
            'signal_dbm': signal,
            'noise_dbm': info.get('noise_dbm'),
            'link_quality': info.get('link_quality', ''),
            'bit_rate': info.get('bit_rate'),
        }).encode('utf-8')
        self._record(4, data)  # WIFI_SIGNAL_STRENGTH
