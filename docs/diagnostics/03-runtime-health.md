# NEXUS OS Runtime Health Report
**Generated:** 2026-03-09
**Audited on:** nexus-admin (10.0.10.5, aarch64 Debian, Python 3.13.5)
**Scope:** Syntax, import, service, blockchain, cluster, and LLM health
**Mode:** Read-only — no files modified, no services started or stopped

---

## CRITICAL ISSUES SUMMARY (read this first)

| # | Severity | Issue | Impact |
|---|----------|-------|--------|
| 1 | **CRITICAL** | Local LLM endpoint blocked by firewall on nexus-ai | All orchestrator LLM calls fall through to HuggingFace API |
| 2 | **CRITICAL** | `llm_client.py` has stale pre-VLAN IP `192.168.8.128` | Even if firewall were fixed, agents would target wrong host |
| 3 | **CRITICAL** | `langgraph` + `web3` absent from system Python | Agent bots (`hierarchy_manager`, `ceo_bot`, `agent_workflow`, `blockchain_logger`) cannot start under system Python |
| 4 | **CRITICAL** | `web3` absent from system Python | All `libnexus/`, `core/service_framework.py`, `networking/` modules fail to import under system Python |
| 5 | **CRITICAL** | IPFS has 0 swarm peers — cluster is isolated | No IPFS data replication across cluster nodes; storage redundancy broken |
| 6 | **HIGH** | `core/action_utils.py` broken (augeas + bad import) | 850-line module is entirely non-functional |
| 7 | **HIGH** | StorageRegistry address in MEMORY.md is stale | MEMORY.md says `0xd216D...`; deployed JSON + constitution say `0x859e30...` |
| 8 | **HIGH** | `nexus-orchestrator.service` crashed once before stabilising | exit-code=1 on first run (2026-03-05 20:37); restart counter=1; has been stable since |
| 9 | **MEDIUM** | `services/` subtree (39 files) inoperable — plinth/django not installed | FreedomBox integration modules silently dead |
| 10 | **MEDIUM** | IPFS API not accessible via public port from VLAN20 | IPFS on VLAN20 nodes responds only on localhost; API calls from nexus-admin blocked |

---

## Section 1: Python Environment

### System Python (used by nexus-orchestrator.service and nexus-reindex.service)

```
Python 3.13.5 — /usr/bin/python3
```

| Package | Version | Required By | Status |
|---------|---------|-------------|--------|
| discord.py | 2.7.0 | agents/, automation/ | OK |
| chromadb | 1.5.2 | automation/ | OK |
| aiohttp | 3.13.3 | agents/llm_client.py | OK |
| httpx | 0.28.1 | various | OK |
| requests | 2.32.3 | various | OK |
| python-dotenv | 1.0.1 | agents/, automation/ | OK |
| PyYAML | 6.0.2 | automation/ | OK |
| psutil | 7.0.0 | automation/ | OK |
| pyserial | 3.5 | networking/ | OK |
| Flask | 3.1.1 | (available) | OK |
| huggingface_hub | 1.5.0 | (available) | OK |
| **web3** | **MISSING** | libnexus/, core/, networking/, contracts/ | **FAIL** |
| **langgraph** | **MISSING** | agents/agent_workflow.py | **FAIL** |
| **augeas** | **MISSING** | core/action_utils.py | **FAIL** |
| **plinth** | **MISSING** | services/ (entire subtree) | **FAIL** |
| **django** | **MISSING** | services/ (entire subtree) | **FAIL** |
| structlog | MISSING | not referenced in codebase | N/A |

### venv Python (used by nexus-dashboard.service only)

```
/opt/nexus/contracts/.venv/bin/python3 (Python 3.13.x)
```

| Package | Version | Status |
|---------|---------|--------|
| web3 | 7.14.1 | OK |
| langgraph | 1.0.8 | OK |
| langgraph-checkpoint | 4.0.0 | OK |
| aiohttp | 3.13.3 | OK |
| discord.py | 2.6.4 | OK (note: older than system 2.7.0) |

**No package version conflicts detected** between system pip and venv. The venv is a superset; system Python has chromadb (missing from venv), venv has web3/langgraph (missing from system). No duplicate package names detected in system pip.

---

## Section 2: Syntax Check Results

All Python files pass syntax check under Python 3.13.5. **Zero syntax errors across the entire codebase.**

### agents/ — 13 files

| File | Lines | Syntax |
|------|-------|--------|
| agent_registry.py | 1004 | ✅ PASS |
| agent_workflow.py | 343 | ✅ PASS |
| blockchain_logger.py | 233 | ✅ PASS |
| ceo_bot.py | 302 | ✅ PASS |
| hierarchy_manager.py | 560 | ✅ PASS |
| invite_bots.py | 422 | ✅ PASS |
| llm_client.py | 389 | ✅ PASS |
| test_blockchain_logger.py | 172 | ✅ PASS |
| test_delegation.py | 99 | ✅ PASS |
| test_integration.py | 231 | ✅ PASS |
| test_llm_client.py | 113 | ✅ PASS |
| test_workflow.py | 166 | ✅ PASS |
| verify_system.py | 248 | ✅ PASS |

### automation/ — 29 files, all PASS ✅

### contracts/scripts/ — 6 files, all PASS ✅

### core/ — 3 files, all PASS ✅

### libnexus/ — 6 files, all PASS ✅

### networking/ — 5 files, all PASS ✅

**Total: 62 files checked, 62 pass, 0 fail.**

Syntax is completely clean. All failures are import-time errors (missing packages), not syntax errors.

---

## Section 3: Import Test Results

Tests run with system Python (`/usr/bin/python3`) in the relevant working directories.

### agents/ — system Python

| Module | Result | Error |
|--------|--------|-------|
| agents.agent_registry | ✅ **OK** | — |
| agents.llm_client | ✅ **OK** | — |
| agents.agent_workflow | ❌ **IMPORT_ERROR** | `No module named 'langgraph'` |
| agents.blockchain_logger | ❌ **IMPORT_ERROR** | `No module named 'web3'` |
| agents.hierarchy_manager | ❌ **IMPORT_ERROR** | `No module named 'langgraph'` (via agent_workflow) |
| agents.ceo_bot | ❌ **IMPORT_ERROR** | `No module named 'langgraph'` (via agent_workflow) |

**2 of 6 agent modules loadable under system Python. The agent bot subsystem cannot start.**

### automation/ — system Python (run from /opt/nexus/automation/ CWD)

| Module | Result |
|--------|--------|
| guardrails | ✅ OK |
| audit_logger | ✅ OK |
| chroma_memory | ✅ OK |
| discord_reporter | ✅ OK |
| llm_router | ✅ OK |
| context_builder | ✅ OK |
| planning_engine | ✅ OK |
| execution_engine | ✅ OK |
| failure_analyzer | ✅ OK |
| feedback_loop | ✅ OK |
| health_monitor | ✅ OK |
| task_planner | ✅ OK |
| git_monitor | ✅ OK |
| persona | ✅ OK |
| intent_parser | ✅ OK |
| proactive_tasks | ✅ OK |
| subagent_client | ✅ OK |
| system_queries | ✅ OK |
| web_research | ✅ OK |
| hid_controller | ✅ OK |
| discord_comms | ✅ OK |

**21 of 21 automation modules load cleanly under system Python. The orchestrator subsystem is fully importable.**

### core/ and libnexus/ — system Python

| Module | Result | Error |
|--------|--------|-------|
| core.service_framework | ❌ IMPORT_ERROR | `No module named 'web3'` |
| core.action_utils | ❌ IMPORT_ERROR | `No module named 'augeas'` |
| libnexus.contracts | ❌ IMPORT_ERROR | `No module named 'web3'` (via kernel import chain) |
| libnexus.kernel | ❌ IMPORT_ERROR | `No module named 'web3'` |
| libnexus.nexus_storage | ❌ IMPORT_ERROR | `No module named 'web3'` |

**0 of 5 core/libnexus modules loadable under system Python.**

### venv Python verification

| Package | venv Import | Status |
|---------|------------|--------|
| web3 | ✅ OK | web3 7.14.1 |
| langgraph | ✅ OK | 1.0.8 |
| langgraph.graph | ✅ OK | StateGraph, END available |

All blockchain-dependent code is importable under `.venv`. The venv is the required runtime for agent bots and contract scripts.

---

## Section 4: Package Conflicts

**No duplicate package names detected** in the system pip package list. No version conflicts between system packages.

The only version delta worth noting: `discord.py` 2.7.0 (system) vs 2.6.4 (venv). Both are compatible with the codebase; the nexus-dashboard.service uses the venv (2.6.4). Non-critical.

---

## Section 5: Contract Artifact Validity

All 9 deployed contract JSON files are valid JSON with `abi` and `address` fields present.

| Contract | Address (deployed JSON) | ABI entries | Memory.md | Match? |
|----------|------------------------|-------------|-----------|--------|
| AgentGovernance.json | 0xA4f8CA77065bE462324624083990F58ff1f12207 | 29 | 0xA4f8CA... | ✅ MATCH |
| DecisionQuality.json | 0x4198228d18c8435d73E51105b912032f657f7218 | 28 | 0x41982... | ✅ MATCH |
| MeshRegistry.json | 0x21e59f66850bbC7333dE62fF5f7d6c2bcaD9A26F | 7 | 0x21e59f... | ✅ MATCH |
| PidRegistry.json | 0xdE9DC5FB0386Cf92145d36e6d46f2a3FA8b531AA | 4 | (not in memory) | ⚠️ UNTRACKED |
| ReasoningLedger.json | 0x0317451264E1de1A0696A81f6141e72E58686DE4 | 7 | 0x031745... | ✅ MATCH |
| ResourceManager.json | 0x7E7f5e6cd9d7d485eeFa4Ec3Fb211705A3A8c6C6 | 8 | (not in memory) | ⚠️ UNTRACKED |
| ServiceRegistry.json | 0xbd015B6A2C0E10E1f31b7C50580A2Cc86e3A0dd8 | 6 | 0xbd015B... | ✅ MATCH |
| StorageRegistry.json | 0x859e30a6b752Af6D96d309Dc3a5bECfCfFDe31A6 | 13 | **0xd216DABD...** | ❌ **MISMATCH** |
| TokenManager.json | 0x08C96540A286a6b3cDe1E20F77B246E53D238E48 | 35 | 0x08C965... | ✅ MATCH |

### StorageRegistry address discrepancy

- **MEMORY.md**: `0xd216DABDAbE314337B4821D29C26FeB52Cb37d27`
- **contracts/deployed/StorageRegistry.json**: `0x859e30a6b752Af6D96d309Dc3a5bECfCfFDe31A6`
- **automation/constitution.json**: `0x859e30a6b752Af6D96d309Dc3a5bECfCfFDe31A6`

The deployed JSON and constitution.json agree with each other. **MEMORY.md has the stale address.** The code will use the deployed JSON (correct). MEMORY.md should be updated. This is a documentation inconsistency only — no runtime impact.

**PidRegistry and ResourceManager** are deployed and have valid JSON artifacts but are not listed in MEMORY.md. Should be added.

---

## Section 6: Service Status

### nexus-orchestrator.service

```
Status:   active (running) since 2026-03-05 20:38:43 EST (4 days ago)
PID:      2374
Command:  /usr/bin/python3 /opt/nexus/automation/dev_orchestrator.py
CWD:      /opt/nexus/automation
Memory:   168M (peak: 1.3G, swap: 52.7M)
CPU:      2m 413ms
Restart:  counter=1 (crashed once on initial start 2026-03-05 20:37:43)
```

**Status: RUNNING but degraded.**
- Crashed at 20:37:43 on first start (exit-code=1) — reason in orchestrator.log
- Restarted at 20:38:43, has been stable for 4 days
- Currently stuck in retry loop for `np-005.1.1` — see git-forensics report
- Memory peaked at 1.3G (normal for Python + LLM context loading)
- Using HuggingFace API for all LLM calls (local LLM unreachable — see Critical Issue #1)

### nexus-dashboard.service

```
Status:   active (running) since 2026-03-05 20:37:44 EST (4 days ago)
PID:      1243
Command:  /opt/nexus/contracts/.venv/bin/python3 dashboard.py
CWD:      /home/mhuraibi/nexus/phase4/dashboard   ⚠️ OUTSIDE /opt/nexus
Memory:   75.3M (peak: 131.8M)
CPU:      5h 8m (heavy — rendering metrics continuously)
Port:     8880 (HTTP, confirmed listening)
```

**Status: RUNNING.**
- Serving HTTP on port 8880, root path returns HTML (200 OK)
- Dashboard source is in `/home/mhuraibi/nexus/phase4/dashboard/` — not in `/opt/nexus/`; not in git
- Using venv Python (correct — needs web3 for chain queries)
- High CPU (5h for 4 days) suggests frequent polling; not necessarily a problem but worth monitoring

### chromadb.service

```
Status:   active (running) since 2026-03-05 20:37:48 EST (4 days ago)
PID:      1501
Command:  /usr/bin/python3 /home/mhuraibi/.local/bin/chroma run --path /mnt/nexus-nas/knowledge/chroma --host 0.0.0.0 --port 8000
Memory:   45.8M (peak: 138.7M, swap: 89.9M)
Port:     8000 (confirmed listening on 0.0.0.0)
```

**Status: RUNNING.**
- Heartbeat confirmed: `{"nanosecond heartbeat": 1773064357658295722}`
- 8 collections: nexus_decisions, session_transcripts, code_chunks, nexus_context, nexus_failures, web_research, docs_chunks, infra_configs
- Data stored on NAS at `/mnt/nexus-nas/knowledge/chroma` — dependency on NFS mount
- chroma runs with `--host 0.0.0.0` (exposed to network); only localhost access is expected from orchestrator

### nexus-reindex.timer

```
Status:   active (waiting)
Next trigger: 2026-03-10 03:00:00 EDT (17h away at time of audit)
Triggers: nexus-reindex.service (runs indexer.py + build_world_model.py)
```

**Status: OK — scheduled correctly.**

### k3s-agent.service

```
Status:   active (running) since 2026-03-05 20:37:55 EST (4 days ago)
PID:      1258 (k3s agent) + 1721 (containerd)
Version:  v1.34.4+k3s1
Memory:   150.4M
```

**Status: RUNNING.** Registered to master at `https://10.0.20.3:6443`. Node label `role=admin`.

Warning log (repeated): `Found node without any CPU, nodeDir: /sys/devices/system/node/nodeX` — this is a cosmetic warning from the Pi 5's NUMA-style CPU topology; k3s does not correctly enumerate all CPU nodes on Pi 5. Non-critical.

`kubectl` requires `sudo` on this node (no user-readable kubeconfig). Full cluster status could not be obtained without privilege escalation.

### wg-quick@nexus-mesh.service

```
Status:   active (exited) — one-shot, interface is up
Interface: nexus-mesh at 10.1.0.4/24
```

**Status: OK.** WireGuard interface is up. However, WG overlay traffic to nexus-ai's LLM port (8090) is blocked by iptables on nexus-ai (see Critical Issue #1).

---

## Section 7: Cluster Health

### K3s
- `kubectl` requires `sudo`; cluster status not fully obtainable
- k3s-agent is active and connected to master (`10.0.20.3:6443`)
- Flannel pod network routes present: `10.42.0.0/24`, `10.42.1.0/24`, `10.42.2.0/24` (via flannel.1)
- **No route to `10.0.20.0/24`** in routing table — VLAN20 nodes reached via default gateway `10.0.10.1`
  This is expected network topology (VLAN router handles inter-VLAN routing), not a defect.

### IPFS

| Node | Port 5001 | Peer ID | Peers |
|------|-----------|---------|-------|
| nexus-admin (localhost) | ✅ RUNNING (PID 1204, Kubo 0.32.1) | 12D3KooWLfCQcQTVDcKUREMoyJzFoNvSRqsjPFMT3KE9FwixUMEk | **0 — ISOLATED** |
| nexus-master (10.0.20.3) | ❌ Not reachable from VLAN10 | — | — |
| nexus-ai (10.0.20.4) | ❌ Not reachable from VLAN10 | — | — |
| nexus-storage (10.0.20.11) | ❌ Not reachable from VLAN10 | — | — |

**IPFS is isolated on nexus-admin — 0 swarm peers.** IPFS API ports on VLAN20 nodes are not open to VLAN10 (only IPFS P2P port 4001 is allowed from VLAN20 hosts). nexus-admin's IPFS cannot verify the cluster is peered.

Likely cause: IPFS on nexus-admin is running but its bootstrap peers (VLAN20 nodes on 10.0.20.x/tcp/4001) are not being reached. The IPFS API (5001) on VLAN20 nodes is firewalled from VLAN10. IPFS data pinning from nexus-admin is unverifiable from this audit.

---

## Section 8: Blockchain Health

### RPC Connectivity

| Node | IP | Port | Block Height | Responding |
|------|----|------|-------------|------------|
| nexus-admin (this node) | localhost | 8545 | — | ❌ NOT RUNNING (expected) |
| nexus-master | 10.0.20.3 | 8545 | **1720** | ✅ OK |
| nexus-ai | 10.0.20.4 | 8545 | **1720** | ✅ OK |
| nexus-storage | 10.0.20.11 | 8545 | **1720** | ✅ OK |

```
Block number hex: 0x6b8 = decimal 1720
```

### Chain State

| Metric | Value | Assessment |
|--------|-------|-----------|
| All validators at same block | 1720 (all three) | ✅ **CONSENSUS** |
| eth_syncing | false | ✅ Fully synced |
| net_peerCount | 2 (on nexus-master) | ✅ All 3 validators peered (2 peers from any one validator is correct for 3-node clique) |
| eth_mining | true (on nexus-master) | ✅ Sealing active |
| Chain ID | 123454321 | (not verified live — assumed from memory) |
| Period | 0 (demand sealing) | Block 1720 was last tx; no activity = stalled height expected |

**Blockchain is healthy.** All 3 validators are in sync at block 1720, sealing is active, and the Clique PoA consensus is functioning. Block 1720 matches known deployed contract blocks (ServiceRegistry at 1709, MeshRegistry at 1717), suggesting no anomalous fork.

Geth is NOT running on nexus-admin (correct — this is an admin/dev node, not a validator).

---

## Section 9: LLM Inference Health

### local-inference.service on nexus-ai (10.0.20.4)

```
Status:   active (running)
Binary:   llama-server (built from llama.cpp)
Model:    smollm2-1.7b-instruct-q4_k_m.gguf
Bind:     0.0.0.0:8090  ← correctly bound to all interfaces
```

**The service is running and the model is loaded.** However:

### LLM Reachability from nexus-admin — CRITICAL FAILURE

| Test | Result |
|------|--------|
| curl http://10.0.20.4:8090/v1/models | ❌ NO RESPONSE |
| curl http://10.1.0.2:8090/v1/models (via WireGuard) | ❌ NO RESPONSE |
| curl http://192.168.8.128:8090/v1/models (stale IP) | ❌ NOT RESPONDING (expected) |

**Root cause identified:** nexus-ai's iptables INPUT chain has policy DROP. Port 8090 is NOT in the ACCEPT rules. The explicit accepts for VLAN10 (nexus-admin at 10.0.10.5) are:

```
tcp dpt:22    from 10.0.10.5   ← SSH only
tcp dpt:8545  from 10.0.10.5   ← Geth RPC (why blockchain works)
tcp dpt:8546  from 10.0.10.5   ← Geth WS
tcp dpt:5001  from 10.0.10.5   ← IPFS API
```

**Port 8090 is missing from nexus-ai's iptables.** New connections from 10.0.10.5 to port 8090 are silently dropped. WireGuard traffic from 10.1.0.4 (nexus-admin WG) to port 8090 is also not whitelisted.

**Compound problem:** Even if the firewall were fixed, `agents/llm_client.py:19` hardcodes the stale pre-migration IP `192.168.8.128`. The fix requires **two changes**: (1) add port 8090 to nexus-ai iptables for `10.0.10.5` and `10.1.0.4`, and (2) update `llm_client.py` to use `10.0.20.4:8090`.

**Current behavior:** `dev_orchestrator.py` → `llm_router.py` → Tier 1 (ThinkPad at 10.0.30.2:1234) → falls back to HuggingFace API when ThinkPad unreachable. All LLM calls are going to HuggingFace, incurring API costs and rate limits.

---

## Section 10: Full Issue Registry

### Blocker — Would prevent fresh start

| File / Location | Issue | Fix |
|-----------------|-------|-----|
| `agents/llm_client.py:19` | `LOCAL_INFERENCE_URL = "http://192.168.8.128:8090/..."` stale IP | Change to `http://10.0.20.4:8090/v1/chat/completions` |
| nexus-ai iptables | Port 8090 not whitelisted for 10.0.10.5 (nexus-admin) | `sudo iptables -I INPUT 9 -p tcp -s 10.0.10.5 --dport 8090 -j ACCEPT && sudo netfilter-persistent save` |
| nexus-ai iptables | Port 8090 not whitelisted for 10.1.0.0/24 (WireGuard) | `sudo iptables -I INPUT 10 -p tcp -s 10.1.0.0/24 --dport 8090 -j ACCEPT && sudo netfilter-persistent save` |
| system Python env | `langgraph` not installed | `pip3 install langgraph` (or run agent bots under `.venv`) |
| system Python env | `web3` not installed | `pip3 install web3` (or run blockchain scripts under `.venv`) |
| `core/action_utils.py:14` | `import augeas` — not installed anywhere | Either install python3-augeas or remove/replace this file |
| `core/action_utils.py:16` | `from . import actions` — not a Python package | `actions/` needs `__init__.py` or the import must be removed |

### High — Functionally broken

| File / Location | Issue | Fix |
|-----------------|-------|-----|
| MEMORY.md | StorageRegistry address stale (`0xd216D...` should be `0x859e30...`) | Update MEMORY.md |
| MEMORY.md | PidRegistry and ResourceManager not listed | Add entries |
| `automation/seed_knowledge.py` | No `__main__` guard — executes on import | Wrap in `if __name__ == "__main__":` |
| `services/` entire subtree | plinth/django not installed; 39 files inoperable | Install plinth+django or accept as aspirational dead code |
| IPFS swarm | nexus-admin has 0 peers — isolated | Check swarm bootstrap list; run `ipfs swarm connect /ip4/10.0.20.3/tcp/4001/p2p/<peer-id>` |

### Medium — Degraded but running

| File / Location | Issue |
|-----------------|-------|
| `nexus-orchestrator.service` | Crashed once on initial start (restart counter=1). Root cause in orchestrator.log lines prior to 2026-03-05 20:37:43 should be investigated |
| `automation/dev_orchestrator.py` | Stuck retry loop on `np-005.1.1` (LLM depth-limit loop, ~30min interval) |
| `dashboard.py` | Source outside `/opt/nexus/` at `/home/mhuraibi/nexus/phase4/dashboard/`; not in git |
| `chromadb.service` | Running with `--host 0.0.0.0` — exposed to local network; no auth configured |
| `automation/discord_comms.py:36` | `CHANNEL_ID` hardcoded as int, ignores `CAF_CHANNEL_ID` env var |
| `automation/backup_file()` | Duplicate implementations in `dev_orchestrator.py` and `execution_engine.py` with diverged logic |

### Low — Tech debt

| Issue |
|-------|
| `automation/hid_controller.py` — 278 lines, zero callers, never wired into orchestrator |
| `automation/subagent_client.py` — duplicates llm_router.py with different API format |
| `_strip_json`, `mtime_iso` — copy-pasted across two files each |
| Git working directory is on `auto/np-004-1-f2-2-1772849379` not `main` |
| 22 stale `auto/` branches |
| IPFS datastore binary files tracked in git (should be gitignored) |
| `nexus-dashboard.service` CPU: 5h in 4 days — polling interval may be too aggressive |

---

## Section 11: Ports and Services on nexus-admin

Confirmed listening services on nexus-admin (10.0.10.5):

| Port | Service | Process | Notes |
|------|---------|---------|-------|
| 22 | SSH | sshd | All interfaces |
| 4001 | IPFS swarm | ipfs (PID 1204) | All interfaces |
| 5001 | IPFS API | ipfs (PID 1204) | All interfaces |
| 8000 | ChromaDB | chroma (PID 1501) | All interfaces |
| 8080 | IPFS gateway | ipfs (PID 1204) | All interfaces |
| 8880 | NEXUS Dashboard | python3 (PID 1243) | All interfaces |
| 10250 | K3s kubelet | k3s-agent | All interfaces |
| 10248/10249/10256 | K3s internal | k3s-agent | Localhost only |
| 6444 | K3s API proxy | k3s-agent | Localhost only |
| 53 | DNS | systemd-resolved | All interfaces |
| 111 | RPC portmapper | rpcbind | All interfaces (NFS client) |

**Geth is NOT running on nexus-admin** (confirmed — port 8545 not listening locally, as expected for a non-validator node).

---

*Report generated 2026-03-09. Read-only — no services started or stopped, no files modified.*
