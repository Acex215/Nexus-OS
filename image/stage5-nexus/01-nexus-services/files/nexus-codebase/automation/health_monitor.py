#!/usr/bin/env python3
"""NEXUS OS CAF — Health Monitor

Runs cluster-wide health checks, stores results in world_model.db,
detects status transitions, and provides compact summaries for context packets.

Public API:
    run_health_checks()                -> list[dict]
    store_health_results(results)      -> None
    detect_transitions(current)        -> list[dict]
    get_health_summary()               -> str
    update_project_state()             -> None
"""

import json
import logging
import re
import shlex
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger("health_monitor")

# ── Paths / config ─────────────────────────────────────────────────────────────

DB_PATH           = "/mnt/nexus-nas/knowledge/world_model.db"
PROJECT_STATE     = "/opt/nexus/automation/project_state.json"
SSH_TIMEOUT       = 10   # seconds per SSH command
HTTP_TIMEOUT      =  5   # seconds per HTTP health probe
SSH_OPTS          = "-o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=8"

NODE_IPS = {
    "nexus-master":  "10.0.20.3",
    "nexus-ai":      "10.0.20.4",
    "nexus-storage": "10.0.20.11",
    "nexus-ai2":     "10.0.20.6",
    "nexus-admin":   None,          # local
    "thinkpad":      "10.0.30.2",
}

GETH_NODES   = ["nexus-master", "nexus-ai", "nexus-storage"]
IPFS_NODES   = ["nexus-master", "nexus-ai", "nexus-storage", "nexus-admin"]
DISK_NODES   = ["nexus-master", "nexus-ai", "nexus-storage", "nexus-ai2", "nexus-admin"]

# ── DB helpers ─────────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS service_health (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            node_name    TEXT    NOT NULL,
            service_name TEXT    NOT NULL,
            status       TEXT    NOT NULL,
            extra_json   TEXT    DEFAULT '{}',
            timestamp    TEXT    NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sh_ts
        ON service_health(timestamp DESC)
    """)
    conn.commit()
    return conn


def _rec(node: str, service: str, status: str, extra: dict = None) -> dict:
    return {
        "node_name":    node,
        "service_name": service,
        "status":       status,
        "extra_json":   json.dumps(extra or {}),
        "timestamp":    datetime.utcnow().isoformat(),
    }


# ── SSH helpers ────────────────────────────────────────────────────────────────

def _ssh(node: str, command: str) -> Optional[str]:
    """Run command on node via SSH (or locally for nexus-admin).

    Returns stdout strip on success, None if SSH fails or times out.
    """
    ip = NODE_IPS.get(node)
    if ip is None:
        # Local execution
        try:
            r = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=SSH_TIMEOUT,
            )
            return r.stdout.strip() if r.returncode == 0 else None
        except subprocess.TimeoutExpired:
            return None
        except Exception:
            return None

    full_cmd = f"ssh {SSH_OPTS} mhuraibi@{ip} {shlex.quote(command)}"
    try:
        r = subprocess.run(
            full_cmd, shell=True, capture_output=True, text=True,
            timeout=SSH_TIMEOUT + 5,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except subprocess.TimeoutExpired:
        log.warning("SSH timeout: %s@%s", node, command[:40])
        return None
    except Exception as e:
        log.warning("SSH error %s: %s", node, e)
        return None


def _ssh_reachable(node: str) -> bool:
    """Quick reachability check (hostname command)."""
    return _ssh(node, "hostname") is not None


# ── Individual checks ──────────────────────────────────────────────────────────

def _check_geth(results: list) -> None:
    for node in GETH_NODES:
        if not _ssh_reachable(node):
            results.append(_rec(node, "geth", "unreachable"))
            continue
        raw = _ssh(
            node,
            "sudo geth attach --exec 'admin.peers.length' /opt/nexus/blockchain/geth.ipc 2>/dev/null",
        )
        if raw is None:
            results.append(_rec(node, "geth", "failed", {"reason": "attach failed"}))
            continue
        try:
            peers = int(raw.strip())
        except ValueError:
            results.append(_rec(node, "geth", "failed", {"reason": f"bad output: {raw[:40]}"}))
            continue
        status = "active" if peers >= 2 else "degraded"
        results.append(_rec(node, "geth", status, {"peers": peers}))


def _check_k3s(results: list) -> None:
    node = "nexus-master"
    if not _ssh_reachable(node):
        results.append(_rec(node, "k3s", "unreachable"))
        return
    raw = _ssh(node, "sudo kubectl get nodes --no-headers 2>/dev/null")
    if raw is None:
        results.append(_rec(node, "k3s", "failed", {"reason": "kubectl failed"}))
        return

    lines = [l for l in raw.splitlines() if l.strip()]
    total   = len(lines)
    not_ready = [l for l in lines if "NotReady" in l]
    status  = "degraded" if not_ready else "active"
    results.append(_rec(node, "k3s", status, {
        "total_nodes": total,
        "not_ready":   [l.split()[0] for l in not_ready],
    }))


def _check_ipfs(results: list) -> None:
    for node in IPFS_NODES:
        if not _ssh_reachable(node):
            results.append(_rec(node, "ipfs", "unreachable"))
            continue
        raw = _ssh(node, "IPFS_PATH=/opt/nexus/ipfs ipfs swarm peers 2>/dev/null | wc -l")
        if raw is None:
            results.append(_rec(node, "ipfs", "failed", {"reason": "command failed"}))
            continue
        try:
            peer_count = int(raw.strip())
        except ValueError:
            results.append(_rec(node, "ipfs", "failed", {"reason": f"bad output: {raw[:40]}"}))
            continue
        status = "failed" if peer_count == 0 else ("degraded" if peer_count < 3 else "active")
        results.append(_rec(node, "ipfs", status, {"peers": peer_count}))


def _check_http(node: str, service: str, url: str,
                down_status: str = "failed") -> dict:
    """Generic HTTP health check."""
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT)
        status = "active" if r.status_code == 200 else "degraded"
        return _rec(node, service, status, {"http_status": r.status_code})
    except requests.exceptions.Timeout:
        return _rec(node, service, down_status, {"reason": "timeout"})
    except Exception as e:
        return _rec(node, service, down_status, {"reason": str(e)[:80]})


def _check_nfs(results: list) -> None:
    raw = _ssh("nexus-admin", "mount | grep nexus-nas")
    status = "active" if (raw and raw.strip()) else "failed"
    results.append(_rec("nexus-admin", "nfs_mount", status,
                        {"mount_line": (raw or "")[:120]}))


def _check_disk(results: list) -> None:
    for node in DISK_NODES:
        if not _ssh_reachable(node):
            results.append(_rec(node, "disk_root", "unreachable"))
            continue
        raw = _ssh(node, "df -h / | tail -1 | awk '{print $5}'")
        if raw is None:
            results.append(_rec(node, "disk_root", "failed", {"reason": "df failed"}))
            continue
        m = re.search(r"(\d+)", raw)
        if not m:
            results.append(_rec(node, "disk_root", "failed",
                               {"reason": f"unparseable: {raw[:20]}"}))
            continue
        pct = int(m.group(1))
        status = "degraded" if pct > 90 else "active"
        results.append(_rec(node, "disk_root", status, {"used_pct": pct}))


def _check_systemd(results: list) -> None:
    """Per-node systemd service status sweep."""
    checks = {
        "nexus-master":  ["nexus-geth.service", "k3s.service",       "ipfs.service"],
        "nexus-ai":      ["nexus-geth.service", "ipfs.service"],
        "nexus-storage": ["nexus-geth.service", "ipfs.service",       "k3s-agent.service"],
        "nexus-ai2":     ["ollama.service",      "k3s-agent.service"],
        "nexus-admin":   ["nexus-orchestrator.service", "chromadb.service",
                          "ipfs.service", "k3s-agent.service"],
    }
    for node, services in checks.items():
        if not _ssh_reachable(node):
            for svc in services:
                results.append(_rec(node, f"systemd:{svc}", "unreachable"))
            continue
        svc_list = " ".join(services)
        raw = _ssh(node, f"systemctl is-active {svc_list} 2>/dev/null")
        if raw is None:
            for svc in services:
                results.append(_rec(node, f"systemd:{svc}", "unknown"))
            continue
        lines = raw.splitlines()
        for i, svc in enumerate(services):
            if i < len(lines):
                state = lines[i].strip()
                status = "active" if state == "active" else (
                    "inactive" if state in ("inactive", "dead") else "failed"
                )
                results.append(_rec(node, f"systemd:{svc}", status, {"systemd_state": state}))
            else:
                results.append(_rec(node, f"systemd:{svc}", "unknown"))


# ── Public API ─────────────────────────────────────────────────────────────────

def run_health_checks() -> list[dict]:
    """Run all cluster health checks. Returns list of health record dicts."""
    results: list[dict] = []

    _check_geth(results)
    _check_k3s(results)
    _check_ipfs(results)

    # Ollama (nexus-ai2)
    results.append(_check_http("nexus-ai2", "ollama",
                               "http://10.0.20.6:11434/api/tags"))

    # LM Studio (ThinkPad — intermittent is expected)
    results.append(_check_http("thinkpad", "lm_studio",
                               "http://10.0.30.2:1234/v1/models",
                               down_status="inactive"))

    # ChromaDB (localhost)
    results.append(_check_http("nexus-admin", "chromadb",
                               "http://localhost:8000/api/v2/heartbeat"))

    _check_nfs(results)
    _check_disk(results)
    _check_systemd(results)

    log.info("run_health_checks: %d records collected", len(results))
    return results


def store_health_results(results: list[dict]) -> None:
    """Persist results into world_model.db service_health table."""
    if not results:
        return
    conn = _get_conn()
    try:
        conn.executemany(
            "INSERT INTO service_health (node_name, service_name, status, extra_json, timestamp) "
            "VALUES (:node_name, :service_name, :status, :extra_json, :timestamp)",
            results,
        )
        conn.commit()
        log.debug("Stored %d health records", len(results))
    finally:
        conn.close()


def detect_transitions(current: list[dict]) -> list[dict]:
    """Compare current run against the previous run stored in the DB.

    Returns list of dicts for entries where status changed:
        {"node": str, "service": str, "was": str, "now": str}
    """
    conn = _get_conn()
    transitions: list[dict] = []

    try:
        # Build {(node, service): status} for current run
        current_map = {
            (r["node_name"], r["service_name"]): r["status"]
            for r in current
        }

        # Fetch last known status per (node, service) before this run
        cur = conn.execute("""
            SELECT node_name, service_name, status
            FROM service_health
            WHERE timestamp < ?
            GROUP BY node_name, service_name
            HAVING timestamp = MAX(timestamp)
        """, (min(r["timestamp"] for r in current),))

        for row in cur.fetchall():
            node, service, prev_status = row
            new_status = current_map.get((node, service))
            if new_status and new_status != prev_status:
                transitions.append({
                    "node":    node,
                    "service": service,
                    "was":     prev_status,
                    "now":     new_status,
                })
    finally:
        conn.close()

    if transitions:
        log.info("detect_transitions: %d status change(s)", len(transitions))
    return transitions


def get_health_summary() -> str:
    """Return a compact one-line cluster health summary for context injection."""
    conn = _get_conn()
    try:
        # Latest status per (node, service)
        cur = conn.execute("""
            SELECT node_name, service_name, status, extra_json
            FROM service_health
            WHERE (node_name, service_name, timestamp) IN (
                SELECT node_name, service_name, MAX(timestamp)
                FROM service_health
                GROUP BY node_name, service_name
            )
        """)
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return "Cluster Health: no data yet"

    # Index by (node, service)
    latest: dict[tuple, dict] = {}
    for node, service, status, extra_json in rows:
        try:
            extra = json.loads(extra_json or "{}")
        except Exception:
            extra = {}
        latest[(node, service)] = {"status": status, **extra}

    # --- Geth ---
    geth_ok = sum(
        1 for n in GETH_NODES
        if latest.get((n, "geth"), {}).get("status") == "active"
    )
    geth_peers = [
        latest.get((n, "geth"), {}).get("peers", "?")
        for n in GETH_NODES
    ]
    geth_str = f"Geth {geth_ok}/{len(GETH_NODES)} validators OK (peers: {geth_peers})"

    # --- K3s ---
    k3s = latest.get(("nexus-master", "k3s"), {})
    k3s_str = (
        f"K3s {k3s.get('total_nodes','?')} nodes"
        + (" (DEGRADED: " + str(k3s.get("not_ready", [])) + ")"
           if k3s.get("not_ready") else " Ready")
    )

    # --- IPFS ---
    ipfs_ok = sum(
        1 for n in IPFS_NODES
        if latest.get((n, "ipfs"), {}).get("status") in ("active", "degraded")
    )
    ipfs_str = f"IPFS {ipfs_ok}/{len(IPFS_NODES)} nodes peered"

    # --- Services ---
    ollama_st  = latest.get(("nexus-ai2",   "ollama"),    {}).get("status", "unknown")
    lmstudio_st= latest.get(("thinkpad",    "lm_studio"), {}).get("status", "unknown")
    chroma_st  = latest.get(("nexus-admin", "chromadb"),  {}).get("status", "unknown")
    nfs_st     = latest.get(("nexus-admin", "nfs_mount"), {}).get("status", "unknown")

    # --- Disk ---
    disk_parts = []
    for n in DISK_NODES:
        pct = latest.get((n, "disk_root"), {}).get("used_pct")
        if pct is not None:
            disk_parts.append(f"{n} {pct}%")
    disk_str = "Disk: " + (", ".join(disk_parts) or "no data")

    parts = [
        geth_str, k3s_str, ipfs_str,
        f"Ollama {ollama_st}",
        f"LM Studio {lmstudio_st}",
        f"NFS {nfs_st}",
        f"ChromaDB {chroma_st}",
        disk_str,
    ]
    return "Cluster Health: " + " | ".join(parts)


def update_project_state() -> None:
    """Merge current health snapshot into project_state.json."""
    state_path = Path(PROJECT_STATE)
    try:
        state = json.loads(state_path.read_text())
    except Exception:
        state = {}

    # Build a compact health snapshot
    conn = _get_conn()
    try:
        cur = conn.execute("""
            SELECT node_name, service_name, status, extra_json
            FROM service_health
            WHERE (node_name, service_name, timestamp) IN (
                SELECT node_name, service_name, MAX(timestamp)
                FROM service_health
                GROUP BY node_name, service_name
            )
        """)
        rows = cur.fetchall()
    finally:
        conn.close()

    snapshot: dict = {}
    for node, service, status, extra_json in rows:
        snapshot.setdefault(node, {})[service] = status

    state["health_snapshot"]  = snapshot
    state["health_updated"]   = datetime.utcnow().isoformat()
    state["last_updated"]     = datetime.utcnow().isoformat()
    state["last_updated_by"]  = "health_monitor"

    # Merge inference status from live checks
    if "inference" in state:
        lm = snapshot.get("thinkpad", {}).get("lm_studio")
        ol = snapshot.get("nexus-ai2", {}).get("ollama")
        if lm:
            state["inference"]["tier_1"]["status"] = lm
        if ol:
            state["inference"]["tier_2"]["status"] = ol

    try:
        state_path.write_text(json.dumps(state, indent=2))
        log.debug("project_state.json updated with health snapshot")
    except Exception as e:
        log.error("Failed to update project_state.json: %s", e)
