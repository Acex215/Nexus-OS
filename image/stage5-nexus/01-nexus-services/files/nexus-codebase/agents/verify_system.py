#!/usr/bin/env python3
"""NEXUS OS full system health verification."""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/opt/nexus/agents")

from agent_registry import AGENT_REGISTRY
from blockchain_logger import get_blockchain_logger, reset_blockchain_logger


def check_hierarchy_running() -> bool:
    """Check if hierarchy_manager.py is running."""
    print("\n  Hierarchy Manager Status")
    print("=" * 55)

    pid_file = Path("/opt/nexus/agents/hierarchy.pid")
    if not pid_file.exists():
        # Also check via pgrep
        import subprocess
        result = subprocess.run(
            ["pgrep", "-f", "hierarchy_manager"],
            capture_output=True, text=True,
        )
        if result.stdout.strip():
            pids = result.stdout.strip().split("\n")
            print(f"  [OK]  Hierarchy running (PIDs: {', '.join(pids)}) — no PID file")
            return True
        print("  [FAIL] Hierarchy manager not running")
        return False

    pid = int(pid_file.read_text().strip())
    try:
        os.kill(pid, 0)
        print(f"  [OK]  Hierarchy manager running (PID: {pid})")
        return True
    except OSError:
        print(f"  [FAIL] Process {pid} not running (stale PID file)")
        return False


def check_log_activity() -> bool:
    """Check recent hierarchy log activity."""
    print("\n  Log Activity")
    print("=" * 55)

    log_path = Path("/opt/nexus/agents/logs/hierarchy.log")
    if not log_path.exists():
        # Check for timestamped logs
        logs = sorted(Path("/opt/nexus/agents/logs").glob("hierarchy*.log"))
        if logs:
            log_path = logs[-1]
        else:
            print("  [FAIL] No hierarchy log files found")
            return False

    mtime = datetime.fromtimestamp(log_path.stat().st_mtime)
    age_s = (datetime.now() - mtime).total_seconds()
    print(f"  [OK]  Log: {log_path.name} (updated {int(age_s)}s ago)")

    # Count connected bots from log
    connected = set()
    with open(log_path) as f:
        for line in f:
            if "Ready:" in line and "bot." in line:
                # Extract agent_id from "bot.ceo"
                parts = line.split("bot.")
                if len(parts) >= 2:
                    aid = parts[1].split()[0].strip()
                    connected.add(aid)
            elif "ONLINE" in line:
                parts = line.split()
                for p in parts:
                    if p in AGENT_REGISTRY:
                        connected.add(p)

    webhook_count = 0
    for aid, cfg in AGENT_REGISTRY.items():
        token = os.getenv(f"{aid.upper()}_TOKEN", "")
        if not token or token == "WEBHOOK_FALLBACK":
            webhook_count += 1

    print(f"  [OK]  Bots connected: {len(connected)}")
    print(f"         Webhook fallback: {webhook_count}")

    if len(connected) >= 20:
        print(f"  [OK]  Sufficient bots online (>= 20)")
        return True
    elif len(connected) >= 1:
        print(f"  [WARN] Only {len(connected)} bots connected")
        return True
    else:
        print(f"  [FAIL] No bots connected")
        return False


def check_decision_logs() -> bool:
    """Check local decision JSONL logs."""
    print("\n  Decision Logs")
    print("=" * 55)

    log_dir = Path("/opt/nexus/agents/logs/decisions")
    if not log_dir.exists():
        print("  [WARN] Decision log directory missing")
        return True  # Not a hard failure

    jsonl_files = list(log_dir.glob("*.jsonl"))
    if not jsonl_files:
        print("  [INFO] No decisions logged yet")
        return True

    total = 0
    total_ect = 0
    with_tx = 0
    agents_seen = set()

    for f in jsonl_files:
        for line in open(f):
            try:
                entry = json.loads(line)
                total += 1
                total_ect += entry.get("ect_cost", 0)
                agents_seen.add(entry.get("agent_id", "?"))
                if entry.get("tx_hash"):
                    with_tx += 1
            except json.JSONDecodeError:
                pass

    print(f"  [OK]  {total} decisions logged across {len(jsonl_files)} files")
    print(f"         {with_tx}/{total} have blockchain tx hash")
    print(f"         {total_ect} total ECT spent")
    print(f"         Agents: {', '.join(sorted(agents_seen))}")
    return True


async def check_blockchain() -> bool:
    """Check blockchain connectivity and ReasoningLedger."""
    print("\n  Blockchain Verification")
    print("=" * 55)

    reset_blockchain_logger()
    bc = get_blockchain_logger()

    if not bc.is_connected():
        print("  [FAIL] Not connected to Geth RPC")
        return False
    print("  [OK]  Connected to Geth RPC")

    count = bc.get_entry_count()
    if count < 0:
        print("  [FAIL] Cannot read ReasoningLedger")
        return False
    print(f"  [OK]  ReasoningLedger entries: {count}")

    if count > 0:
        latest = bc.get_latest_entry()
        if latest:
            print(f"         Latest: {latest['decision'][:60]}...")
            print(f"         Hash:   {latest['reasoning'][:32]}...")
            ts = latest["timestamp"]
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            age = (datetime.now(timezone.utc) - dt).total_seconds()
            print(f"         Age:    {int(age)}s ago")

    pending = len(bc.pending_logs)
    if pending:
        print(f"  [WARN] {pending} pending blockchain logs")
    else:
        print(f"  [OK]  No pending logs")

    return True


def check_agent_tokens() -> bool:
    """Verify bot tokens are loadable."""
    print("\n  Agent Tokens")
    print("=" * 55)

    from dotenv import load_dotenv
    load_dotenv("/opt/nexus/agents/.env")

    active = 0
    webhook = 0
    missing = []

    for aid in AGENT_REGISTRY:
        env_key = f"{aid.upper()}_TOKEN"
        token = os.getenv(env_key, "")
        if not token:
            missing.append(aid)
        elif token == "WEBHOOK_FALLBACK":
            webhook += 1
        else:
            active += 1

    print(f"  [OK]  Active tokens: {active}")
    print(f"  [OK]  Webhook fallback: {webhook}")
    if missing:
        print(f"  [WARN] Missing tokens: {', '.join(missing)}")
    else:
        print(f"  [OK]  All 30 agents have tokens")

    return active >= 20


async def main():
    print()
    print("=" * 55)
    print("  NEXUS OS Full System Verification")
    print("=" * 55)

    results = {}
    results["Agent Tokens"] = check_agent_tokens()
    results["Hierarchy Running"] = check_hierarchy_running()
    results["Log Activity"] = check_log_activity()
    results["Decision Logs"] = check_decision_logs()
    results["Blockchain"] = await check_blockchain()

    print()
    print("=" * 55)
    print("  Summary")
    print("=" * 55)

    passed = 0
    for name, ok in results.items():
        status = "[OK]  " if ok else "[FAIL]"
        print(f"  {status} {name}")
        if ok:
            passed += 1

    total = len(results)
    print(f"\n  {passed}/{total} checks passed")

    if passed == total:
        print("\n  All systems operational!")
    else:
        print("\n  Some checks failed — review output above")

    return passed == total


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
