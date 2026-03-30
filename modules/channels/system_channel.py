"""System resource monitoring channel — CPU, RAM, disk, network, temperature."""

import json
import os
import subprocess
import time

from modules.channels.base_channel import BaseChannel


class SystemChannel(BaseChannel):
    """
    Comprehensive system resource snapshots every 10 seconds.

    Records:
    - SYS_RESOURCE_SNAPSHOT (1): Full system state (CPU, RAM, swap, load,
      temperature, network I/O, disk, top processes, uptime)
    - SYS_PROCESS_START (2): New significant process detected
    - SYS_PROCESS_END (3): Significant process exited
    - SYS_PROCESS_CRASH (4): Process exited abnormally
    - SYS_NETWORK_IO (5): Network bytes batch (10s delta)
    - SYS_DISK_IO (6): Disk read/write batch (10s delta)
    """

    POLL_INTERVAL = 10  # seconds

    def __init__(self, client):
        super().__init__(client, 8, 'system')
        self._prev_cpu_times = None
        self._prev_net_bytes = None
        self._prev_disk_stats = None

    def _run(self):
        """Main system monitoring loop."""
        print(f"[{self.name}] Polling system resources every {self.POLL_INTERVAL}s")

        # Prime the deltas
        self._prev_cpu_times = self._read_cpu_times()
        self._prev_net_bytes = self._read_net_bytes()
        self._prev_disk_stats = self._read_disk_stats()
        time.sleep(self.POLL_INTERVAL)

        while self.active:
            try:
                snapshot = self._get_system_snapshot()
                if snapshot:
                    data = json.dumps(snapshot).encode('utf-8')
                    self._record(1, data)  # SYS_RESOURCE_SNAPSHOT

                    # Also record network I/O as separate event if significant
                    net = snapshot.get('network')
                    if net:
                        total_rx = sum(v.get('rx_bytes_delta', 0) for v in net.values())
                        total_tx = sum(v.get('tx_bytes_delta', 0) for v in net.values())
                        if total_rx > 0 or total_tx > 0:
                            net_data = json.dumps({
                                'rx_bytes': total_rx,
                                'tx_bytes': total_tx,
                                'interfaces': net,
                            }).encode('utf-8')
                            self._record(5, net_data)  # SYS_NETWORK_IO

                    # Record disk I/O if significant
                    disk_io = snapshot.get('disk_io')
                    if disk_io:
                        total_read = sum(v.get('read_bytes_delta', 0) for v in disk_io.values())
                        total_write = sum(v.get('write_bytes_delta', 0) for v in disk_io.values())
                        if total_read > 0 or total_write > 0:
                            disk_data = json.dumps({
                                'read_bytes': total_read,
                                'write_bytes': total_write,
                                'devices': disk_io,
                            }).encode('utf-8')
                            self._record(6, disk_data)  # SYS_DISK_IO

            except Exception as e:
                self.errors += 1
            time.sleep(self.POLL_INTERVAL)

    def _get_system_snapshot(self):
        """Collect a complete system resource snapshot."""
        snapshot = {}

        subsystems = [
            ('cpu', self._get_cpu_usage),
            ('memory', self._get_memory),
            ('load', self._get_load_average),
            ('temperature', self._get_temperature),
            ('network', self._get_network_delta),
            ('disk_usage', self._get_disk_usage),
            ('disk_io', self._get_disk_io_delta),
            ('top_processes', self._get_top_processes),
            ('uptime', self._get_uptime),
        ]

        for name, fn in subsystems:
            try:
                snapshot[name] = fn()
            except Exception as e:
                self.errors += 1
                if self.errors <= 3 or self.errors % 100 == 0:
                    print(f"[{self.name}] Subsystem '{name}' error #{self.errors}: {type(e).__name__}: {e}")
                snapshot[name] = {} if name != 'top_processes' else []

        return snapshot

    # ── CPU ────────────────────────────────────────────────────────────────

    def _read_cpu_times(self):
        """Read per-CPU times from /proc/stat."""
        cpu_times = {}
        try:
            with open('/proc/stat', 'r') as f:
                for line in f:
                    if line.startswith('cpu'):
                        parts = line.strip().split()
                        name = parts[0]
                        times = [int(x) for x in parts[1:]]
                        cpu_times[name] = times
        except Exception:
            pass
        return cpu_times

    def _get_cpu_usage(self):
        """Calculate CPU usage percentage per core since last snapshot."""
        current = self._read_cpu_times()
        result = {}

        if self._prev_cpu_times:
            for name in current:
                if name in self._prev_cpu_times:
                    prev = self._prev_cpu_times[name]
                    curr = current[name]

                    # user, nice, system, idle, iowait, irq, softirq, steal
                    prev_idle = prev[3] + (prev[4] if len(prev) > 4 else 0)
                    curr_idle = curr[3] + (curr[4] if len(curr) > 4 else 0)

                    prev_total = sum(prev)
                    curr_total = sum(curr)

                    total_delta = curr_total - prev_total
                    idle_delta = curr_idle - prev_idle

                    if total_delta > 0:
                        usage = round((1.0 - idle_delta / total_delta) * 100, 1)
                    else:
                        usage = 0.0

                    result[name] = usage

        self._prev_cpu_times = current
        return result

    # ── Memory ─────────────────────────────────────────────────────────────

    def _get_memory(self):
        """Read memory stats from /proc/meminfo."""
        mem = {}
        try:
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    parts = line.strip().split()
                    key = parts[0].rstrip(':')
                    value_kb = int(parts[1])
                    if key in ('MemTotal', 'MemFree', 'MemAvailable', 'Buffers',
                               'Cached', 'SwapTotal', 'SwapFree', 'Dirty', 'Shmem'):
                        mem[key] = value_kb

            total = mem.get('MemTotal', 1)
            available = mem.get('MemAvailable', 0)
            used = total - available

            swap_total = mem.get('SwapTotal', 0)
            swap_free = mem.get('SwapFree', 0)
            swap_used = swap_total - swap_free

            return {
                'total_mb': round(total / 1024, 1),
                'used_mb': round(used / 1024, 1),
                'available_mb': round(available / 1024, 1),
                'usage_pct': round(used / total * 100, 1) if total > 0 else 0,
                'buffers_mb': round(mem.get('Buffers', 0) / 1024, 1),
                'cached_mb': round(mem.get('Cached', 0) / 1024, 1),
                'swap_total_mb': round(swap_total / 1024, 1),
                'swap_used_mb': round(swap_used / 1024, 1),
                'swap_usage_pct': round(swap_used / swap_total * 100, 1) if swap_total > 0 else 0,
                'dirty_kb': mem.get('Dirty', 0),
            }
        except Exception:
            return {}

    # ── Load average ───────────────────────────────────────────────────────

    def _get_load_average(self):
        """Read load average from /proc/loadavg."""
        try:
            with open('/proc/loadavg', 'r') as f:
                parts = f.read().strip().split()
                running = parts[3].split('/')
                return {
                    'load_1m': float(parts[0]),
                    'load_5m': float(parts[1]),
                    'load_15m': float(parts[2]),
                    'running_processes': int(running[0]),
                    'total_processes': int(running[1]),
                }
        except Exception:
            return {}

    # ── Temperature ────────────────────────────────────────────────────────

    def _get_temperature(self):
        """Read CPU temperature via vcgencmd (Raspberry Pi) or thermal zones."""
        # Try vcgencmd first (Pi-specific)
        try:
            result = subprocess.run(
                ['vcgencmd', 'measure_temp'],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                # Output: temp=42.8'C
                import re
                match = re.search(r'temp=([\d.]+)', result.stdout)
                if match:
                    return {'cpu_c': float(match.group(1)), 'source': 'vcgencmd'}
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Fallback: thermal zone
        try:
            thermal_path = '/sys/class/thermal/thermal_zone0/temp'
            if os.path.exists(thermal_path):
                with open(thermal_path, 'r') as f:
                    millideg = int(f.read().strip())
                    return {'cpu_c': round(millideg / 1000, 1), 'source': 'thermal_zone'}
        except Exception:
            pass

        return {}

    # ── Network I/O ────────────────────────────────────────────────────────

    def _read_net_bytes(self):
        """Read network byte counters from /proc/net/dev."""
        net = {}
        try:
            with open('/proc/net/dev', 'r') as f:
                for line in f:
                    line = line.strip()
                    if ':' not in line:
                        continue
                    iface, stats = line.split(':', 1)
                    iface = iface.strip()
                    if iface == 'lo':
                        continue
                    parts = stats.split()
                    if len(parts) >= 10:
                        net[iface] = {
                            'rx_bytes': int(parts[0]),
                            'rx_packets': int(parts[1]),
                            'tx_bytes': int(parts[8]),
                            'tx_packets': int(parts[9]),
                        }
        except Exception:
            pass
        return net

    def _get_network_delta(self):
        """Calculate network I/O delta since last snapshot."""
        current = self._read_net_bytes()
        delta = {}

        if self._prev_net_bytes:
            for iface in current:
                if iface in self._prev_net_bytes:
                    prev = self._prev_net_bytes[iface]
                    curr = current[iface]
                    delta[iface] = {
                        'rx_bytes_delta': curr['rx_bytes'] - prev['rx_bytes'],
                        'tx_bytes_delta': curr['tx_bytes'] - prev['tx_bytes'],
                        'rx_packets_delta': curr['rx_packets'] - prev['rx_packets'],
                        'tx_packets_delta': curr['tx_packets'] - prev['tx_packets'],
                    }

        self._prev_net_bytes = current
        return delta

    # ── Disk usage ─────────────────────────────────────────────────────────

    def _get_disk_usage(self):
        """Get disk usage from df."""
        disks = {}
        try:
            result = subprocess.run(
                ['df', '-B1', '--output=target,size,used,avail,pcent'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n')[1:]:
                    parts = line.split()
                    if len(parts) >= 5:
                        mount = parts[0]
                        # Only track real filesystems
                        if mount in ('/', '/home', '/boot', '/opt', '/opt/nexus'):
                            disks[mount] = {
                                'total_gb': round(int(parts[1]) / (1024**3), 2),
                                'used_gb': round(int(parts[2]) / (1024**3), 2),
                                'avail_gb': round(int(parts[3]) / (1024**3), 2),
                                'usage_pct': parts[4].rstrip('%'),
                            }
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return disks

    # ── Disk I/O ───────────────────────────────────────────────────────────

    def _read_disk_stats(self):
        """Read disk I/O counters from /proc/diskstats."""
        stats = {}
        try:
            with open('/proc/diskstats', 'r') as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 14:
                        name = parts[2]
                        # Only track whole devices (not partitions with numbers)
                        if name.startswith(('sd', 'nvme', 'mmcblk')) and not any(c.isdigit() for c in name[-1:] if not name.startswith('mmcblk')):
                            # For mmcblk, accept mmcblk0 but not mmcblk0p1
                            if name.startswith('mmcblk') and 'p' in name:
                                continue
                            stats[name] = {
                                'reads': int(parts[3]),
                                'read_sectors': int(parts[5]),
                                'writes': int(parts[7]),
                                'write_sectors': int(parts[9]),
                            }
        except Exception:
            pass
        return stats

    def _get_disk_io_delta(self):
        """Calculate disk I/O delta since last snapshot."""
        current = self._read_disk_stats()
        delta = {}

        if self._prev_disk_stats:
            for dev in current:
                if dev in self._prev_disk_stats:
                    prev = self._prev_disk_stats[dev]
                    curr = current[dev]
                    # Sectors are 512 bytes
                    delta[dev] = {
                        'read_bytes_delta': (curr['read_sectors'] - prev['read_sectors']) * 512,
                        'write_bytes_delta': (curr['write_sectors'] - prev['write_sectors']) * 512,
                        'reads_delta': curr['reads'] - prev['reads'],
                        'writes_delta': curr['writes'] - prev['writes'],
                    }

        self._prev_disk_stats = current
        return delta

    # ── Top processes ──────────────────────────────────────────────────────

    def _get_top_processes(self):
        """Get top 5 processes by CPU usage."""
        try:
            result = subprocess.run(
                ['ps', 'aux', '--sort=-pcpu'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return []

            processes = []
            lines = result.stdout.strip().split('\n')
            for line in lines[1:6]:  # Skip header, take top 5
                parts = line.split(None, 10)
                if len(parts) >= 11:
                    processes.append({
                        'user': parts[0],
                        'pid': int(parts[1]),
                        'cpu_pct': float(parts[2]),
                        'mem_pct': float(parts[3]),
                        'rss_kb': int(parts[5]),
                        'command': parts[10][:200],
                    })
            return processes
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []

    # ── Uptime ─────────────────────────────────────────────────────────────

    def _get_uptime(self):
        """Read system uptime from /proc/uptime."""
        try:
            with open('/proc/uptime', 'r') as f:
                parts = f.read().strip().split()
                uptime_s = float(parts[0])
                idle_s = float(parts[1])
                return {
                    'uptime_s': round(uptime_s, 1),
                    'uptime_h': round(uptime_s / 3600, 2),
                    'idle_s': round(idle_s, 1),
                    'idle_pct': round(idle_s / (uptime_s * os.cpu_count()) * 100, 1) if uptime_s > 0 else 0,
                }
        except Exception:
            return {}
