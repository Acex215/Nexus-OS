"""
NEXUS OS — Storage Repair Daemon

Monitors shard availability across the IPFS cluster and repairs degraded
files ONLY after sustained absence with degraded redundancy. Repairs are
NOT triggered on every node disconnect — transient outages are expected
and tolerated.

Policy:
  - 72-hour delay before any repair (node will likely return)
  - Minimum redundancy threshold: K+2 = 12 available shards
  - Max 5 repairs per hour (budget cap to prevent bandwidth storms)
  - Circuit breaker PAUSE_REPAIRS halts all repair activity
  - Start with MAX_REPAIRS_PER_HOUR = 0 (log-only mode)

References:
  - erasure_coding.py: RS(10,5) shard encoding, shard map format
  - circuit_breaker.py: PAUSE_REPAIRS breaker
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

log = logging.getLogger("nexus.repair_daemon")

# ── Constants ────────────────────────────────────────────────────────────

REPAIR_DELAY_HOURS = 72
MIN_REDUNDANCY = 12         # K+2 where K=10 (data shards)
MAX_REPAIRS_PER_HOUR = 0    # SAFETY: start at 0 (log only, no actual repairs)

SHARD_MAPS_DIR = Path("/opt/nexus/config/shard_maps")
REPAIR_LOG_PATH = Path("/opt/nexus/logs/repair_requests.jsonl")
DAEMON_STATE_PATH = Path("/opt/nexus/config/repair_daemon_state.json")
IPFS_API = "http://127.0.0.1:5001/api/v0"
GATEWAY_URL = "http://127.0.0.1:5001/api/v0"  # IPFS swarm peers as node list

DATA_SHARDS = 10
PARITY_SHARDS = 5
TOTAL_SHARDS = DATA_SHARDS + PARITY_SHARDS


class RepairDaemon:
    """
    Long-lived daemon that monitors shard health and repairs degraded files
    after sustained absence exceeds REPAIR_DELAY_HOURS.
    """

    def __init__(self, ipfs_api=IPFS_API, max_repairs=MAX_REPAIRS_PER_HOUR,
                 repair_delay_hours=REPAIR_DELAY_HOURS):
        self.ipfs_api = ipfs_api.rstrip("/")
        self.max_repairs = max_repairs
        self.repair_delay_hours = repair_delay_hours

        # {peer_id: first_offline_timestamp} — tracks when a node went offline
        self.offline_nodes = {}
        # {file_id: {available_shards, total_shards, degraded_since}}
        self.file_health = {}
        # Set of known-online peer IDs from last check
        self._last_known_peers = set()
        # Repair budget tracking: list of timestamps of repairs this hour
        self._repair_timestamps = []

        self._load_state()

    # ── State persistence ───────────────────────────────────────────────────

    def _load_state(self):
        """Load daemon state from disk (offline nodes, file health)."""
        if DAEMON_STATE_PATH.exists():
            try:
                with open(DAEMON_STATE_PATH) as f:
                    state = json.load(f)
                self.offline_nodes = state.get("offline_nodes", {})
                self.file_health = state.get("file_health", {})
                self._last_known_peers = set(state.get("last_known_peers", []))
                log.info("Loaded state: %d offline nodes, %d file health records",
                         len(self.offline_nodes), len(self.file_health))
            except (json.JSONDecodeError, OSError) as e:
                log.warning("Failed to load daemon state: %s", e)

    def _save_state(self):
        """Persist daemon state to disk."""
        DAEMON_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "offline_nodes": self.offline_nodes,
            "file_health": self.file_health,
            "last_known_peers": list(self._last_known_peers),
            "last_saved": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with open(DAEMON_STATE_PATH, "w") as f:
                json.dump(state, f, indent=2)
        except OSError as e:
            log.error("Failed to save daemon state: %s", e)

    # ── Node availability ───────────────────────────────────────────────────

    def check_node_availability(self):
        """
        Query IPFS swarm for connected peers. Track nodes going offline
        and nodes coming back online.

        Returns:
            dict: {online: [peer_ids], went_offline: [peer_ids], came_back: [peer_ids]}
        """
        current_peers = set()
        try:
            r = requests.post(
                f"{self.ipfs_api}/swarm/peers",
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            for peer_info in data.get("Peers", []) or []:
                peer_id = peer_info.get("Peer", "")
                if peer_id:
                    current_peers.add(peer_id)
        except Exception as e:
            log.warning("Failed to query IPFS swarm peers: %s", e)
            return {"online": [], "went_offline": [], "came_back": []}

        now = time.time()

        # Nodes that went offline since last check
        went_offline = self._last_known_peers - current_peers
        for peer_id in went_offline:
            if peer_id not in self.offline_nodes:
                self.offline_nodes[peer_id] = now
                log.info("Node went offline: %s", peer_id[:16])

        # Nodes that came back
        came_back = []
        for peer_id in list(self.offline_nodes.keys()):
            if peer_id in current_peers:
                offline_duration = now - self.offline_nodes[peer_id]
                log.info("Node came back: %s (was offline %.1f hours)",
                         peer_id[:16], offline_duration / 3600)
                del self.offline_nodes[peer_id]
                came_back.append(peer_id)

        self._last_known_peers = current_peers
        self._save_state()

        return {
            "online": list(current_peers),
            "went_offline": list(went_offline),
            "came_back": came_back,
        }

    # ── File health assessment ──────────────────────────────────────────────

    def assess_file_health(self):
        """
        For each registered file in shard maps, count how many shards are
        available on currently-online nodes. Flag for repair if degraded
        below MIN_REDUNDANCY for longer than REPAIR_DELAY_HOURS.

        Returns:
            dict: {healthy: int, degraded: int, needs_repair: int, files: [...]}
        """
        if not SHARD_MAPS_DIR.exists():
            return {"healthy": 0, "degraded": 0, "needs_repair": 0, "files": []}

        now = time.time()
        healthy = 0
        degraded = 0
        needs_repair = 0
        file_reports = []

        for map_file in SHARD_MAPS_DIR.glob("*.json"):
            try:
                with open(map_file) as f:
                    shard_map = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            file_id = shard_map.get("file_id", map_file.stem)
            shard_cids = shard_map.get("shard_cids", {})

            # Check availability of each shard via IPFS pin check
            available = 0
            missing_indices = []
            for i in range(TOTAL_SHARDS):
                cid = shard_cids.get(str(i))
                if cid and self._ipfs_pin_check(cid):
                    available += 1
                else:
                    missing_indices.append(i)

            report = {
                "file_id": file_id,
                "available_shards": available,
                "total_shards": TOTAL_SHARDS,
                "missing_indices": missing_indices,
                "status": "healthy",
            }

            if available >= MIN_REDUNDANCY:
                healthy += 1
                # Clear any degradation tracking
                if file_id in self.file_health:
                    del self.file_health[file_id]
            else:
                # Track degradation start time
                if file_id not in self.file_health:
                    self.file_health[file_id] = {
                        "available_shards": available,
                        "total_shards": TOTAL_SHARDS,
                        "degraded_since": now,
                    }
                else:
                    self.file_health[file_id]["available_shards"] = available

                degraded_since = self.file_health[file_id]["degraded_since"]
                hours_degraded = (now - degraded_since) / 3600

                if hours_degraded >= self.repair_delay_hours:
                    needs_repair += 1
                    report["status"] = "needs_repair"
                    report["hours_degraded"] = round(hours_degraded, 1)
                    log.warning("File %s needs repair: %d/%d shards, degraded %.1f hours",
                                file_id[:24], available, TOTAL_SHARDS, hours_degraded)
                else:
                    degraded += 1
                    report["status"] = "degraded"
                    report["hours_degraded"] = round(hours_degraded, 1)
                    log.info("File %s degraded: %d/%d shards, %.1f hours (delay: %d)",
                             file_id[:24], available, TOTAL_SHARDS,
                             hours_degraded, self.repair_delay_hours)

            file_reports.append(report)

        self._save_state()

        return {
            "healthy": healthy,
            "degraded": degraded,
            "needs_repair": needs_repair,
            "files": file_reports,
        }

    def _ipfs_pin_check(self, cid):
        """Check if a CID is pinned (available) locally."""
        try:
            r = requests.post(
                f"{self.ipfs_api}/pin/ls",
                params={"arg": cid, "type": "all"},
                timeout=10,
            )
            return r.status_code == 200
        except Exception:
            return False

    # ── Repair execution ────────────────────────────────────────────────────

    def execute_repairs(self, max_count=None):
        """
        Execute repairs for files that have been degraded beyond the delay
        threshold. Respects circuit breaker and hourly budget cap.

        Args:
            max_count: override max repairs (default: self.max_repairs)

        Returns:
            dict: {attempted: int, succeeded: int, skipped_reason: str|None, repairs: [...]}
        """
        if max_count is None:
            max_count = self.max_repairs

        # Check circuit breaker
        try:
            from circuit_breaker import get_circuit_breaker, PAUSE_REPAIRS
            cb = get_circuit_breaker(log_on_chain=False)
            if cb.is_paused(PAUSE_REPAIRS):
                reason = cb.get_reason(PAUSE_REPAIRS)
                log.info("Repairs paused by circuit breaker: %s", reason)
                return {
                    "attempted": 0, "succeeded": 0,
                    "skipped_reason": f"PAUSE_REPAIRS active: {reason}",
                    "repairs": [],
                }
        except ImportError:
            log.warning("circuit_breaker module not available — skipping CB check")

        # Enforce hourly budget
        now = time.time()
        cutoff = now - 3600
        self._repair_timestamps = [t for t in self._repair_timestamps if t > cutoff]
        budget_remaining = max_count - len(self._repair_timestamps)

        if budget_remaining <= 0:
            log.info("Repair budget exhausted: %d/%d this hour", len(self._repair_timestamps), max_count)
            return {
                "attempted": 0, "succeeded": 0,
                "skipped_reason": f"hourly budget exhausted ({max_count}/{max_count})",
                "repairs": [],
            }

        if max_count == 0:
            # Log-only mode
            flagged = [fid for fid, info in self.file_health.items()
                       if (now - info["degraded_since"]) / 3600 >= self.repair_delay_hours]
            if flagged:
                log.info("LOG-ONLY MODE: %d files would be repaired (MAX_REPAIRS_PER_HOUR=0)", len(flagged))
                for fid in flagged:
                    self._log_repair_request(fid, "log_only", success=False,
                                             note="log-only mode, no repair executed")
            return {
                "attempted": 0, "succeeded": 0,
                "skipped_reason": "log-only mode (MAX_REPAIRS_PER_HOUR=0)",
                "repairs": [{"file_id": fid, "action": "would_repair"} for fid in flagged],
            }

        # Find files needing repair
        flagged_files = []
        for file_id, info in self.file_health.items():
            hours_degraded = (now - info["degraded_since"]) / 3600
            if hours_degraded >= self.repair_delay_hours:
                flagged_files.append((file_id, info))

        repairs = []
        attempted = 0
        succeeded = 0

        for file_id, info in flagged_files[:budget_remaining]:
            attempted += 1
            result = self._repair_file(file_id)
            repairs.append(result)
            if result.get("success"):
                succeeded += 1
                self._repair_timestamps.append(now)
                # Clear degradation tracking on success
                if file_id in self.file_health:
                    del self.file_health[file_id]

        self._save_state()

        return {
            "attempted": attempted,
            "succeeded": succeeded,
            "skipped_reason": None,
            "repairs": repairs,
        }

    def _repair_file(self, file_id):
        """
        Repair a single file by re-encoding missing shards from available ones.

        Steps:
          1. Load shard map
          2. Identify missing shards
          3. Retrieve available shards from IPFS
          4. Re-encode missing shards via Reed-Solomon
          5. Pin new shards to IPFS
          6. Update shard map
          7. Log repair

        Returns:
            dict: {file_id, success, shards_repaired, error}
        """
        # Find shard map file matching this file_id
        shard_map = None
        shard_map_path = None
        if not SHARD_MAPS_DIR.exists():
            return {"file_id": file_id, "success": False, "shards_repaired": 0,
                    "error": "shard maps directory not found"}

        for map_file in SHARD_MAPS_DIR.glob("*.json"):
            try:
                with open(map_file) as f:
                    candidate = json.load(f)
                if candidate.get("file_id") == file_id:
                    shard_map = candidate
                    shard_map_path = map_file
                    break
            except (json.JSONDecodeError, OSError):
                continue

        if shard_map is None:
            self._log_repair_request(file_id, "repair", success=False,
                                     note="shard map not found")
            return {"file_id": file_id, "success": False, "shards_repaired": 0,
                    "error": "shard map not found"}

        shard_cids = shard_map.get("shard_cids", {})
        metadata = shard_map.get("metadata", {})

        # Identify available vs missing shards
        available_shards = {}
        missing_indices = []

        for i in range(TOTAL_SHARDS):
            cid = shard_cids.get(str(i))
            if cid and self._ipfs_pin_check(cid):
                try:
                    r = requests.post(
                        f"{self.ipfs_api}/cat",
                        params={"arg": cid},
                        timeout=30,
                    )
                    r.raise_for_status()
                    available_shards[i] = r.content
                except Exception as e:
                    log.warning("Shard %d fetch failed for %s: %s", i, file_id[:24], e)
                    missing_indices.append(i)
            else:
                missing_indices.append(i)

        if len(available_shards) < DATA_SHARDS:
            self._log_repair_request(file_id, "repair", success=False,
                                     note=f"insufficient shards: {len(available_shards)}/{DATA_SHARDS}")
            return {"file_id": file_id, "success": False, "shards_repaired": 0,
                    "error": f"only {len(available_shards)} shards available, need {DATA_SHARDS}"}

        if not missing_indices:
            return {"file_id": file_id, "success": True, "shards_repaired": 0,
                    "error": None}

        # Re-encode missing shards using Reed-Solomon
        try:
            import reedsolo
            rs = reedsolo.RSCodec(PARITY_SHARDS)
            chunk_size = metadata.get("chunk_size", 0)

            if chunk_size == 0:
                # Infer from available shard size
                sample = next(iter(available_shards.values()))
                chunk_size = len(sample)

            # Build full shard array with None for missing
            all_shards = [None] * TOTAL_SHARDS
            for i, data in available_shards.items():
                all_shards[i] = data

            # RS decode column-by-column to reconstruct missing shards
            reconstructed = [bytearray(chunk_size) for _ in range(TOTAL_SHARDS)]
            for i, data in available_shards.items():
                reconstructed[i] = bytearray(data)

            for pos in range(chunk_size):
                column = bytearray(TOTAL_SHARDS)
                erase_pos = []
                for i in range(TOTAL_SHARDS):
                    if all_shards[i] is not None:
                        column[i] = all_shards[i][pos]
                    else:
                        column[i] = 0
                        erase_pos.append(i)

                decoded = rs.decode(bytes(column), erase_pos=erase_pos)
                # decoded[0] is data portion, full encoded is data+parity
                full_encoded = rs.encode(decoded[0])
                for i in missing_indices:
                    reconstructed[i][pos] = full_encoded[i]

            # Pin reconstructed shards to IPFS
            shards_repaired = 0
            for i in missing_indices:
                try:
                    r = requests.post(
                        f"{self.ipfs_api}/add",
                        files={"file": ("shard", bytes(reconstructed[i]))},
                        params={"pin": "true"},
                        timeout=30,
                    )
                    r.raise_for_status()
                    new_cid = r.json()["Hash"]
                    shard_cids[str(i)] = new_cid
                    shards_repaired += 1
                    log.info("Repaired shard %d for %s → %s", i, file_id[:24], new_cid)
                except Exception as e:
                    log.error("Failed to pin repaired shard %d: %s", i, e)

            # Update shard map on disk
            shard_map["shard_cids"] = shard_cids
            with open(shard_map_path, "w") as f:
                json.dump(shard_map, f, indent=2)

            self._log_repair_request(file_id, "repair", success=True,
                                     note=f"repaired {shards_repaired} shards")

            return {"file_id": file_id, "success": True,
                    "shards_repaired": shards_repaired, "error": None}

        except Exception as e:
            log.error("Repair failed for %s: %s", file_id[:24], e)
            self._log_repair_request(file_id, "repair", success=False, note=str(e))
            return {"file_id": file_id, "success": False, "shards_repaired": 0,
                    "error": str(e)}

    def _log_repair_request(self, file_id, action, success, note=""):
        """Append a repair event to the repair log."""
        REPAIR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": time.time(),
            "datetime": datetime.now(timezone.utc).isoformat(),
            "file_id": file_id,
            "action": action,
            "success": success,
            "note": note,
        }
        try:
            with open(REPAIR_LOG_PATH, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as e:
            log.error("Failed to write repair log: %s", e)

    # ── Status ──────────────────────────────────────────────────────────────

    def get_repair_status(self):
        """
        Current repair daemon status.

        Returns:
            dict: {files_degraded, files_pending_repair, repairs_executed_today,
                   nodes_offline: [{peer_id, offline_since, hours_offline}]}
        """
        now = time.time()

        files_degraded = 0
        files_pending_repair = 0
        for file_id, info in self.file_health.items():
            hours_degraded = (now - info["degraded_since"]) / 3600
            if hours_degraded >= self.repair_delay_hours:
                files_pending_repair += 1
            else:
                files_degraded += 1

        # Count repairs executed today
        repairs_today = 0
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        if REPAIR_LOG_PATH.exists():
            try:
                with open(REPAIR_LOG_PATH) as f:
                    for line in f:
                        try:
                            entry = json.loads(line.strip())
                            if (entry.get("timestamp", 0) >= today_start
                                    and entry.get("success")):
                                repairs_today += 1
                        except json.JSONDecodeError:
                            continue
            except OSError:
                pass

        nodes_offline = []
        for peer_id, offline_since in self.offline_nodes.items():
            nodes_offline.append({
                "peer_id": peer_id,
                "offline_since": datetime.fromtimestamp(
                    offline_since, tz=timezone.utc
                ).isoformat(),
                "hours_offline": round((now - offline_since) / 3600, 1),
            })
        nodes_offline.sort(key=lambda x: x["hours_offline"], reverse=True)

        return {
            "files_degraded": files_degraded,
            "files_pending_repair": files_pending_repair,
            "repairs_executed_today": repairs_today,
            "max_repairs_per_hour": self.max_repairs,
            "mode": "log-only" if self.max_repairs == 0 else "active",
            "nodes_offline": nodes_offline,
        }

    # ── Main loop ───────────────────────────────────────────────────────────

    async def run_loop(self, interval_minutes=30):
        """
        Main daemon loop. Runs indefinitely:
          1. Check node availability
          2. Assess file health
          3. Execute repairs (if budget allows)

        Args:
            interval_minutes: check interval (default 30)
        """
        log.info("Repair daemon starting (interval=%dm, max_repairs=%d/hr, delay=%dh)",
                 interval_minutes, self.max_repairs, self.repair_delay_hours)

        while True:
            try:
                log.info("=== Repair daemon cycle start ===")

                # Step 1: check node availability
                avail = self.check_node_availability()
                log.info("Nodes: %d online, %d went offline, %d came back, %d tracked offline",
                         len(avail["online"]), len(avail["went_offline"]),
                         len(avail["came_back"]), len(self.offline_nodes))

                # Step 2: assess file health
                health = self.assess_file_health()
                log.info("Files: %d healthy, %d degraded, %d needs repair",
                         health["healthy"], health["degraded"], health["needs_repair"])

                # Step 3: execute repairs
                if health["needs_repair"] > 0:
                    result = self.execute_repairs()
                    log.info("Repairs: attempted=%d, succeeded=%d, skipped=%s",
                             result["attempted"], result["succeeded"],
                             result["skipped_reason"] or "none")

                # Log status
                status = self.get_repair_status()
                log.info("Status: %d degraded, %d pending repair, %d repaired today, mode=%s",
                         status["files_degraded"], status["files_pending_repair"],
                         status["repairs_executed_today"], status["mode"])

            except Exception as e:
                log.error("Repair daemon cycle error: %s", e, exc_info=True)

            await asyncio.sleep(interval_minutes * 60)


# ── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    import argparse

    parser = argparse.ArgumentParser(description="NEXUS Storage Repair Daemon")
    parser.add_argument("--interval", type=int, default=30,
                        help="Check interval in minutes (default: 30)")
    parser.add_argument("--max-repairs", type=int, default=MAX_REPAIRS_PER_HOUR,
                        help="Max repairs per hour (default: 0 = log-only)")
    parser.add_argument("--delay", type=int, default=REPAIR_DELAY_HOURS,
                        help="Hours to wait before repairing (default: 72)")
    parser.add_argument("--once", action="store_true",
                        help="Run one cycle and exit (for testing)")
    args = parser.parse_args()

    daemon = RepairDaemon(
        max_repairs=args.max_repairs,
        repair_delay_hours=args.delay,
    )

    if args.once:
        print("=== NEXUS Repair Daemon (single cycle) ===\n")

        print("--- Node Availability ---")
        avail = daemon.check_node_availability()
        print(f"  Online: {len(avail['online'])} peers")
        print(f"  Went offline: {len(avail['went_offline'])}")
        print(f"  Came back: {len(avail['came_back'])}")
        print(f"  Tracked offline: {len(daemon.offline_nodes)}")

        print("\n--- File Health ---")
        health = daemon.assess_file_health()
        print(f"  Healthy: {health['healthy']}")
        print(f"  Degraded: {health['degraded']}")
        print(f"  Needs repair: {health['needs_repair']}")
        for fr in health["files"]:
            if fr["status"] != "healthy":
                print(f"    {fr['file_id'][:32]}... {fr['available_shards']}/{fr['total_shards']} "
                      f"[{fr['status']}] {fr.get('hours_degraded', 0):.1f}h")

        print("\n--- Repair Execution ---")
        result = daemon.execute_repairs()
        print(f"  Attempted: {result['attempted']}")
        print(f"  Succeeded: {result['succeeded']}")
        if result["skipped_reason"]:
            print(f"  Skipped: {result['skipped_reason']}")

        print("\n--- Status ---")
        status = daemon.get_repair_status()
        print(f"  Mode: {status['mode']}")
        print(f"  Files degraded: {status['files_degraded']}")
        print(f"  Files pending repair: {status['files_pending_repair']}")
        print(f"  Repairs today: {status['repairs_executed_today']}")
        print(f"  Nodes offline: {len(status['nodes_offline'])}")
        for n in status["nodes_offline"][:5]:
            print(f"    {n['peer_id'][:16]}... offline {n['hours_offline']}h")

        print("\nDone.")
    else:
        asyncio.run(daemon.run_loop(interval_minutes=args.interval))
