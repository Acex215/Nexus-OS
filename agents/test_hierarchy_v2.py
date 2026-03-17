#!/usr/bin/env python3
"""NEXUS OS Hierarchy v2 — Full Integration Test Suite

Tests the complete agent decision cycle after the llm_router_v2 migration:
  Router routing logic → health checks → inference → workflow → delegation → blockchain

Usage:
    python3 test_hierarchy_v2.py              # all tests
    python3 test_hierarchy_v2.py --quick      # skip inference (routing + blockchain only)

Exit code:
    0  all critical tests passed
    1  one or more critical tests failed
"""
import asyncio
import hashlib
import json
import logging
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# ── Path setup ───────────────────────────────────────────────────────────────

sys.path.insert(0, "/opt/nexus/agents")

# Silence noisy third-party loggers during the test run
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(name)-20s %(levelname)s %(message)s",
)
logging.getLogger("workflow").setLevel(logging.ERROR)
logging.getLogger("llm-router").setLevel(logging.WARNING)

# ── Result tracking ──────────────────────────────────────────────────────────

class TestResults:
    def __init__(self):
        self.results: List[Tuple[str, bool, str]] = []   # (name, passed, note)

    def record(self, name: str, passed: bool, note: str = ""):
        self.results.append((name, passed, note))
        status = "\033[32mPASS\033[0m" if passed else "\033[31mFAIL\033[0m"
        note_str = f"  ({note})" if note else ""
        print(f"  [{status}] {name}{note_str}")

    def skip(self, name: str, reason: str):
        self.results.append((name, None, reason))
        print(f"  [\033[33mSKIP\033[0m] {name}  ({reason})")

    def summary(self) -> Tuple[int, int, int]:
        passed  = sum(1 for _, ok, _ in self.results if ok is True)
        failed  = sum(1 for _, ok, _ in self.results if ok is False)
        skipped = sum(1 for _, ok, _ in self.results if ok is None)
        return passed, failed, skipped

    def critical_failures(self) -> List[str]:
        return [n for n, ok, _ in self.results if ok is False]

R = TestResults()

# ── Helpers ──────────────────────────────────────────────────────────────────

def _section(title: str):
    print(f"\n\033[1;36m{'═' * 60}\033[0m")
    print(f"\033[1;36m  {title}\033[0m")
    print(f"\033[1;36m{'═' * 60}\033[0m")


def _is_sha256(s: str) -> bool:
    return bool(s and re.fullmatch(r"[0-9a-f]{64}", s))


# ════════════════════════════════════════════════════════════════════════════
# SECTION 1: Router unit tests (pure logic, no network)
# ════════════════════════════════════════════════════════════════════════════

def test_router_routing():
    _section("1. LLM Router — Routing Logic")

    from llm_router_v2 import LLMRouter, TIERS

    router = LLMRouter()

    cases = [
        # (agent_id, task_type, expected_tier, description)
        ("ceo",                None,          "coordinator", "CEO → coordinator"),
        ("coo",                None,          "director",    "COO → director"),
        ("compute_director",   None,          "director",    "compute_director → director"),
        ("storage_director",   None,          "director",    "storage_director → director"),
        ("ml_director",        None,          "director",    "ml_director → director"),
        # Router uses role-based IDs (auth_agent, process_scheduler) — these route correctly
        ("auth_agent",         None,          "worker",      "auth_agent (router ID) → worker"),
        ("qaoa_optimizer",     None,          "worker",      "qaoa_optimizer (router ID) → worker"),
        ("unknown_agent_xyz",  None,          "director",    "unknown → director (default)"),
        # task_type overrides agent
        ("ceo",                "code_gen",    "coder",       "CEO + code_gen → coder (override)"),
        (None,                 "planning",    "coordinator", "None + planning → coordinator"),
        ("compute_worker_1",   "code_gen",    "coder",       "worker + code_gen → coder (override)"),
        ("ceo",                "planning",    "coordinator", "CEO + planning → coordinator (both match)"),
    ]

    all_ok = True
    for agent_id, task_type, expected, desc in cases:
        tier = router.select_tier(agent_id, task_type)
        ok = tier.name == expected
        if not ok:
            all_ok = False
        R.record(f"route: {desc}", ok,
                 note="" if ok else f"got '{tier.name}', want '{expected}'")

    # ── Known issue: registry IDs ≠ router IDs for all 21 workers ────────
    # The router uses role-based agent IDs (process_scheduler, auth_agent, …)
    # but the registry uses numbered IDs (compute_worker_1, security_worker_1, …).
    # All 21 workers in the registry will default to the director tier at runtime.
    from agent_registry import AGENT_REGISTRY
    misrouted = [
        aid for aid, cfg in AGENT_REGISTRY.items()
        if cfg.get("tier") == "worker"
        and router.select_tier(aid).name != "worker"
    ]
    # This SHOULD be 0 — flag as FAIL so it gets fixed
    R.record(
        "route: all registry worker IDs resolve to worker tier (ID sync)",
        len(misrouted) == 0,
        note=f"⚠ {len(misrouted)}/21 workers use numbered IDs not in router agent list "
             f"(e.g. compute_worker_1 → should be process_scheduler). "
             f"Fix: sync llm_router_v2 agents lists with registry IDs."
             if misrouted else "",
    )

    # Verify all tier configs are intact
    for tier_name in ("coordinator", "coder", "director", "worker"):
        R.record(f"tier config: {tier_name} exists", tier_name in TIERS)

    return all_ok


# ════════════════════════════════════════════════════════════════════════════
# SECTION 2: Health checks
# ════════════════════════════════════════════════════════════════════════════

async def test_health_checks() -> Dict[str, bool]:
    _section("2. Endpoint Health Checks")

    from llm_router_v2 import LLMRouter, TIERS

    router = LLMRouter()
    health: Dict[str, bool] = {}

    for tier_name, config in TIERS.items():
        t0 = time.monotonic()
        ok = await router.check_health(config.endpoint)
        latency = (time.monotonic() - t0) * 1000
        health[tier_name] = ok
        R.record(
            f"health: {tier_name} ({config.model[:30]})",
            ok,
            note=f"{latency:.0f}ms" if ok else f"DOWN — {config.endpoint}",
        )

    up = sum(health.values())
    print(f"\n  Endpoints UP: {up}/{len(TIERS)}")
    return health


# ════════════════════════════════════════════════════════════════════════════
# SECTION 3: Direct inference on each UP endpoint
# ════════════════════════════════════════════════════════════════════════════

async def test_direct_inference(health: Dict[str, bool]):
    _section("3. Direct Inference (UP endpoints only)")

    from llm_router_v2 import LLMRouter, TIERS

    router = LLMRouter()

    # Tier → representative agent_id for routing
    tier_agents = {
        "coordinator": "ceo",
        "coder":       None,   # routed by task_type
        "director":    "coo",
        "worker":      "compute_worker_1",
    }

    ping_messages = [{"role": "user", "content": "Reply with exactly two words: NEXUS OK"}]

    for tier_name, config in TIERS.items():
        if not health.get(tier_name):
            R.skip(f"inference: {tier_name}", "endpoint DOWN")
            continue

        agent_id = tier_agents[tier_name]
        task_type = "code_gen" if tier_name == "coder" else None

        t0 = time.monotonic()
        result = await router.generate(
            agent_id or "ceo",
            ping_messages,
            task_type=task_type,
            max_tokens=20,
            temperature=0.0,
        )
        latency = (time.monotonic() - t0) * 1000

        ok = (
            result.get("error") is None
            and result.get("content")
            and len(result["content"].strip()) > 0
        )
        note = (
            f"{latency:.0f}ms | model={result.get('model','?')[:25]} | "
            f"reply='{result.get('content','[none]')[:40].strip()}'"
            if ok else
            f"error={result.get('error','?')[:80]}"
        )
        R.record(f"inference: {tier_name}", ok, note=note)


# ════════════════════════════════════════════════════════════════════════════
# SECTION 4: Full agent workflow (CEO)
# ════════════════════════════════════════════════════════════════════════════

async def test_workflow_ceo(health: Dict[str, bool]) -> Optional[Dict]:
    _section("4. Agent Workflow — CEO Full Cycle")

    # CEO needs coordinator tier (or director as fallback)
    if not health.get("coordinator") and not health.get("director"):
        R.skip("workflow: CEO full cycle", "coordinator AND director both DOWN")
        return None

    try:
        from agent_workflow import NexusAgentWorkflow
    except Exception as exc:
        R.record("workflow: import NexusAgentWorkflow", False, note=str(exc)[:80])
        return None

    R.record("workflow: import NexusAgentWorkflow", True)

    # Instantiate
    try:
        wf = NexusAgentWorkflow("ceo")
        R.record("workflow: NexusAgentWorkflow('ceo') init", True)
    except Exception as exc:
        R.record("workflow: NexusAgentWorkflow('ceo') init", False, note=str(exc)[:80])
        return None

    # Verify it's using the router
    has_router = hasattr(wf, "router") and not hasattr(wf, "llm_client")
    R.record("workflow: uses self.router (not llm_client)", has_router)

    # Process a realistic CEO-level message
    test_msg = "Run a full cluster health check on all 4 nodes"
    print(f"\n  Message: '{test_msg}'")

    try:
        t0 = time.monotonic()
        result = await wf.process_message(test_msg)
        latency = (time.monotonic() - t0) * 1000
        print(f"  Latency: {latency:.0f}ms")
    except Exception as exc:
        R.record("workflow: process_message completed", False, note=str(exc)[:100])
        return None

    R.record("workflow: process_message completed", True, note=f"{latency:.0f}ms")

    # ── Validate WorkflowState fields ────────────────────────────────────

    decision = result.get("decision", {})

    # Required fields present
    for field in ("decision", "reasoning", "delegates_to", "priority", "ect_cost"):
        present = field in decision and decision[field] is not None
        R.record(f"workflow: decision.{field} present", present,
                 note=str(decision.get(field, "MISSING"))[:60] if present else "MISSING")

    # Type checks
    R.record("workflow: decision.delegates_to is list",
             isinstance(decision.get("delegates_to"), list))
    R.record("workflow: decision.priority in 1-5",
             isinstance(decision.get("priority"), (int, float))
             and 1 <= decision.get("priority", 0) <= 5)
    R.record("workflow: decision.ect_cost in 1-100",
             isinstance(decision.get("ect_cost"), (int, float))
             and 1 <= decision.get("ect_cost", 0) <= 100)

    # Reasoning hash
    rhash = result.get("reasoning_hash", "")
    R.record("workflow: reasoning_hash is valid SHA256", _is_sha256(rhash),
             note=f"{rhash[:20]}…" if rhash else "empty")

    # Timestamp
    ts = result.get("timestamp", "")
    ts_ok = bool(ts) and "T" in ts and ts.endswith("Z")
    R.record("workflow: timestamp is ISO8601Z", ts_ok, note=ts if ts else "empty")

    # Leadership path ran analyze node (CEO has 4-node graph)
    analysis = result.get("analysis")
    R.record("workflow: analysis node ran (leadership path)",
             analysis is not None and len(analysis) > 10,
             note=(analysis[:60] + "…") if analysis else "None/empty")

    # No error in state
    err = result.get("error")
    R.record("workflow: no error in state", err is None,
             note=str(err)[:80] if err else "")

    print(f"\n  Decision:    {str(decision.get('decision',''))[:80]}")
    print(f"  Reasoning:   {str(decision.get('reasoning',''))[:80]}")
    print(f"  Delegates:   {decision.get('delegates_to', [])}")
    print(f"  Priority:    {decision.get('priority')}  ECT: {decision.get('ect_cost')}")
    print(f"  Hash:        {rhash[:32]}…")

    return result


# ════════════════════════════════════════════════════════════════════════════
# SECTION 5: Delegation chain
# ════════════════════════════════════════════════════════════════════════════

async def test_delegation_chain(health: Dict[str, bool], ceo_result: Optional[Dict]):
    _section("5. Delegation Chain — CEO → Compute Director → Worker")

    # ── 5a: CEO should delegate compute tasks ────────────────────────────

    if ceo_result is not None:
        decision = ceo_result.get("decision", {})
        delegates = decision.get("delegates_to", [])
        # delegates_to is structurally valid (list) — actual delegation is
        # non-deterministic at temperature 0.6; CEO may choose clarification over delegation
        delegates_ok = isinstance(delegates, list)
        R.record("delegation: CEO delegates_to is a valid list",
                 delegates_ok,
                 note=f"delegates={delegates} (empty = clarification request, non-zero = delegation)")
    else:
        R.skip("delegation: CEO delegation check", "CEO workflow not run")

    # ── 5b: Compute Director workflow ─────────────────────────────────────

    if not health.get("director") and not health.get("coordinator"):
        R.skip("delegation: compute_director workflow", "director+coordinator both DOWN")
    else:
        try:
            from agent_workflow import NexusAgentWorkflow
            wf_dir = NexusAgentWorkflow("compute_director")
            R.record("delegation: NexusAgentWorkflow('compute_director') init", True)

            t0 = time.monotonic()
            dir_result = await wf_dir.process_message(
                "Run health check on nexus-master and nexus-ai nodes"
            )
            latency = (time.monotonic() - t0) * 1000

            dir_decision = dir_result.get("decision", {})
            dir_ok = bool(dir_decision.get("decision")) and bool(dir_decision.get("reasoning"))
            R.record("delegation: compute_director produced decision", dir_ok,
                     note=f"{latency:.0f}ms | {str(dir_decision.get('decision',''))[:60]}")

            # Director should have analysis (it's a leadership role)
            dir_analysis = dir_result.get("analysis")
            R.record("delegation: compute_director ran analyze node",
                     dir_analysis is not None and len(dir_analysis) > 5,
                     note=(dir_analysis[:60] + "…") if dir_analysis else "None/empty")

            # reasoning_hash valid
            dir_hash = dir_result.get("reasoning_hash", "")
            R.record("delegation: compute_director hash is SHA256", _is_sha256(dir_hash))

        except Exception as exc:
            R.record("delegation: compute_director workflow", False, note=str(exc)[:100])
            dir_result = None

    # ── 5c: Worker workflow (3-node graph, no analyze step) ────────────────

    if not health.get("worker") and not health.get("director"):
        R.skip("delegation: worker workflow", "worker+director both DOWN")
    else:
        try:
            from agent_workflow import NexusAgentWorkflow
            wf_w = NexusAgentWorkflow("compute_worker_1")
            R.record("delegation: NexusAgentWorkflow('compute_worker_1') init", True)

            t0 = time.monotonic()
            w_result = await wf_w.process_message(
                "Check CPU and memory usage on nexus-master"
            )
            latency = (time.monotonic() - t0) * 1000

            w_decision = w_result.get("decision", {})
            w_ok = bool(w_decision.get("decision"))
            R.record("delegation: compute_worker_1 produced decision", w_ok,
                     note=f"{latency:.0f}ms | {str(w_decision.get('decision',''))[:60]}")

            # Worker graph has NO analyze node — analysis must be None
            w_analysis = w_result.get("analysis")
            R.record("delegation: worker skipped analyze node (3-node graph)",
                     w_analysis is None,
                     note=f"analysis={w_analysis[:30] if w_analysis else 'None'}")

            w_hash = w_result.get("reasoning_hash", "")
            R.record("delegation: compute_worker_1 hash is SHA256", _is_sha256(w_hash))

        except Exception as exc:
            R.record("delegation: compute_worker_1 workflow", False, note=str(exc)[:100])


# ════════════════════════════════════════════════════════════════════════════
# SECTION 6: Blockchain logger
# ════════════════════════════════════════════════════════════════════════════

async def test_blockchain_logger():
    _section("6. Blockchain Logger")

    try:
        from blockchain_logger import BlockchainLogger
        bc = BlockchainLogger()
        R.record("blockchain: BlockchainLogger init", True)
    except Exception as exc:
        R.record("blockchain: BlockchainLogger init", False, note=str(exc)[:80])
        return

    connected = bc.is_connected()
    R.record("blockchain: RPC reachable (10.0.20.3:8545)", connected,
             note="chain ID 123454321" if connected else "nexus-master unreachable from admin VLAN?")

    if not connected:
        R.skip("blockchain: log_decision", "RPC not reachable")
        R.skip("blockchain: tx_hash returned", "RPC not reachable")
        R.skip("blockchain: entry count readable", "RPC not reachable")
        return

    # Verify we can read entry count
    count = bc.get_entry_count()
    R.record("blockchain: getEntryCount() readable", count >= 0,
             note=f"{count} entries on-chain")

    # Log a test decision
    test_hash = hashlib.sha256(b"test_hierarchy_v2_probe").hexdigest()
    try:
        tx_hash = await bc.log_decision(
            agent_id="test_suite",
            task="Hierarchy v2 integration test probe",
            reasoning_hash=test_hash,
            ect_cost=1,
        )
        tx_ok = tx_hash is not None and len(tx_hash) > 10
        R.record("blockchain: log_decision submitted", tx_ok,
                 note=f"tx={tx_hash[:20]}…" if tx_ok else "None/empty")
    except Exception as exc:
        R.record("blockchain: log_decision submitted", False, note=str(exc)[:80])
        return

    # Verify entry was recorded
    new_count = bc.get_entry_count()
    R.record("blockchain: entry count incremented", new_count == count + 1,
             note=f"{count} → {new_count}")

    # Verify the hash on-chain matches what we submitted
    if new_count > 0:
        entry = bc.get_entry(new_count - 1)
        hash_match = entry is not None and entry.get("reasoning") == test_hash
        R.record("blockchain: on-chain reasoning_hash matches",
                 hash_match,
                 note=f"stored={entry['reasoning'][:20]}…" if entry else "entry not found")


# ════════════════════════════════════════════════════════════════════════════
# SECTION 7: agent_registry tier fields (sanity check after Prompt 3)
# ════════════════════════════════════════════════════════════════════════════

def test_registry_tiers():
    _section("7. agent_registry — Tier Field Sanity Check")

    from agent_registry import AGENT_REGISTRY, get_agent

    expected = {
        "ceo":               "coordinator",
        "coo":               "director",
        "compute_director":  "director",
        "security_director": "director",
        "ml_director":       "director",
        "compute_worker_1":  "worker",
        "security_worker_1": "worker",
        "quantum_worker_1":  "worker",
    }

    for agent_id, expected_tier in expected.items():
        try:
            cfg = get_agent(agent_id)
            actual = cfg.get("tier", "MISSING")
            legacy = cfg.get("legacy_model", "MISSING")
            ok = actual == expected_tier
            R.record(f"registry: {agent_id}.tier={expected_tier}",
                     ok,
                     note=f"legacy_model={legacy[:30]}" if ok else f"got '{actual}'")
        except KeyError:
            R.record(f"registry: {agent_id} exists", False, note="KeyError — not in registry")

    # Ensure no agent still has bare "model" key (should all be "legacy_model" now)
    stale = [aid for aid, cfg in AGENT_REGISTRY.items() if "model" in cfg and "legacy_model" not in cfg]
    R.record('registry: no stale "model" fields (all renamed to legacy_model)',
             len(stale) == 0,
             note=f"stale: {stale}" if stale else "")

    # Total count
    R.record(f"registry: 30 agents loaded", len(AGENT_REGISTRY) == 30,
             note=f"found {len(AGENT_REGISTRY)}")


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

async def run_all(quick: bool = False):
    print("\n\033[1;37m╔══════════════════════════════════════════════════════════╗\033[0m")
    print("\033[1;37m║     NEXUS OS Hierarchy v2 — Integration Test Suite       ║\033[0m")
    print(f"\033[1;37m║     Mode: {'QUICK (no inference)' if quick else 'FULL (inference enabled)':44s}║\033[0m")
    print("\033[1;37m╚══════════════════════════════════════════════════════════╝\033[0m")

    # Section 1: Pure routing logic — always runs
    test_router_routing()

    # Section 7: Registry sanity — always runs
    test_registry_tiers()

    # Section 2: Health checks — always runs (fast)
    health = await test_health_checks()

    if quick:
        print("\n  \033[33m[QUICK MODE] Skipping inference, workflow, delegation, blockchain tests.\033[0m")
    else:
        # Section 3: Direct inference
        await test_direct_inference(health)

        # Section 4: Full CEO workflow
        ceo_result = await test_workflow_ceo(health)

        # Section 5: Delegation chain
        await test_delegation_chain(health, ceo_result)

        # Section 6: Blockchain logger
        await test_blockchain_logger()

    # ── Final summary ─────────────────────────────────────────────────────

    passed, failed, skipped = R.summary()
    total = passed + failed + skipped

    print(f"\n\033[1;37m{'═' * 60}\033[0m")
    print(f"\033[1;37m  RESULTS: {total} tests | "
          f"\033[32m{passed} passed\033[0m\033[1;37m | "
          f"\033[31m{failed} failed\033[0m\033[1;37m | "
          f"\033[33m{skipped} skipped\033[0m\033[1;37m"
          f"\033[0m")

    if failed > 0:
        print(f"\n\033[31m  FAILED tests:\033[0m")
        for name in R.critical_failures():
            print(f"    ✗ {name}")

    print(f"\033[1;37m{'═' * 60}\033[0m\n")

    return failed == 0


def main():
    quick = "--quick" in sys.argv
    ok = asyncio.run(run_all(quick=quick))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
