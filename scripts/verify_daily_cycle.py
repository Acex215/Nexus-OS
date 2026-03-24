#!/usr/bin/env python3
"""NEXUS Daily Cycle Verification — system integration test.

Checks that all components of the daily cycle are functioning end-to-end.
When all 10 checks pass, the core architecture is working.

Usage: cd /opt/nexus && python3 scripts/verify_daily_cycle.py
"""
import json
import sys
import time
import traceback
import urllib.request

sys.path.insert(0, '/opt/nexus')

DEPLOYER = '0x817B0842B208B76A7665948F8D1A0592F9b1e958'
DASHBOARD_URL = 'http://localhost:8768'
GATEWAY_URL = 'http://10.0.20.1:8766'

PASS = '\u2713'
FAIL = '\u2717'

results = []


def check(name, fn):
    """Run a check function, capture pass/fail and detail string."""
    try:
        ok, detail = fn()
        results.append((name, ok, detail))
        mark = PASS if ok else FAIL
        print(f"  {mark} {name}: {detail}")
    except Exception as e:
        results.append((name, False, str(e)))
        print(f"  {FAIL} {name}: {e}")


# ── 1. TokenManager: Can mint and read ECT? ──────────────────────────────

def check_token_manager():
    from libnexus.token_client import TokenClient
    tc = TokenClient(wallet=DEPLOYER)
    bal = tc.get_balances(DEPLOYER)
    ect = bal['ect']
    rst = bal['rst']
    return True, f"ECT={ect} RST={rst}"


# ── 2. TemporalScheduler: Current bin ID resolves? ───────────────────────

def check_temporal_scheduler():
    from libnexus.kernel import NexusKernel
    k = NexusKernel(wallet=DEPLOYER)
    if k.temporal_scheduler is None:
        return False, "TemporalScheduler not deployed"
    bin_id = k.get_current_bin_id()
    return True, f"bin_id=0x{bin_id.hex()[:16]}..."


# ── 3. FlockCoordinator: Current epoch active? ───────────────────────────

def check_flock_epoch():
    from libnexus.flock_client import FlockClient
    fc = FlockClient(wallet=DEPLOYER)
    epoch = fc.get_current_epoch()
    eid = epoch['epochId']
    finalized = epoch['finalized']
    subs = epoch['submissionCount']
    if eid == 0:
        return False, "No active epoch (epochId=0)"
    status = "finalized" if finalized else "active"
    return True, f"epoch={eid} {status} submissions={subs}"


# ── 4. Daily salt: Different from previous epoch? ────────────────────────

def check_daily_salt():
    from libnexus.flock_client import FlockClient
    fc = FlockClient(wallet=DEPLOYER)
    epoch = fc.get_current_epoch()
    eid = epoch['epochId']
    current_salt = epoch['dailySalt']
    if eid <= 1:
        return True, f"epoch={eid} salt={current_salt[:18]}... (first epoch, no previous to compare)"
    prev_salt = fc.get_daily_salt(eid - 1)
    different = current_salt != prev_salt
    if not different:
        return False, f"epoch {eid} salt == epoch {eid-1} salt"
    return True, f"epoch {eid} salt != epoch {eid-1} salt"


# ── 5. Feature collector: Generates 128-dim vector? ──────────────────────

def check_feature_collector():
    from agents.feature_collector import FeatureCollector
    fc = FeatureCollector()
    raw = fc.collect_raw_signals()
    features = fc.extract_features(raw)
    shape = features.shape
    ok = shape == (128,) and features.dtype.name == 'float32'
    return ok, f"shape={shape} dtype={features.dtype}"


# ── 6. Obfuscation: Same features + different salt = different hash? ─────

def check_obfuscation():
    from agents.feature_collector import FeatureCollector
    fc = FeatureCollector()
    raw = fc.collect_raw_signals()
    features = fc.extract_features(raw)
    salt_a = 'aa' * 32
    salt_b = 'bb' * 32
    hash_a = fc.obfuscate(features, salt_a)
    hash_b = fc.obfuscate(features, salt_b)
    different = hash_a != hash_b
    return different, f"hash_a=0x{hash_a.hex()[:12]}... hash_b=0x{hash_b.hex()[:12]}... different={different}"


# ── 7. Gradient submission: Can submit to FlockCoordinator? ───────────────

def check_gradient_submission():
    from libnexus.flock_client import FlockClient
    from agents.feature_collector import FeatureCollector
    fc_flock = FlockClient(wallet=DEPLOYER)
    fc_feat = FeatureCollector()

    epoch = fc_flock.get_current_epoch()
    if epoch['epochId'] == 0:
        return False, "No active epoch"
    if epoch['finalized']:
        return False, f"Epoch {epoch['epochId']} already finalized"

    raw = fc_feat.collect_raw_signals()
    features = fc_feat.extract_features(raw)
    salt_hex = epoch['dailySalt'][2:] if epoch['dailySalt'].startswith('0x') else epoch['dailySalt']
    gradient_bytes = fc_feat.get_epoch_gradient(bytes.fromhex(salt_hex))
    gradient_hash = FlockClient.generate_gradient_hash(gradient_bytes)
    result = fc_flock.submit_gradient(gradient_hash, 7500)
    return True, f"tx={result['tx_hash'][:16]}... block={result['block']} gas={result['gas_used']}"


# ── 8. Node agents: At least 1 node connected to Gateway? ────────────────

def check_gateway_nodes():
    req = urllib.request.Request(f"{GATEWAY_URL}/nodes", method='GET')
    req.add_header('Accept', 'application/json')
    resp = urllib.request.urlopen(req, timeout=5)
    data = json.loads(resp.read())
    nodes = data if isinstance(data, list) else data.get('nodes', [])
    connected = [n for n in nodes if n.get('connected')]
    total = len(nodes)
    count = len(connected)
    return count >= 1, f"{count}/{total} nodes connected"


# ── 9. ReasoningLedger: Entry count > 0? ─────────────────────────────────

def check_reasoning_ledger():
    from libnexus.kernel import NexusKernel
    k = NexusKernel(wallet=DEPLOYER)
    count = k.get_entry_count()
    return count > 0, f"entry_count={count}"


# ── 10. Dashboard API: /api/health returns 200? ──────────────────────────

def check_dashboard_api():
    req = urllib.request.Request(f"{DASHBOARD_URL}/api/health", method='GET')
    req.add_header('Accept', 'application/json')
    resp = urllib.request.urlopen(req, timeout=5)
    status = resp.getcode()
    data = json.loads(resp.read())
    has_error = 'error' in data
    ok = status == 200 and not has_error
    detail = f"status={status}"
    if has_error:
        detail += f" error={data['error']}"
    return ok, detail


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    print()
    print("NEXUS Daily Cycle Verification")
    print("=" * 50)
    print()

    check(" 1. TokenManager balances",       check_token_manager)
    check(" 2. TemporalScheduler bin ID",     check_temporal_scheduler)
    check(" 3. FlockCoordinator epoch",       check_flock_epoch)
    check(" 4. Daily salt uniqueness",        check_daily_salt)
    check(" 5. Feature collector (128-dim)",  check_feature_collector)
    check(" 6. Obfuscation (salt diversity)", check_obfuscation)
    check(" 7. Gradient submission",          check_gradient_submission)
    check(" 8. Gateway node connectivity",    check_gateway_nodes)
    check(" 9. ReasoningLedger entries",      check_reasoning_ledger)
    check("10. Dashboard API health",         check_dashboard_api)

    print()
    print("=" * 50)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"NEXUS Daily Cycle: {passed}/{total} checks passed")
    print()

    if passed < total:
        print("Failed checks:")
        for name, ok, detail in results:
            if not ok:
                print(f"  {FAIL} {name}: {detail}")
        print()

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
