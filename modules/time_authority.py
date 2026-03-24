"""
NEXUS OS — Forensic Time Authority

Implements the ForensicTimeStack from the security resilience design.
Multiple time sources ranked by trustworthiness, with drift detection
to identify NTP poisoning or clock manipulation.

Priority order:
  1. GPS (Flipper Zero serial) — ground truth if connected
  2. Blockchain (latest block timestamp) — consensus time
  3. NTP (pool.ntp.org) — network time
  4. Local system clock — fallback

Every on-chain log includes which time source was used, creating a
verifiable audit trail for forensic reconstruction.
"""

import glob
import logging
import os
import time
from datetime import datetime, timezone

import requests

log = logging.getLogger("nexus.time_authority")

# ── Constants ────────────────────────────────────────────────────────────

GPS_SERIAL_PATTERNS = ["/dev/ttyACM*", "/dev/ttyUSB*"]
GPS_BAUD_RATE = 115200
GPS_READ_TIMEOUT = 3

RPC_URL = "http://10.0.20.3:8545"
NTP_SERVER = "pool.ntp.org"
NTP_TIMEOUT = 2

DRIFT_THRESHOLD_SECONDS = 5


class TimeAuthority:
    """
    Authoritative time source for NEXUS operations.

    Tries each source in priority order (GPS → blockchain → NTP → local)
    and returns the highest-priority available timestamp.
    """

    def __init__(self, rpc_url=None):
        self._rpc_url = rpc_url or RPC_URL
        self._last_source = None

    @property
    def last_source(self):
        """Which time source was used in the most recent get_authoritative_time() call."""
        return self._last_source

    # ── Authoritative time ──────────────────────────────────────────────────

    def get_authoritative_time(self):
        """
        Get the most trustworthy available timestamp.

        Tries sources in priority order:
          1. GPS (Flipper Zero)
          2. Blockchain consensus
          3. NTP
          4. Local system clock

        Returns:
            datetime (timezone-aware, UTC)
        """
        # 1. GPS
        gps_time = self.get_gps_time()
        if gps_time is not None:
            self._last_source = "gps"
            log.debug("Time source: GPS (%s)", gps_time.isoformat())
            return gps_time

        # 2. Blockchain
        try:
            chain_time = self.get_blockchain_time()
            if chain_time is not None:
                self._last_source = "blockchain"
                log.debug("Time source: blockchain (%s)", chain_time.isoformat())
                return chain_time
        except Exception as e:
            log.debug("Blockchain time unavailable: %s", e)

        # 3. NTP
        try:
            ntp_time = self.get_ntp_time()
            if ntp_time is not None:
                self._last_source = "ntp"
                log.debug("Time source: NTP (%s)", ntp_time.isoformat())
                return ntp_time
        except Exception as e:
            log.debug("NTP time unavailable: %s", e)

        # 4. Local fallback
        self._last_source = "local"
        local_time = datetime.now(timezone.utc)
        log.debug("Time source: local (%s)", local_time.isoformat())
        return local_time

    # ── GPS (Flipper Zero) ──────────────────────────────────────────────────

    def get_gps_time(self):
        """
        Read GPS time from Flipper Zero (or any GPS device) via serial.
        Parses NMEA GPRMC/GNRMC sentences for timestamp + date.

        Returns:
            datetime (UTC) or None if Flipper not connected / no GPS fix
        """
        try:
            import serial
        except ImportError:
            return None

        # Find serial devices
        ports = []
        for pattern in GPS_SERIAL_PATTERNS:
            ports.extend(glob.glob(pattern))

        if not ports:
            return None

        for port in ports:
            try:
                ser = serial.Serial(port, GPS_BAUD_RATE, timeout=GPS_READ_TIMEOUT)
                # Read lines looking for NMEA RMC sentence
                deadline = time.monotonic() + GPS_READ_TIMEOUT
                while time.monotonic() < deadline:
                    line = ser.readline().decode("ascii", errors="ignore").strip()
                    if not line:
                        continue

                    # $GPRMC or $GNRMC — Recommended Minimum sentence
                    if line.startswith(("$GPRMC", "$GNRMC")):
                        parsed = self._parse_nmea_rmc(line)
                        if parsed is not None:
                            ser.close()
                            return parsed

                ser.close()
            except Exception:
                continue

        return None

    def _parse_nmea_rmc(self, sentence):
        """
        Parse NMEA RMC sentence for UTC date/time.

        Format: $GPRMC,HHMMSS.ss,A,lat,N,lon,W,speed,course,DDMMYY,...
        Field 1: time (HHMMSS.ss)
        Field 2: A=valid, V=void
        Field 9: date (DDMMYY)
        """
        parts = sentence.split(",")
        if len(parts) < 10:
            return None

        status = parts[2]
        if status != "A":
            return None  # no valid fix

        time_str = parts[1]   # HHMMSS.ss
        date_str = parts[9]   # DDMMYY

        if len(time_str) < 6 or len(date_str) < 6:
            return None

        try:
            hours = int(time_str[0:2])
            minutes = int(time_str[2:4])
            seconds = int(time_str[4:6])
            microseconds = 0
            if "." in time_str:
                frac = time_str.split(".")[1]
                microseconds = int(frac.ljust(6, "0")[:6])

            day = int(date_str[0:2])
            month = int(date_str[2:4])
            year = int(date_str[4:6]) + 2000

            return datetime(year, month, day, hours, minutes, seconds,
                            microseconds, tzinfo=timezone.utc)
        except (ValueError, IndexError):
            return None

    # ── Blockchain time ─────────────────────────────────────────────────────

    def get_blockchain_time(self):
        """
        Read the latest block timestamp from Geth.

        Returns:
            datetime (UTC) or None if RPC unreachable
        """
        try:
            r = requests.post(
                self._rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "method": "eth_getBlockByNumber",
                    "params": ["latest", False],
                    "id": 1,
                },
                timeout=5,
            )
            r.raise_for_status()
            result = r.json().get("result")
            if result is None:
                return None

            timestamp_hex = result.get("timestamp", "0x0")
            timestamp = int(timestamp_hex, 16)
            if timestamp == 0:
                return None

            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except Exception as e:
            log.debug("Blockchain RPC failed: %s", e)
            return None

    # ── NTP time ────────────────────────────────────────────────────────────

    def get_ntp_time(self):
        """
        Query NTP server for current UTC time.

        Returns:
            datetime (UTC) or None if NTP unreachable
        """
        try:
            import ntplib
            client = ntplib.NTPClient()
            response = client.request(NTP_SERVER, version=3, timeout=NTP_TIMEOUT)
            return datetime.fromtimestamp(response.tx_time, tz=timezone.utc)
        except Exception as e:
            log.debug("NTP query failed: %s", e)
            return None

    # ── Drift validation ────────────────────────────────────────────────────

    def validate_time_drift(self):
        """
        Compare all available time sources and detect drift.

        If any sources differ by more than DRIFT_THRESHOLD_SECONDS,
        log a warning. NTP diverging from GPS+blockchain may indicate
        NTP poisoning.

        Returns:
            dict: {
                sources: {name: datetime_iso or None},
                max_drift_seconds: float,
                drift_ok: bool,
                warnings: [str]
            }
        """
        sources = {}
        timestamps = {}

        # Collect all sources independently
        gps = self.get_gps_time()
        sources["gps"] = gps.isoformat() if gps else None
        if gps:
            timestamps["gps"] = gps.timestamp()

        chain = self.get_blockchain_time()
        sources["blockchain"] = chain.isoformat() if chain else None
        if chain:
            timestamps["blockchain"] = chain.timestamp()

        ntp = self.get_ntp_time()
        sources["ntp"] = ntp.isoformat() if ntp else None
        if ntp:
            timestamps["ntp"] = ntp.timestamp()

        local = datetime.now(timezone.utc)
        sources["local"] = local.isoformat()
        timestamps["local"] = local.timestamp()

        # Calculate max drift between any two sources
        max_drift = 0.0
        warnings = []
        ts_items = list(timestamps.items())

        for i in range(len(ts_items)):
            for j in range(i + 1, len(ts_items)):
                name_a, ts_a = ts_items[i]
                name_b, ts_b = ts_items[j]
                drift = abs(ts_a - ts_b)
                if drift > max_drift:
                    max_drift = drift

                if drift > DRIFT_THRESHOLD_SECONDS:
                    msg = (f"Time drift: {name_a} vs {name_b} = {drift:.1f}s "
                           f"(threshold: {DRIFT_THRESHOLD_SECONDS}s)")
                    warnings.append(msg)

        # Special check: NTP diverging from GPS+blockchain = potential poisoning
        if "ntp" in timestamps and ("gps" in timestamps or "blockchain" in timestamps):
            trusted_sources = []
            if "gps" in timestamps:
                trusted_sources.append(("gps", timestamps["gps"]))
            if "blockchain" in timestamps:
                trusted_sources.append(("blockchain", timestamps["blockchain"]))

            for name, ts in trusted_sources:
                ntp_drift = abs(timestamps["ntp"] - ts)
                if ntp_drift > DRIFT_THRESHOLD_SECONDS:
                    msg = (f"POTENTIAL NTP POISONING: NTP diverges from {name} "
                           f"by {ntp_drift:.1f}s")
                    warnings.append(msg)
                    log.warning(msg)

        if warnings:
            log.warning("Time drift detected: GPS=%s, Blockchain=%s, NTP=%s, Local=%s",
                        sources["gps"], sources["blockchain"],
                        sources["ntp"], sources["local"])

        drift_ok = max_drift <= DRIFT_THRESHOLD_SECONDS

        return {
            "sources": sources,
            "max_drift_seconds": round(max_drift, 3),
            "drift_ok": drift_ok,
            "warnings": warnings,
        }


# ── Singleton ───────────────────────────────────────────────────────────

_instance = None


def get_time_authority(rpc_url=None):
    """Get or create the singleton TimeAuthority instance."""
    global _instance
    if _instance is None:
        _instance = TimeAuthority(rpc_url=rpc_url)
    return _instance


# ── Main demo ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(name)s  %(levelname)s  %(message)s")

    print("=== NEXUS Forensic Time Authority Demo ===\n")

    ta = TimeAuthority()

    # Individual sources
    print("--- Individual time sources ---")

    gps = ta.get_gps_time()
    print(f"  GPS (Flipper Zero): {gps.isoformat() if gps else 'not available'}")

    chain = ta.get_blockchain_time()
    print(f"  Blockchain:         {chain.isoformat() if chain else 'not available'}")

    ntp = ta.get_ntp_time()
    print(f"  NTP:                {ntp.isoformat() if ntp else 'not available'}")

    local = datetime.now(timezone.utc)
    print(f"  Local:              {local.isoformat()}")

    # Authoritative time
    print("\n--- Authoritative time ---")
    auth_time = ta.get_authoritative_time()
    print(f"  Time:   {auth_time.isoformat()}")
    print(f"  Source: {ta.last_source}")

    # Drift validation
    print("\n--- Drift validation ---")
    drift = ta.validate_time_drift()
    print(f"  Max drift: {drift['max_drift_seconds']}s")
    print(f"  Drift OK:  {drift['drift_ok']}")
    if drift["warnings"]:
        for w in drift["warnings"]:
            print(f"  WARNING: {w}")
    else:
        print("  No warnings")

    print(f"\n  Sources:")
    for name, ts in drift["sources"].items():
        print(f"    {name:<12s} {ts or 'N/A'}")

    print("\nDone.")
