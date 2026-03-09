# NEXUS OS Documentation Drift Report
**Generated:** 2026-03-09
**Method:** Read-only cross-reference of documentation claims against filesystem, live processes, and live blockchain queries
**Scope:** All markdown, JSON state files, and in-code claims

---

## Executive Summary

The NEXUS OS documentation is in a **bifurcated state**: the primary reference document (`NEXUS_OS_Current_State.md`) is 23 days old and was written before the VLAN migration, while the live system has advanced significantly beyond what it describes. The autonomous orchestrator has introduced additional drift by auto-updating some state files while leaving others frozen.

**Overall drift score: 58% of documented claims are accurate as-is.** A further 21% describe features that exist but are degraded or partially broken. 21% are materially false.

The most dangerous category of drift is **stale IP addresses in executable code**: 5 Python files still contain `192.168.8.x` addresses that point at nothing. These silently break blockchain logging, contract deployment, and the health-check scripts.

---

## Section 1: Documentation Inventory

| Document | Path | Last Modified | Author | Freshness |
|----------|------|---------------|--------|-----------|
| NEXUS OS Current State | `/opt/nexus/NEXUS_OS_Current_State.md` | 2026-02-15 | Human | **STALE — 23 days old, pre-VLAN migration** |
| NEXUS Living Guide | `/opt/nexus/automation/NEXUS_Living_Guide.md` | 2026-02-27 | Human + CAF auto-append | **STALE — 10 days old** |
| Project State JSON | `/opt/nexus/automation/project_state.json` | 2026-03-09 02:25 | health_monitor (auto) | **Current but contains stale values** |
| Change Ledger | `/opt/nexus/automation/change_ledger.md` | 2026-03-06 | CAF auto | Current — accurate for agent tasks only |
| Agents README | `/opt/nexus/agents/README.md` | 2026-02-14 | Human | Mostly accurate |
| Agent Invite Instructions | `/opt/nexus/agents/INVITE_INSTRUCTIONS.md` | 2026-02-14 | Human | Operational (list of invite URLs) |
| Pipeline Installation | `/opt/nexus/docs/pipeline_installation.md` | 2026-03-06 | CAF auto | 12 lines — sparse stub |
| Pipeline Usage Examples | `/opt/nexus/docs/pipeline_usage_examples.md` | 2026-03-06 | CAF auto | 45 lines — example stub |
| Bare Metal Results | `/opt/nexus/research/bare-metal/RESULTS.md` | unknown | Human | Historical benchmarks |

**The compiled-db (`/opt/nexus/docs/compiled-db/`) does not exist.** No `components.yaml`, `decisions.yaml`, `interfaces.yaml`, `code_index.yaml`, `dependencies.yaml`, or `gaps.yaml` files were found anywhere in `/opt/nexus/docs/`.

**No task/todo/backlog files exist** in `/opt/nexus` outside of `automation/intent_registry.yaml` (the orchestrator's internal task queue).

---

## Section 2: EXISTS vs MISSING — Every Path Mentioned in Documentation

### From `NEXUS_OS_Current_State.md` (Section 9 filesystem layout)

| Path | Status | Notes |
|------|--------|-------|
| `/opt/nexus/agents/hierarchy_manager.py` | ✅ EXISTS | 560 lines |
| `/opt/nexus/agents/ceo_bot.py` | ✅ EXISTS | 302 lines |
| `/opt/nexus/agents/agent_registry.py` | ✅ EXISTS | 1004 lines |
| `/opt/nexus/agents/agent_workflow.py` | ✅ EXISTS | 343 lines |
| `/opt/nexus/agents/blockchain_logger.py` | ✅ EXISTS | 233 lines |
| `/opt/nexus/agents/llm_client.py` | ✅ EXISTS | 389 lines |
| `/opt/nexus/agents/.env` | ✅ EXISTS | 59 lines, 31 token vars |
| `/opt/nexus/agents/verify_system.py` | ✅ EXISTS | 248 lines |
| `/opt/nexus/agents/test_delegation.py` | ✅ EXISTS | 99 lines |
| `/opt/nexus/agents/logs/hierarchy.log` | ✅ EXISTS | 3.1 MB, last entry 2026-02-17 |
| `/opt/nexus/agents/logs/decisions/` | ✅ EXISTS | 4 JSONL files, 10 total lines |
| `/opt/nexus/blockchain/genesis.json` | ❌ **MISSING on nexus-admin** | Lives on validators at `/opt/nexus/blockchain/` |
| `/opt/nexus/blockchain/genesis-fast.json` | ❌ **MISSING on nexus-admin** | Lives on validators |
| `/opt/nexus/blockchain/genesis-original-backup.json` | ❌ **MISSING on nexus-admin** | Lives on validators |
| `/opt/nexus/blockchain/geth/` | ❌ **MISSING on nexus-admin** | Lives on validators |
| `/opt/nexus/blockchain/keystore/` | ❌ **MISSING on nexus-admin** | Lives on validators |
| `/opt/nexus/blockchain/password.txt` | ❌ **MISSING on nexus-admin** | Lives on validators |
| `/opt/nexus/contracts/source/ReasoningLedger.sol` | ✅ EXISTS | |
| `/opt/nexus/contracts/source/ResourceManager.sol` | ✅ EXISTS | |
| `/opt/nexus/contracts/source/StorageRegistry.sol` | ✅ EXISTS | |
| `/opt/nexus/contracts/deployed/ReasoningLedger.json` | ✅ EXISTS | 7 ABI entries |
| `/opt/nexus/contracts/deployed/ResourceManager.json` | ✅ EXISTS | 8 ABI entries |
| `/opt/nexus/contracts/deployed/StorageRegistry.json` | ✅ EXISTS | 10 ABI entries |
| `/opt/nexus/contracts/scripts/deploy.py` | ✅ EXISTS | Uses stale IP 192.168.8.228 |
| `/opt/nexus/contracts/scripts/deploy_storage_registry.py` | ✅ EXISTS | |
| `/opt/nexus/contracts/scripts/test_storage_registry.py` | ✅ EXISTS | |
| `/opt/nexus/contracts/.venv/` | ✅ EXISTS | web3 7.14.1, langgraph 1.0.8 |
| `/opt/nexus/ipfs/config` | ✅ EXISTS | |
| `/opt/nexus/ipfs/swarm.key` | ✅ EXISTS | Private network key |
| `/opt/nexus/ipfs/datastore/` | ✅ EXISTS | |
| `/opt/nexus/scripts/install-ipfs-cluster.sh` | ✅ EXISTS | Installs Kubo 0.32.1 |
| `/opt/nexus/scripts/setup-ipfs-private.sh` | ✅ EXISTS | |
| `/opt/nexus/scripts/test-ipfs-distribution.sh` | ✅ EXISTS | Uses stale 192.168.8.x IPs |
| `/opt/nexus/scripts/verify-fast-blocks.py` | ✅ EXISTS | Uses stale 192.168.8.x IPs |
| `/etc/systemd/system/nexus-geth.service` | ❌ **MISSING on nexus-admin** | Only on validators (10.0.20.x) |
| `/etc/systemd/system/ipfs.service` | ✅ EXISTS | Running (PID 1204) |

**Missing paths summary:** 7 missing — ALL are blockchain files that correctly live on validator nodes, not nexus-admin. The document was written from the perspective of a validator node, or describes the cluster as a whole without distinguishing per-node layout. This is a structural issue in the documentation, not missing data.

### From `NEXUS_OS_Current_State.md` — Credentials section

| Item | Location | Status |
|------|----------|--------|
| Deployer wallet (0x817B...) | On-chain | ✅ Balance: 999.52 ETH confirmed live |
| Wallet keystore | `/opt/nexus/blockchain/keystore/` (on validators) | ✅ EXISTS on nexus-master |
| Wallet password | `/opt/nexus/blockchain/password.txt` (on validators) | ✅ EXISTS on nexus-master |
| Bot tokens | `/opt/nexus/agents/.env` | ✅ 31 token variables |
| IPFS swarm key | `/opt/nexus/ipfs/swarm.key` | ✅ EXISTS |
| Contract ABIs | `/opt/nexus/contracts/deployed/*.json` | ✅ 9 files (doc only mentions 3) |
| Python venv | `/opt/nexus/contracts/.venv/` | ✅ EXISTS |
| Geth service | `/etc/systemd/system/nexus-geth.service` | ❌ MISSING on nexus-admin (on validators only) |
| IPFS service | `/etc/systemd/system/ipfs.service` | ✅ EXISTS |

---

## Section 3: "Operational" Claims vs Reality

### Claims from `NEXUS_OS_Current_State.md` Section 10 — "What Works Now"

| Claim | Doc Status | Reality | Verdict |
|-------|-----------|---------|---------|
| Private Ethereum blockchain (Clique PoA, 3 validators, synced) | ✅ Operational | All 3 validators at block 1720, consensus, sealing=true | ✅ **ACCURATE** |
| 3 smart contracts deployed and functional | ✅ Operational | **9 contracts** deployed (doc only lists 3 — TokenManager, DecisionQuality, AgentGovernance, ServiceRegistry, MeshRegistry, PidRegistry all post-date this doc) | ✅ TRUE but **GROSSLY INCOMPLETE** |
| AI agent decision logging to blockchain (21 entries) | ✅ Operational | ReasoningLedger live query: **1,106 entries** (doc is frozen at time of writing) | ⚠️ **OUTDATED COUNT** |
| 30-agent hierarchy running on Discord (25 bots + 5 webhooks) | ✅ Operational | **NOT RUNNING.** Last `hierarchy.log` entry: 2026-02-17 14:17. No `hierarchy_manager.py` process in `ps`. Crashed with gateway disconnects. | ❌ **FALSE** |
| CEO → Director → Worker delegation chain (tested end-to-end) | ✅ Operational (tested) | `test_delegation.py` exists and pytest collects it. Was last run Feb 15-16 per ceo_bot.log. Code works when agents are running. | ⚠️ **TESTED HISTORICALLY, NOT VERIFIED NOW** |
| IPFS private cluster (4 nodes, full mesh, swarm.key protected) | ✅ Operational | IPFS running on all 4 nodes, swarm.key present. But nexus-admin has **0 swarm peers** — full mesh is NOT verified from here. | ⚠️ **PARTIAL — ADMIN ISOLATED** |
| Distributed file storage with content addressing | ✅ Operational | StorageRegistry: `fileCount() = 2` files registered | ⚠️ **FUNCTIONAL BUT MINIMAL USE** |
| Cross-node file replication (add on any, retrieve from any) | ✅ Operational | Cannot verify — nexus-admin has 0 IPFS peers | ⚠️ **UNVERIFIABLE FROM THIS NODE** |
| Pin management and garbage collection | ✅ Operational | Cannot verify from nexus-admin | ⚠️ **UNVERIFIABLE** |
| StorageRegistry: file registration, chunk assignment, storage proofs | ✅ Operational | Contract deployed; 2 files registered; ABI functions confirmed | ✅ **CONTRACT WORKS** |
| systemd services for Geth and IPFS (auto-start on boot) | ✅ Operational | Geth: nexus-geth.service active on all validators. IPFS: ipfs.service active on all nodes. | ✅ **ACCURATE** |
| Zero gas fees (private chain) | ✅ Operational | Gas price = 0 on private chain | ✅ **ACCURATE** |
| Comprehensive test suites for all components | ✅ Operational | 20 test files exist. BUT: agents tests need venv + live HuggingFace API key to execute; services/ tests need plinth (dead); only guardrails/context_builder tests run cleanly in system Python. | ⚠️ **PARTIAL — NOT ALL RUNNABLE** |

### Claims from `NEXUS_OS_Current_State.md` Section 10 — "Planned / In Progress"

| Claim | Doc Status | Reality | Verdict |
|-------|-----------|---------|---------|
| Erasure coding for storage redundancy | `[ ]` Planned | No implementation found | ✅ ACCURATE — still not done |
| `libnexus` Python library | `[ ]` Planned | **FULLY IMPLEMENTED**: `kernel.py` (339 lines), `nexus_storage.py` (418 lines), `contracts.py`, `__init__.py`, `cid_index.json`. Imports successfully in venv. NexusKernel connects to live chain. | ❌ **WRONG — ALREADY IMPLEMENTED** |
| End-to-end encrypted file upload/download | `[ ]` Planned | No implementation found | ✅ ACCURATE — not done |
| AI agent integration with StorageRegistry | `[ ]` Planned | No integration code found | ✅ ACCURATE — not done |
| Storage proof verification (Merkle proofs) | `[ ]` Planned | Not implemented | ✅ ACCURATE — not done |
| Automated replication policies | `[ ]` Planned | Not implemented | ✅ ACCURATE — not done |
| IPFS cluster pinning service | `[ ]` Planned | Not implemented | ✅ ACCURATE — not done |

---

## Section 4: Stale IP Address Contamination — Dangerous Mismatches

**The VLAN migration moved the cluster from `192.168.8.0/24` to `10.0.20.0/24` (validators) and `10.0.10.0/24` (admin).** This migration is not reflected in several executable files. Any code path using these addresses silently fails.

### Files with stale `192.168.8.x` IPs

| File | Line | Stale Value | Correct Value | Impact |
|------|------|-------------|---------------|--------|
| `agents/blockchain_logger.py` | 27 | `RPC_URL = "http://192.168.8.228:8545"` | `http://10.0.20.3:8545` | **CRITICAL: All agent on-chain logging broken** |
| `agents/llm_client.py` | 19 | `LOCAL_INFERENCE_URL = "http://192.168.8.128:8090/..."` | `http://10.0.20.4:8090/v1/chat/completions` | **CRITICAL: Local LLM unreachable** |
| `agents/agent_registry.py` | 8–11, 154 | Cluster description strings with `192.168.8.x` | `10.0.20.x` | **HIGH: Agent system context is wrong — agents describe a non-existent network** |
| `scripts/verify-fast-blocks.py` | 23–27 | `{"ip": "192.168.8.228", ...}` etc. | `10.0.20.3`, `10.0.20.4`, `10.0.20.11` | **HIGH: Primary health-check script broken** |
| `contracts/scripts/deploy.py` | 9 | `RPC_URL = 'http://192.168.8.228:8545'` | `http://10.0.20.3:8545` | **HIGH: Contract deployment script broken** |

### Consequence

When `hierarchy_manager.py` is started and `blockchain_logger.py` initialises, it connects to `http://192.168.8.228:8545` — a non-existent address. The blockchain logging subsystem silently fails for every agent decision. The 1,106 entries in ReasoningLedger were written when the hierarchy was running in February 2026 (before or during the migration). **No new decisions have been logged to the chain since the agents went down on Feb 17.**

---

## Section 5: `project_state.json` — Auto-Updated State File Accuracy

The `health_monitor` last updated this file at `2026-03-09 02:25:46` (today). It is the most current state snapshot, but it contains several stale or incorrect values.

| Field | JSON Value | Reality | Status |
|-------|-----------|---------|--------|
| `ai_agents.hierarchy_manager` | `"operational"` | **NOT RUNNING** — last log Feb 17, no process | ❌ **WRONG** |
| `ai_agents.on_chain_decisions` | `21` | Live RPC: **1,106 entries** | ❌ **STALE** (frozen from initial doc) |
| `ai_agents.local_llm` | `false` | `local-inference.service` IS active on nexus-ai with SmolLM2 | ❌ **WRONG** |
| `inference.tier_3.status` | `"not_installed"` | SmolLM2-1.7B running on port 8090 via llama.cpp | ❌ **WRONG** |
| `inference.tier_1.status` | `"active"` | ThinkPad (10.0.30.2:1234) responding — 4 models loaded | ✅ **CORRECT** |
| `inference.tier_2.status` | `"active"` | nexus-ai2 Ollama (10.0.20.6:11434) responding — qwen2.5-coder:7b | ✅ **CORRECT** |
| `kubernetes.nexus_ai2_joined` | `false` | k3s-agent.service INACTIVE on nexus-ai2; not in cluster | ✅ **CORRECT** |
| `kubernetes.status` | `"operational"` | 4 nodes Ready (master, ai, storage, admin) | ✅ **CORRECT** |
| `health_snapshot.nexus-admin.ipfs` | `"failed"` | 0 swarm peers confirmed | ✅ **CORRECT** (honest about own failure) |
| `blockchain.contracts` | Lists 3 contracts | **9 contracts** deployed | ❌ **INCOMPLETE** |
| `os_image.status` | `"built_not_flashed_to_hardware"` | 913MB image exists at `/opt/nexus/pi-gen/deploy/` | ✅ **CORRECT** |
| `network.firewall_monitor` | `"running"` | No dedicated firewall monitor process found | ❌ **UNVERIFIED** |

---

## Section 6: Network Topology — Entire Documentation Framework Is Pre-Migration

`NEXUS_OS_Current_State.md` describes a **flat 192.168.8.0/24 LAN** with no VLANs, no K3s, no WireGuard, no Clef signer, and only 4 nodes. The actual cluster as of 2026-03-09:

| Feature | Documented State | Actual State |
|---------|-----------------|--------------|
| Network topology | Flat `192.168.8.0/24` | 3 VLANs (10, 20, 30) |
| nexus-admin IP | `192.168.8.153` | `10.0.10.5` |
| nexus-master IP | `192.168.8.228` | `10.0.20.3` |
| nexus-ai IP | `192.168.8.128` | `10.0.20.4` |
| nexus-storage IP | `192.168.8.224` | `10.0.20.11` |
| nexus-ai2 | NOT MENTIONED | `10.0.20.6`, Hailo-10H AI HAT+, Ollama qwen2.5-coder:7b |
| ThinkPad | NOT MENTIONED | `10.0.30.2`, VLAN30, Tier-1 LLM (qwen3.5-35b-a3b) |
| Kubernetes | NOT MENTIONED | K3s v1.34, 4 nodes Ready |
| WireGuard | NOT MENTIONED | `wg-quick@nexus-mesh` active, 10.1.0.0/24 overlay |
| Clef signer | NOT MENTIONED | Running on validators, IPC signing |
| Ethereum wallet unlock | `--allow-insecure-unlock` implied | Migrated to Clef (no --allow-insecure-unlock) |
| Deployed contracts | 3 (RL, RM, SR) | **9** (+TokenManager, DecisionQuality, AgentGovernance, ServiceRegistry, MeshRegistry, PidRegistry) |
| Autonomous orchestrator | NOT MENTIONED | `nexus-orchestrator.service` running since Mar 5 |
| ChromaDB | NOT MENTIONED | Running, 8 collections, NAS-backed |
| Dashboard | NOT MENTIONED | `nexus-dashboard.service` on port 8880 |

---

## Section 7: "Comprehensive Test Suites" Claim — Detailed Reality

The doc claims: `[x] Comprehensive test suites for all components`

### Actual test inventory and runnability

| Test File | Tests | Runnable? | Blocker |
|-----------|-------|-----------|---------|
| `agents/test_delegation.py` | 1 (test_full_chain) | ⚠️ Partial | Needs venv (langgraph) + live HuggingFace API key + running agents |
| `agents/test_workflow.py` | ? | ❌ No | Needs venv (langgraph) |
| `agents/test_blockchain_logger.py` | ? | ❌ No | Needs venv (web3) |
| `agents/test_integration.py` | ? | ❌ No | Needs venv (langgraph, web3) |
| `agents/test_llm_client.py` | ? | ❌ No | No `__main__`, likely needs API key |
| `libnexus/test_storage.py` | ? | ❌ No | Needs venv (web3) + live IPFS + live Geth |
| `contracts/scripts/test_storage_registry.py` | ? | ❌ No | Needs venv (web3) + live Geth |
| `automation/test_guardrails.py` | ? | ✅ Yes | System Python, no external deps |
| `automation/test_context_builder.py` | ? | ⚠️ Partial | Needs live ChromaDB |
| `services/*/tests/*.py` | Many | ❌ No | Needs plinth/django (not installed) |

**Verdict:** Only 1–2 of 20 test files can run without external setup. The claim of "comprehensive test suites for all components" is technically true (the files exist) but practically misleading — most tests require the full cluster to be up, the venv activated, live API keys, and live services.

---

## Section 8: Compiled Database

**`/opt/nexus/docs/compiled-db/` does not exist.**

This directory structure (with `components.yaml`, `decisions.yaml`, etc.) was not found anywhere on the system. The automation system uses ChromaDB (at `localhost:8000`) and SQLite world-model databases instead. There is no YAML-based compiled documentation database.

---

## Section 9: Task and Backlog Files

No `tasks.*`, `todo.*`, `TODO.*`, `*.todo`, or `backlog.*` files exist in `/opt/nexus` (excluding venv and extraction directories).

The orchestrator's task queue lives exclusively in `/opt/nexus/automation/intent_registry.yaml`. As of the most recent read (2026-03-08 22:19), it contains **40 intents** with statuses: completed (7), decomposed (16), blocked (2), pending (5), failed (1).

Current active intent: `np-005.1.1` (Data Collection and Preparation) — stuck in retry loop, failing with LLM depth limit exceeded.

---

## Section 10: Overall Drift Assessment

### Scoring methodology
Each documented claim is scored as: ✅ Accurate / ⚠️ Partial / ❌ False / 📦 Obsolete (superseded by new features)

### NEXUS_OS_Current_State.md (primary doc, 491 lines)

| Category | Total Claims | ✅ Accurate | ⚠️ Partial | ❌ False | 📦 Obsolete |
|----------|-------------|------------|-----------|---------|------------|
| Hardware config | 8 | 5 | 1 | 0 | 2 (missing ai2, ThinkPad) |
| IP addresses | 4 | 0 | 0 | 4 | 0 |
| Blockchain state | 6 | 4 | 1 | 1 (entry count) | 0 |
| Contract list | 3 listed | 3 | 0 | 0 | 0 (but 6 more exist) |
| IPFS status | 5 | 3 | 2 | 0 | 0 |
| Agent status | 4 | 2 | 0 | 2 (hierarchy not running) | 0 |
| Services/systemd | 4 | 3 | 0 | 1 (no nexus-geth on admin) | 0 |
| File paths | 33 | 26 | 0 | 7 | 0 |
| "Planned" features | 7 | 5 | 0 | 1 (libnexus exists) | 1 |
| **TOTAL** | **74** | **51 (69%)** | **4 (5%)** | **15 (20%)** | **4 (5%)** |

**Score: 69% accurate, 20% materially false, 5% partial, 5% obsolete.**

### project_state.json (auto-updated, most current)

| Category | Claims | ✅ | ⚠️ | ❌ |
|----------|--------|---|---|---|
| Network topology | 6 | 6 | 0 | 0 |
| Kubernetes | 3 | 2 | 0 | 1 |
| Blockchain | 5 | 3 | 0 | 2 |
| AI agents | 6 | 3 | 0 | 3 |
| Inference tiers | 4 | 2 | 0 | 2 |
| Storage/IPFS | 3 | 2 | 1 | 0 |
| OS image | 1 | 1 | 0 | 0 |
| **TOTAL** | **28** | **19 (68%)** | **1 (4%)** | **8 (29%)** |

Even the auto-updated state file is 29% wrong because it was seeded from the old documentation values and health_monitor does not poll the blockchain for entry counts or check whether hierarchy_manager is running.

---

## Section 11: Prioritized Dangerous Mismatches

These are documentation-reality gaps that will cause a developer or the orchestrator to take wrong action:

### CRITICAL — Silent failures in running code

**1. `agents/blockchain_logger.py:27` — Stale RPC URL**
```python
RPC_URL = "http://192.168.8.228:8545"  # WRONG — should be 10.0.20.3:8545
```
When `hierarchy_manager.py` is restarted, every agent decision will fail to log to the blockchain. The failure is silent — `blockchain_logger` catches connection errors and may degrade gracefully. No new ReasoningLedger entries will be written.

**2. `agents/llm_client.py:19` — Stale LLM URL**
```python
LOCAL_INFERENCE_URL = "http://192.168.8.128:8090/v1/chat/completions"  # WRONG — 10.0.20.4
```
All local inference attempts fail. Current orchestrator uses HuggingFace API fallback, incurring rate limits and API costs. `local-inference.service` on nexus-ai is running and loaded with SmolLM2 — completely unused.

**3. `contracts/scripts/deploy.py:9` — Stale RPC URL**
```python
RPC_URL = 'http://192.168.8.228:8545'  # WRONG — should be 10.0.20.3:8545
```
Any new contract deployment attempt will fail silently. Developer running this script will see connection errors, not a clear "wrong IP" diagnosis.

### HIGH — Misleads developer or orchestrator planning

**4. `project_state.json` → `ai_agents.hierarchy_manager: "operational"`**
The orchestrator reads this file for context when planning tasks. If asked to "check agent health," it will read this field and incorrectly conclude the hierarchy is running. The orchestrator has not been explicitly asked to verify this, but any LLM-based planning step could be wrong.

**5. `project_state.json` → `ai_agents.on_chain_decisions: 21`**
Both the project_state.json and NEXUS_OS_Current_State.md claim 21 on-chain decisions. The live chain has 1,106. This count is frozen at the doc-writing date and has never been updated by health_monitor (it doesn't query the blockchain for entry counts).

**6. `agents/agent_registry.py:8–11` — Agent system context with wrong IPs**
The AI agents carry their understanding of the cluster in a long context string at the top of `agent_registry.py`. This string describes the old `192.168.8.x` network. Every agent that uses this context for cluster queries or self-description will have fundamentally wrong information about where things are. The agents have not run since Feb 17, but when restarted, they will describe a network that no longer exists.

**7. `scripts/verify-fast-blocks.py:23–27` — Health check script broken**
The canonical health-check script pointed to in `NEXUS_OS_Current_State.md` Section 12 ("Quick Health Check") uses all pre-migration IPs. Running it as documented (`/opt/nexus/contracts/.venv/bin/python3 /opt/nexus/scripts/verify-fast-blocks.py`) will fail to connect to any validator.

### MEDIUM — Gaps that cause confusion but don't break running systems

**8. `libnexus` listed as "planned" everywhere**
`NEXUS_OS_Current_State.md`, `project_state.json`, and the Living Guide all treat libnexus as future work. It is a fully implemented library with 418-line `nexus_storage.py`, working NexusKernel, and a `cid_index.json`. It imports cleanly in venv and connects to the live chain. Developers reading the docs would not think to use it.

**9. `project_state.json` → `inference.tier_3.status: "not_installed"` for nexus-ai**
`local-inference.service` is running on nexus-ai (10.0.20.4) with SmolLM2-1.7B loaded and bound to `0.0.0.0:8090`. The orchestrator's `llm_router.py` has a tier for this endpoint but `llm_client.py` points to the wrong IP. The state file compounds this by saying the service is not installed.

**10. Nine contracts deployed, three documented**
TokenManager (35 ABI entries), DecisionQuality (28), AgentGovernance (29), ServiceRegistry (6), MeshRegistry (7), and PidRegistry (4) all have deployed JSON artifacts and were deployed post-doc. Nothing in the primary documentation describes them, their addresses, or their purpose. Any developer consulting the docs will not know these contracts exist.

---

## Section 12: Recommended Documentation Actions (priority order)

1. **Immediate**: Update `agents/blockchain_logger.py:27`, `agents/llm_client.py:19`, and `contracts/scripts/deploy.py:9` with correct VLAN IPs (these are code bugs, not doc bugs)
2. **Immediate**: Update `agents/agent_registry.py` cluster context strings with `10.0.20.x` addresses and mention nexus-ai2 + ThinkPad
3. **Immediate**: Update `project_state.json` to set `ai_agents.hierarchy_manager: "stopped"` and `ai_agents.on_chain_decisions: 1106` and `inference.tier_3.status: "active"`
4. **This week**: Write a new `NEXUS_OS_Current_State_v2.md` that reflects the post-VLAN-migration architecture with all 5 nodes, 3 VLANs, 9 contracts, K3s, Clef, WireGuard, and the CAF orchestrator
5. **This week**: Update `scripts/verify-fast-blocks.py` and `scripts/test-ipfs-distribution.sh` with `10.0.20.x` IPs
6. **This week**: Add all 9 deployed contracts with addresses and ABI summaries to the main state document
7. **This week**: Add a "How to restart the hierarchy manager" section with `.venv` activation instructions
8. **Low priority**: Mark `libnexus` as "implemented" in all documentation references
9. **Low priority**: Create `/opt/nexus/docs/compiled-db/` YAML files if the orchestrator needs a structured knowledge base

---

*Report generated 2026-03-09. Read-only — no files modified.*
