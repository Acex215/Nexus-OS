# NEXUS OS Codebase Map
**Generated:** 2026-03-09
**Scope:** /opt/nexus (excluding .git, __pycache__, .venv, extraction/, pi-gen/, ipfs/datastore/)
**Python runtime:** /usr/bin/python3 3.13.5 (system); /opt/nexus/contracts/.venv (Python venv for blockchain scripts)

---

## Section 1: Complete File Inventory

### Python Files

| Path | Lines | Last Modified | Purpose | Entry Point |
|------|-------|---------------|---------|-------------|
| **agents/** | | | | |
| agents/agent_registry.py | 1004 | 2026-02-14 | Registry of all 30 Discord bot agents (tokens, roles, hierarchy) | N |
| agents/agent_workflow.py | 343 | 2026-02-14 | LangGraph-based agent workflow state machine | N |
| agents/blockchain_logger.py | 233 | 2026-02-14 | Async blockchain event logger (writes to ReasoningLedger) | N |
| agents/ceo_bot.py | 302 | 2026-02-14 | CEO Discord bot with command handling | Y (__main__) |
| agents/hierarchy_manager.py | 560 | 2026-02-14 | Runs all 25 agent bots concurrently via Discord.py | Y (__main__) |
| agents/invite_bots.py | 422 | 2026-02-14 | OAuth2 invite generator for all bot tokens | Y (__main__) |
| agents/llm_client.py | 389 | 2026-02-16 | Async LLM client with local+HuggingFace fallback, rate limiting | N |
| agents/test_blockchain_logger.py | 172 | 2026-02-14 | pytest tests for blockchain_logger | Y (__main__) |
| agents/test_delegation.py | 99 | 2026-02-14 | pytest tests for delegation workflow | Y (__main__) |
| agents/test_integration.py | 231 | 2026-02-14 | Integration tests for agent workflow | Y (__main__) |
| agents/test_llm_client.py | 113 | 2026-02-14 | pytest tests for llm_client | N |
| agents/test_workflow.py | 166 | 2026-02-14 | pytest tests for agent_workflow | Y (__main__) |
| agents/verify_system.py | 248 | 2026-02-14 | System health verification script | Y (__main__) |
| **automation/** | | | | |
| automation/audit_logger.py | 108 | 2026-03-02 | Append-only JSONL audit log writer | N |
| automation/build_world_model.py | 631 | 2026-03-02 | Builds SQLite world-model DB from codebase scan | Y (__main__) |
| automation/chroma_memory.py | 52 | 2026-03-02 | ChromaDB HTTP client wrapper (remember/recall/seed) | Y (__main__) |
| automation/command_executor.py | 625 | 2026-03-05 | Allowlisted shell command executor with sandboxing | N |
| automation/context_builder.py | 458 | 2026-03-02 | Assembles LLM context from ChromaDB + world model | N |
| automation/create_collections.py | 76 | 2026-03-02 | One-shot ChromaDB collection creator | Y (__main__) |
| automation/dev_orchestrator.py | 1216 | 2026-03-05 | Central autonomous dev orchestrator (main service) | Y (__main__) |
| automation/discord_comms.py | 530 | 2026-03-05 | Discord CAF thread for send_notification/request_approval | N |
| automation/discord_reporter.py | 116 | 2026-03-03 | One-shot Discord message sender via REST API | N |
| automation/execution_engine.py | 427 | 2026-03-03 | Validates and executes multi-step plans | N |
| automation/failure_analyzer.py | 300 | 2026-03-05 | Classifies and records task failures | N |
| automation/feedback_loop.py | 427 | 2026-03-02 | Stores lessons learned in SQLite, writes change ledger | N |
| automation/git_monitor.py | 143 | 2026-03-02 | Monitors git repo for new commits, triggers reindex | N |
| automation/guardrails.py | 303 | 2026-03-02 | Command allowlist, path protection, sanitization | N |
| automation/health_monitor.py | 474 | 2026-03-02 | SSH-based cluster health checks (geth, k3s, ipfs, disk) | N |
| automation/hid_controller.py | 278 | 2026-03-03 | Pi Pico HID keyboard/mouse controller via USB serial | N |
| automation/indexer.py | 1056 | 2026-03-02 | Full codebase indexer to SQLite + ChromaDB | Y (__main__) |
| automation/intent_parser.py | 350 | 2026-03-03 | Parses natural-language intents from Discord messages | N |
| automation/llm_router.py | 206 | 2026-03-03 | 3-tier LLM routing (ThinkPad→nexus-ai2→nexus-master) | N |
| automation/persona.py | 291 | 2026-03-03 | Formats LLM output with NEXUS personality | N |
| automation/planning_engine.py | 523 | 2026-03-05 | Reads intent_registry.yaml, selects/decomposes intents | N |
| automation/proactive_tasks.py | 183 | 2026-03-03 | Generates proactive maintenance tasks | N |
| automation/seed_knowledge.py | 42 | 2026-03-02 | One-shot ChromaDB knowledge seeder | N |
| automation/subagent_client.py | 114 | 2026-03-03 | Ollama HTTP client for nexus-master (port 11434) | N |
| automation/system_queries.py | 293 | 2026-03-03 | System status queries (k3s, geth, disk, etc.) | N |
| automation/task_planner.py | 367 | 2026-03-05 | Generates shell-command execution plans via LLM | N |
| automation/test_context_builder.py | 262 | 2026-03-02 | pytest tests for context_builder | N |
| automation/test_guardrails.py | 205 | 2026-03-02 | pytest tests for guardrails + execution_engine | Y (__main__) |
| automation/web_research.py | 244 | 2026-03-02 | Web scraping research helper | N |
| **contracts/scripts/** | | | | |
| contracts/benchmark_fast.py | 118 | 2026-02-15 | Blockchain latency benchmark | N |
| contracts/scripts/deploy.py | 100 | 2026-02-14 | Deploy core contracts (ReasoningLedger, etc.) | N |
| contracts/scripts/deploy_pid_registry.py | 73 | 2026-02-22 | Deploy PidRegistry contract | N |
| contracts/scripts/deploy_service_registry.py | 73 | 2026-02-22 | Deploy ServiceRegistry contract | N |
| contracts/scripts/deploy_storage_registry.py | 95 | 2026-02-15 | Deploy StorageRegistry contract | N |
| contracts/scripts/test_storage_registry.py | 270 | 2026-02-15 | Test StorageRegistry contract interactions | N |
| **core/** | | | | |
| core/__init__.py | 0 | 2026-02-22 | Empty package marker | N |
| core/action_utils.py | 850 | 2026-02-22 | FreedomBox-derived privileged action utilities | N |
| core/service_framework.py | 331 | 2026-02-22 | NexusService base class with SQLite config + blockchain | N |
| **libnexus/** | | | | |
| libnexus/__init__.py | 3 | 2026-02-14 | Exports NexusKernel from kernel.py | N |
| libnexus/contracts.py | 23 | 2026-02-14 | Loads deployed contract ABI+address from JSON files | N |
| libnexus/kernel.py | 339 | 2026-02-22 | NexusKernel: web3 connection, contract access, IPFS | N |
| libnexus/nexus_storage.py | 418 | 2026-02-15 | IPFS upload/download/verify with on-chain CID registry | Y (__main__) |
| libnexus/setup.py | 13 | 2026-02-14 | pip setup.py for libnexus package | N |
| libnexus/test_storage.py | 207 | 2026-02-15 | Tests for NexusStorage | Y (__main__ implied by script structure) |
| **networking/** | | | | |
| networking/degradation_manager.py | 440 | 2026-02-22 | Network degradation detection + fallback routing | Y (__main__) |
| networking/flipper_bridge.py | 409 | 2026-02-22 | Flipper Zero RF bridge for out-of-band comms | Y (__main__) |
| networking/mesh_discovery.py | 185 | 2026-02-22 | BATMAN-adv mesh node discovery + blockchain registration | Y (__main__) |
| networking/rf_mesh_daemon.py | 435 | 2026-02-22 | RF mesh packet routing daemon (Flipper Zero + serial) | Y (__main__) |
| networking/rf_relay.py | 245 | 2026-02-22 | RF packet encoding/decoding (MsgType enum, RFPacket) | N |
| **scripts/** | | | | |
| scripts/phase2_validation.py | 315 | 2026-02-14 | Phase 2 cluster validation suite | N |
| scripts/register_nodes.py | 73 | 2026-02-14 | Registers cluster nodes via NexusKernel | N |
| scripts/verify-fast-blocks.py | 459 | 2026-02-15 | Block performance verification across validators | Y (__main__) |
| **services/** (FreedomBox-derived, require `plinth` — NOT installed) | | | | |
| services/backups/* | ~3000 | 2026-02-22 | Borg backup management (14 files) | N |
| services/firewall/* | ~1000 | 2026-02-22 | nftables firewall management (7 files) | N |
| services/networks/* | ~1500 | 2026-02-22 | NetworkManager integration (8 files) | N |
| services/storage/* | ~2000 | 2026-02-22 | UDisks2 storage management (10 files) | N |

**Total Python lines:** ~29,657

### Non-Python Files of Note

| Path | Purpose |
|------|---------|
| agents/.env | All 30 Discord bot tokens + HuggingFace API key |
| automation/constitution.json | Orchestrator identity, principles, protected file list |
| automation/intent_registry.yaml | Task backlog (ns-001...) for autonomous orchestrator |
| automation/NEXUS_Living_Guide.md | Orchestrator living documentation (self-updated) |
| automation/change_ledger.md | Agent-written change log |
| automation/project_state.json | JSON health/status snapshot updated by health_monitor |
| contracts/deployed/*.json | ABI + checksummed addresses for all deployed contracts |
| contracts/source/*.sol | Solidity source for 6 contracts |
| networking/degradation_log.json | Network degradation event history |

---

## Section 2: Module Dependency Graph

### agents/

```
agents/hierarchy_manager.py
  → agents/agent_registry.py
  → agents/agent_workflow.py
  → agents/blockchain_logger.py
  → agents/llm_client.py
  [EXTERNAL] discord, dotenv

agents/ceo_bot.py
  → agents/agent_workflow.py
  → agents/blockchain_logger.py
  → agents/llm_client.py
  [EXTERNAL] discord, dotenv

agents/agent_workflow.py
  → agents/agent_registry.py
  → agents/llm_client.py
  [EXTERNAL] langgraph (in .venv, NOT system python)

agents/blockchain_logger.py
  [EXTERNAL] web3 (in .venv, NOT system python)

agents/llm_client.py
  [EXTERNAL] aiohttp, dotenv
  [STALE IP] LOCAL_INFERENCE_URL = "http://192.168.8.128:8090/..." (pre-VLAN migration)

agents/verify_system.py
  → agents/agent_registry.py
  → agents/blockchain_logger.py

agents/invite_bots.py
  → agents/agent_registry.py
```

### automation/

```
automation/dev_orchestrator.py  [main service — nexus-orchestrator.service]
  → automation/chroma_memory.py
  → automation/planning_engine.py
  → automation/context_builder.py
  → automation/llm_router.py
  → automation/task_planner.py
  → automation/web_research.py
  → automation/audit_logger.py
  → automation/feedback_loop.py
  → automation/health_monitor.py
  → automation/git_monitor.py
  → automation/discord_comms.py
  → automation/discord_reporter.py
  → automation/persona.py
  → automation/failure_analyzer.py
  → automation/execution_engine.py  [lazy import at line 394, 482]
  → automation/proactive_tasks.py   [lazy import at lines 918, 933, 1016]

automation/discord_comms.py
  → automation/command_executor.py  [lazy import at line 342]
  → automation/system_queries.py    [lazy import at line 344]
  [EXTERNAL] discord, dotenv
  [HARDCODED] loads /opt/nexus/agents/.env directly

automation/audit_logger.py
  → automation/guardrails.py

automation/execution_engine.py
  → automation/guardrails.py

automation/failure_analyzer.py
  → automation/llm_router.py
  → automation/guardrails.py

automation/feedback_loop.py
  → automation/llm_router.py

automation/task_planner.py
  → automation/llm_router.py

automation/seed_knowledge.py
  → automation/chroma_memory.py
  (no main guard — runs at import time)

automation/proactive_tasks.py
  → automation/subagent_client.py   [lazy import at line 90]

automation/context_builder.py
  → automation/chroma_memory.py     [via _get_chroma()]

automation/chroma_memory.py
  [EXTERNAL] chromadb (HttpClient → localhost:8000 — requires chromadb.service)

automation/subagent_client.py
  [EXTERNAL] requests
  [ENDPOINT] http://10.0.20.3:11434 (Ollama on nexus-master — may not be running)
```

### libnexus/

```
libnexus/__init__.py
  → libnexus/kernel.py

libnexus/kernel.py
  → libnexus/contracts.py
  [EXTERNAL] web3 (NOT in system python — only in .venv)

libnexus/nexus_storage.py
  [EXTERNAL] web3, requests (NOT in system python)

libnexus/contracts.py
  (stdlib only — loads JSON from contracts/deployed/)
```

### networking/

```
networking/mesh_discovery.py
  → libnexus (NexusKernel)
  [EXTERNAL] web3 (via libnexus — NOT in system python)

networking/rf_mesh_daemon.py
  → networking/rf_relay.py
  → networking/flipper_bridge.py
  → libnexus (NexusKernel — lazy import at line 137)

networking/degradation_manager.py
  → libnexus (NexusKernel — lazy import at line 325)

networking/flipper_bridge.py
  → networking/rf_relay.py
  [EXTERNAL] serial (pyserial — IS in system python via pip)

networking/rf_relay.py
  (stdlib only)
```

### core/

```
core/service_framework.py
  → libnexus (NexusKernel — lazy import at line 42)
  [EXTERNAL] web3 (NOT in system python)

core/action_utils.py
  → core/actions  [subpackage — exists as /opt/nexus/core/actions/service-ctl binary, NOT a Python module]
  [EXTERNAL] augeas (NOT installed anywhere)
```

### contracts/scripts/

```
All scripts:
  [EXTERNAL] web3 (NOT in system python — must use .venv)
  scripts use hardcoded RPC: http://localhost:8545

scripts/phase2_validation.py
  → libnexus (NexusKernel)

scripts/register_nodes.py
  → libnexus (NexusKernel)

scripts/verify-fast-blocks.py
  sys.path.insert(0, "/opt/nexus/agents")  [non-standard path manipulation]
  [EXTERNAL] web3 (NOT in system python)
```

### services/ (entire subtree)

```
ALL services/ files:
  [EXTERNAL] plinth (FreedomBox framework — NOT installed, ModuleNotFoundError)
  [EXTERNAL] django (NOT installed)
  [EXTERNAL] augeas (NOT installed)
  These modules are INOPERABLE in current environment.
```

---

## Section 3: Broken Imports

### Critical — runtime failures in production services

**1. `agents/llm_client.py` — Stale IP address (not a Python import error, but a connectivity break)**
- Line 19: `LOCAL_INFERENCE_URL = "http://192.168.8.128:8090/v1/chat/completions"`
- `192.168.8.128` is a pre-VLAN-migration IP. The correct post-migration address is `http://10.0.20.4:8090/v1/chat/completions`
- **Impact:** All agent-tier LLM calls will fail to reach the local inference endpoint. HuggingFace API fallback will be used instead.

**2. `agents/agent_workflow.py` — langgraph not in system Python**
- Line 15: `from langgraph.graph import END, StateGraph`
- `langgraph` is installed in `/opt/nexus/contracts/.venv` but NOT in `/usr/bin/python3` (system Python 3.13)
- The `nexus-orchestrator.service` runs with `/usr/bin/python3`
- **Impact:** `hierarchy_manager.py`, `ceo_bot.py`, `agent_workflow.py` all fail to import when run from the system Python that services use. These run from `/opt/nexus/agents/` directory which has no venv activation.
- **Verification:** `langgraph` is absent from system `pip3 list`; present only in `.venv`.

**3. `agents/blockchain_logger.py` — web3 not in system Python**
- Line 20-21: `from web3 import Web3; from web3.middleware import ExtraDataToPOAMiddleware`
- `web3` is in `.venv` only. System Python 3.13: `ModuleNotFoundError: No module named 'web3'`
- **Impact:** `blockchain_logger.py` (imported by `hierarchy_manager.py`, `ceo_bot.py`, `verify_system.py`) cannot be loaded via system Python.

**4. `core/action_utils.py` — augeas not installed + broken relative import**
- Line 14: `import augeas` — `augeas` Python bindings not installed anywhere (not in system pip, not in .venv)
- Line 16: `from . import actions` — `/opt/nexus/core/actions/` contains a binary (`service-ctl`), not a Python package. No `__init__.py` exists there.
- **Impact:** `core/action_utils.py` is completely non-functional. Any code importing it will fail immediately.

**5. `libnexus/kernel.py`, `libnexus/nexus_storage.py` — web3 not in system Python**
- Both require `web3`, which is only in `.venv`
- All callers using system Python (`networking/mesh_discovery.py`, `scripts/phase2_validation.py`, `scripts/register_nodes.py`, `core/service_framework.py`, `scripts/verify-fast-blocks.py`) will fail unless run with `.venv/bin/python3`
- `networking/mesh_discovery.py` and `scripts/register_nodes.py` are run directly (no venv), making them broken.

**6. Entire `services/` subtree — plinth/django not installed**
- Every file in `services/{backups,firewall,networks,storage}/` imports from `plinth` and `django`
- Neither framework is installed on this system (`ModuleNotFoundError: No module named 'plinth'`)
- These are FreedomBox modules extracted to `/opt/nexus/extraction/freedombox/` and copied here
- **Impact:** The entire `services/` subtree is INOPERABLE in the current environment. These appear to be aspirational FreedomBox integrations not yet wired into the NEXUS runtime.

**7. `automation/discord_comms.py` — hardcoded channel ID**
- Line 36: `CHANNEL_ID: int = 1446026349528616990`
- This is not a broken import but a hardcoded constant that bypasses the `.env` file for channel selection. The `CAF_CHANNEL_ID` env var exists in `discord_reporter.py` but `discord_comms.py` ignores it.

**8. `automation/subagent_client.py` — endpoint likely offline**
- Line 23: `SUBAGENT_URL = "http://10.0.20.3:11434"` (Ollama API on nexus-master)
- Per project memory, nexus-master runs Geth + K3s control-plane, not an LLM inference server. Port 11434 is Ollama — it is unclear if Ollama is deployed on nexus-master. The known LLM endpoint is nexus-ai at `:8090`.
- **Impact:** `proactive_tasks.py` (which imports this) will silently fail health checks.

### Summary table

| File | Line | Import | Status |
|------|------|--------|--------|
| agents/agent_workflow.py | 15 | `from langgraph.graph import END, StateGraph` | BROKEN (not in system Python) |
| agents/blockchain_logger.py | 20 | `from web3 import Web3` | BROKEN (not in system Python) |
| core/action_utils.py | 14 | `import augeas` | BROKEN (not installed anywhere) |
| core/action_utils.py | 16 | `from . import actions` | BROKEN (actions/ is a binary, not a package) |
| libnexus/kernel.py | 2-3 | `from web3 import Web3` | BROKEN in system Python |
| libnexus/nexus_storage.py | 27-28 | `from web3 import Web3` | BROKEN in system Python |
| services/\*/\*.py | multiple | `from plinth import ...` | BROKEN (plinth not installed) |
| services/\*/\*.py | multiple | `from django import ...` | BROKEN (django not installed) |
| services/firewall/privileged.py | 7 | `import augeas` | BROKEN (not installed) |

---

## Section 4: Dead Code Candidates

Files meeting the dead code criteria: not imported by any other /opt/nexus file, no `__main__` block, and not referenced in any .service file.

### Definite dead code (zero imports, no main, no service reference)

| File | Reason |
|------|--------|
| `automation/seed_knowledge.py` | Not imported, no `__main__`, no service reference. Script body executes at top level (will run on import). One-shot seeder that should have been run once during setup. |
| `automation/hid_controller.py` | Not imported by anything, no `__main__`. HID Pico controller orphaned — not wired into dev_orchestrator or any service. |
| `agents/test_llm_client.py` | Not imported, no `__main__` block. pytest test file but missing `if __name__ == "__main__"`. |

### Probable dead code (no main, no service, low or zero import count)

| File | Imported By | Notes |
|------|-------------|-------|
| `services/backups/schedule.py` | 0 | Not imported internally; FreedomBox module needing plinth. |
| `services/backups/urls.py` | 0 | Django URL config; plinth not installed. |
| `services/backups/__init__.py` | 0 | Top-level BackupsApp; not registered in any nexus framework. |
| `services/networks/__init__.py` | 0 | NetworksApp; not registered. |
| `services/networks/urls.py` | 0 | Django URL config; plinth not installed. |
| `services/firewall/__init__.py` | 0 | FirewallApp; not registered. |
| `services/firewall/urls.py` | 0 | Django URL config. |
| `services/storage/__init__.py` | 0 | StorageApp; not registered. |
| `services/storage/udisks2.py` | 0 | UDisks2 D-Bus proxy; not imported by nexus code. |
| `services/storage/urls.py` | 0 | Django URL config. |
| `core/action_utils.py` | 0 | Not imported by any nexus file; broken imports (augeas, core.actions). |
| `automation/test_context_builder.py` | 0 | Test file, no `__main__`. |
| `scripts/phase2_validation.py` | 0 | Validation script; no main block, not in any service. |
| `scripts/register_nodes.py` | 0 | Manual setup script; no main block, not in any service. |
| `libnexus/setup.py` | 0 | pip setup.py; not a runtime module. |
| `libnexus/contracts.py` | 1 (libnexus/kernel.py) | Minimal JSON loader; functionally used. |

### Note on entire services/ subtree
The 39 Python files under `services/` are all inoperable (see Section 3) and none are imported by any operational nexus code. They appear to be extracted FreedomBox source intended for future integration. Treating the entire `services/` tree as aspirational/dead code is accurate for the current deployment.

---

## Section 5: Duplicate Definitions

### Cross-file duplicate functions (by name)

| Function | Files | Assessment |
|----------|-------|-----------|
| `backup_file` | `automation/dev_orchestrator.py`, `automation/execution_engine.py` | **Diverged copies.** `dev_orchestrator.py` version (line 187) is simple subprocess cp; `execution_engine.py` version (line ~130) is more sophisticated with manifest.json for rollback. Agent likely added the execution_engine version without removing the older one. The dev_orchestrator version should be removed and replaced with a call to execution_engine. |
| `is_protected` | `automation/dev_orchestrator.py`, `automation/build_world_model.py` | **Semantically different.** `dev_orchestrator.py` uses a glob-based string match on `PROTECTED` list; `build_world_model.py` uses a set of `PROTECTED_NAMES` + `PROTECTED_EXTS`. These serve the same purpose but are not interchangeable. The dev_orchestrator version should import from a shared module. |
| `_strip_json` | `automation/feedback_loop.py`, `automation/task_planner.py` | **Identical implementation** — same regex, same logic. Classic agent-generated copy-paste. Should be extracted to a shared utility. |
| `mtime_iso` | `automation/build_world_model.py`, `automation/indexer.py` | **Identical implementation.** Both compute ISO timestamp from path mtime. Agent-generated duplicate. |
| `open_db` | `automation/build_world_model.py`, `automation/indexer.py` | **Slightly different signatures** (`build_world_model.py` has `force` parameter). Both create SQLite connections with similar schemas. Agent-generated near-duplicate. |
| `main` | `automation/build_world_model.py`, `automation/indexer.py`, `networking/mesh_discovery.py`, `networking/rf_mesh_daemon.py`, `networking/degradation_manager.py`, `libnexus/nexus_storage.py` | Normal — each file has its own `main()` function as its entry point. Not a problem. |
| `setup` | `services/backups/privileged.py`, `services/firewall/privileged.py`, `services/networks/privileged.py`, `services/storage/privileged.py` | FreedomBox pattern — each service module has a `setup()` function. Expected duplication. |
| `get_disks` | `services/storage/__init__.py`, `services/storage/udisks2.py` | FreedomBox split (sync vs D-Bus version). Expected. |

### Duplicate class names

No true duplicate class names across files. All classes are uniquely named (verified via grep).

### Assessment of agent-generated duplicates

The functions `_strip_json`, `mtime_iso`, and `backup_file` (the simpler version in dev_orchestrator) are strong candidates for agent-generated duplicates. The automation/ files were created between 2026-03-02 and 2026-03-05 in rapid succession, consistent with multi-step agent code generation. The `is_protected` duplication is more subtle — the two versions have different logic, suggesting they were written independently for different contexts without cross-module awareness.

---

## Section 6: Environment Variables

### Variables defined in `.env` files

**`/opt/nexus/agents/.env`** (chmod 600, 55 variables):

```
HUGGINGFACE_API_KEY
GUILD_ID
CEO_TOKEN
COO_TOKEN
COMPUTE_DIRECTOR_TOKEN
STORAGE_DIRECTOR_TOKEN
NETWORK_DIRECTOR_TOKEN
SECURITY_DIRECTOR_TOKEN
BLOCKCHAIN_DIRECTOR_TOKEN
ML_DIRECTOR_TOKEN
QUANTUM_DIRECTOR_TOKEN
COMPUTE_WORKER_1_TOKEN .. COMPUTE_WORKER_3_TOKEN
STORAGE_WORKER_1_TOKEN .. STORAGE_WORKER_3_TOKEN
NETWORK_WORKER_1_TOKEN .. NETWORK_WORKER_3_TOKEN
SECURITY_WORKER_1_TOKEN .. SECURITY_WORKER_3_TOKEN
BLOCKCHAIN_WORKER_1_TOKEN .. BLOCKCHAIN_WORKER_3_TOKEN
ML_WORKER_1_TOKEN .. ML_WORKER_3_TOKEN
QUANTUM_WORKER_1_TOKEN .. QUANTUM_WORKER_3_TOKEN
CAF_DISCORD_TOKEN
CAF_CHANNEL_ID
```

**No `.env` file exists in `automation/`**. The orchestrator loads credentials from `/opt/nexus/agents/.env` directly (hardcoded path in `discord_comms.py` line 34, `discord_reporter.py` line 34).

### Variables referenced in code vs. defined in .env

| Variable | Referenced In | In agents/.env | Status |
|----------|---------------|---------------|--------|
| `HUGGINGFACE_API_KEY` | agents/llm_client.py | YES | OK |
| `CEO_TOKEN` | agents/hierarchy_manager.py | YES | OK |
| `GUILD_ID` | agents/hierarchy_manager.py | YES | OK |
| `CAF_DISCORD_TOKEN` | automation/discord_comms.py, discord_reporter.py | YES | OK |
| `CAF_CHANNEL_ID` | automation/discord_reporter.py | YES | OK (but discord_comms.py ignores it — uses hardcoded int) |
| `TASK_TIMEOUT_MINUTES` | automation/dev_orchestrator.py | NO | Missing from .env — defaults to 30 min |
| `NEXUS_WALLET` | networking/mesh_discovery.py, core/service_framework.py | NO | Has default: deployer address `0x817B...`. Not a secret but should be in .env |
| `TOKENIZERS_PARALLELISM` | automation/indexer.py | NO | Set programmatically via `os.environ.setdefault` |
| `TRANSFORMERS_VERBOSITY` | automation/indexer.py | NO | Set programmatically |

### Hardcoded credentials / sensitive values

| File | Line | Finding | Severity |
|------|------|---------|----------|
| `automation/discord_comms.py` | 36 | `CHANNEL_ID: int = 1446026349528616990` — Discord channel ID hardcoded. Not a secret but should be in .env via `CAF_CHANNEL_ID`. | Low |
| `automation/subagent_client.py` | 23 | `SUBAGENT_URL = "http://10.0.20.3:11434"` — Endpoint hardcoded. Should be configurable. | Low |
| `automation/llm_router.py` | 38-40 | LLM tier endpoints hardcoded (ThinkPad:1234, nexus-ai2:11434, nexus-master:11434). Not secrets but drift risk. | Low |
| `networking/mesh_discovery.py` | 42 | `WALLET = os.environ.get('NEXUS_WALLET', '0x817B0842B208B76A7665948F8D1A0592F9b1e958')` — Deployer address as default. Public key, not secret. | Informational |
| `agents/llm_client.py` | 19 | `LOCAL_INFERENCE_URL = "http://192.168.8.128:8090/..."` — **Stale pre-migration IP hardcoded.** This is a bug, not a credential issue. | **High (bug)** |

No plaintext private keys, passwords, or API key values found hardcoded in any Python file.

---

## Section 7: Entry Point Catalog

### Active production services

| File | What it does | How invoked | Key Dependencies |
|------|-------------|-------------|-----------------|
| `automation/dev_orchestrator.py` | Central autonomous orchestrator: reads intent_registry.yaml, plans tasks with LLM, executes shell commands, monitors cluster health, communicates via Discord. The "brain" of NEXUS OS. | `nexus-orchestrator.service` (`/usr/bin/python3`) — enabled, runs as mhuraibi | planning_engine, llm_router, context_builder, feedback_loop, health_monitor, discord_comms, execution_engine, chromadb (external) |
| `automation/indexer.py` | Full codebase scanner: walks /opt/nexus, extracts AST metadata, stores in SQLite world-model DB + ChromaDB. Nightly via systemd timer. | `nexus-reindex.service` (timer: 03:00 daily) as mhuraibi | chromadb (external), world-model SQLite |
| `automation/build_world_model.py` | Builds the SQLite world-model from codebase scan (runs after indexer via `ExecStartPost`). | `nexus-reindex.service` (ExecStartPost) | SQLite at /mnt/nexus-nas/ |

### Agent bots (run from agents/ directory)

| File | What it does | How invoked | Key Dependencies |
|------|-------------|-------------|-----------------|
| `agents/hierarchy_manager.py` | Spawns all 25+ Discord bots concurrently. Each bot connects to Discord and responds using LangGraph workflows + LLM. | Manual: `cd /opt/nexus/agents && python3 hierarchy_manager.py` (no systemd service found) | agent_registry, agent_workflow, llm_client, blockchain_logger, discord (system Python) |
| `agents/ceo_bot.py` | CEO-tier Discord bot with command routing. | Manual (standalone test bot) | agent_workflow, blockchain_logger, llm_client |

### Utility / one-shot scripts

| File | What it does | How invoked | Key Dependencies |
|------|-------------|-------------|-----------------|
| `agents/invite_bots.py` | Generates OAuth2 invite URLs for all bots | Manual | agent_registry, dotenv |
| `agents/verify_system.py` | System health check for agent subsystem | Manual | agent_registry, blockchain_logger |
| `automation/chroma_memory.py` | Creates ChromaDB collections (main block) | Manual (setup) | chromadb |
| `automation/create_collections.py` | One-shot ChromaDB collection creator | Manual (setup) | chromadb |
| `libnexus/nexus_storage.py` | CLI IPFS storage test (main block) | Manual with .venv | web3, requests |
| `networking/mesh_discovery.py` | Runs BATMAN-adv mesh discovery + chain registration | Manual (requires .venv for web3) | libnexus, web3 |
| `networking/rf_mesh_daemon.py` | RF mesh packet routing daemon | Manual | rf_relay, flipper_bridge, libnexus |
| `networking/flipper_bridge.py` | Flipper Zero serial bridge test | Manual | rf_relay, serial |
| `networking/degradation_manager.py` | Network degradation monitor | Manual | libnexus (lazy) |
| `scripts/verify-fast-blocks.py` | Block performance benchmark across all validators | Manual with .venv | web3, agents/ on sys.path |
| `automation/test_guardrails.py` | pytest test runner for guardrails | Manual (pytest) | guardrails, execution_engine |

### Test files (pytest)

`agents/test_blockchain_logger.py`, `agents/test_delegation.py`, `agents/test_integration.py`, `agents/test_workflow.py`, `libnexus/test_storage.py`, `automation/test_context_builder.py`, `automation/test_guardrails.py`, `services/backups/tests/*`, `services/firewall/tests/*`, `services/networks/tests/*`, `services/storage/tests/*`

All agent tests require `.venv` for `langgraph` and `web3`. All services tests require `plinth`/`django` — inoperable.

---

## Section 8: Agent-Generated Code Assessment

### automation/ directory

The automation/ directory contains 29 Python files created between **2026-03-02 and 2026-03-05** (3-day window), strongly indicating rapid agent-assisted code generation in multiple sessions.

#### Files flagged as agent-generated stubs or problematic

**`automation/seed_knowledge.py`** — DANGEROUS AS-IS
- No `if __name__ == "__main__"` guard.
- Contains top-level executable code that runs on import.
- Imports `chroma_memory` at module level; if `chromadb.service` is not running, importing this file will cause `requests.exceptions.ConnectionError` and crash any module that imports it.
- It is not imported by anything currently, but if accidentally imported, it would silently execute ChromaDB writes.
- Recommendation: Add `if __name__ == "__main__":` guard immediately.

**`automation/hid_controller.py`** — INCOMPLETE STUB
- Implements HID keyboard/mouse control via USB serial to Pi Pico.
- Not imported by any module. Not referenced in any service. Not wired into `dev_orchestrator.py`.
- The `intent_registry.yaml` shows `ns-002` (HID controller) as a task that was generated, but the integration into the orchestrator was apparently never completed.
- The module imports `serial` which IS available in system Python, so it would load. But it has no callers.
- Recommendation: Either wire into dev_orchestrator.py or mark as incomplete in intent_registry.yaml.

**`automation/subagent_client.py`** — ENDPOINT MISMATCH
- Points to `http://10.0.20.3:11434` (Ollama API format) as a "second compute tier."
- `llm_router.py` (likely written in the same session) defines Tier 3 as the same URL but using OpenAI-compatible `/v1/chat/completions` path.
- `subagent_client.py` uses Ollama's native `/api/generate` endpoint format (different API schema).
- These two files represent duplicate LLM routing logic with inconsistent API formats.
- Recommendation: Consolidate subagent_client.py into llm_router.py or replace it entirely with `route_llm_call(tier=3)`.

**`automation/create_collections.py`** — ORPHANED SETUP SCRIPT
- One-shot ChromaDB collection creator. Should have been run once during initial setup.
- Has `__main__` block but is never imported and presumably already executed.
- Safe to leave as-is but adds confusion.

**`automation/execution_engine.py` vs `automation/dev_orchestrator.py`** — DUPLICATE LOGIC
- `execution_engine.py` was added (2026-03-03) after `dev_orchestrator.py` was created (initial).
- `dev_orchestrator.py` has its own `backup_file()`, `is_protected()`, `run_cmd()` functions that overlap with execution_engine.py.
- The relationship is: dev_orchestrator calls execution_engine via lazy import for plan execution, but keeps its own versions of helper functions. This creates a maintenance risk — two independent implementations of safety-critical functions (`backup_file`, `is_protected`).

**`automation/test_guardrails.py`** — UNUSUAL TEST STRUCTURE
- Has `if __name__ == "__main__"` that runs `pytest.main([__file__, "-v"])`.
- Also imports `from execution_engine import validate_plan` — this import is conditional in the file but will fail if execution_engine's guardrails import fails.
- The file has `import sys` and some conditional logic but no pytest fixtures at module level, making it runnable as a script.

#### Files that appear complete and correctly integrated

- `dev_orchestrator.py` — well-structured, proper async event loop, signal handling, comprehensive logging
- `planning_engine.py` — clean YAML parser with proper error handling
- `llm_router.py` — proper tier fallback with caching
- `guardrails.py` — comprehensive allowlist, appears carefully crafted
- `discord_comms.py` — proper thread-safe Discord integration
- `context_builder.py` — well-integrated with ChromaDB and world model
- `feedback_loop.py` — proper SQLite persistence with lessons/ledger
- `health_monitor.py` — comprehensive SSH-based cluster health checks
- `audit_logger.py` — minimal, correct

#### Dangerous patterns in automation/

1. **`dev_orchestrator.py` runs as root-equivalent (mhuraibi) with full shell access** via `command_executor.py` and `execution_engine.py`. The guardrails allowlist (`guardrails.py`) is the only safety mechanism between the LLM and the system. If the LLM generates a plan containing a command not on the allowlist, it is blocked — but the allowlist integrity must be verified regularly.

2. **`execution_engine.py` can write files** — the `backup_file` function in execution_engine performs file copies as part of plan execution. If the LLM hallucinates a file path inside a protected directory that passes the glob check, it could overwrite protected files. The `is_protected` check in dev_orchestrator and the separate one in build_world_model use different logic and different protected file lists.

3. **`discord_comms.py` `handle_discord_message` accepts commands from any Discord user in `CHANNEL_ID`** (line 329+). There is no visible authentication beyond Discord channel membership. Any user with access to the CAF channel can potentially trigger orchestrator actions.

#### Unmerged or isolated modules (likely from parallel agent sessions)

The following files show signs of being created in isolation without being integrated into the main orchestrator flow:

- `automation/hid_controller.py` — standalone, no callers
- `automation/seed_knowledge.py` — one-shot script masquerading as a module
- `networking/flipper_bridge.py` — complete implementation but `rf_mesh_daemon.py` imports it while `degradation_manager.py` does not; integration path unclear
- `networking/degradation_manager.py` — complete but has no service entry; would need a systemd service to run continuously

---

## Appendix: Python Environment Summary

| Package | System Python 3.13 | .venv |
|---------|-------------------|-------|
| discord.py | YES (2.7.0) | YES (2.6.4) |
| chromadb | YES (1.5.2) | NO |
| aiohttp | YES (3.13.3) | YES (3.13.3) |
| requests | YES (2.32.3) | YES (2.32.5) |
| python-dotenv | YES (1.0.1) | YES (1.2.1) |
| PyYAML | YES (6.0.2) | YES (6.0.3) |
| psutil | YES (7.0.0) | YES (7.2.2) |
| pyserial | YES (3.5) | NO |
| langgraph | **NO** | YES (1.0.8) |
| web3 | **NO** | YES (7.14.1) |
| augeas | **NO** | **NO** |
| plinth | **NO** | **NO** |
| django | **NO** | **NO** |

**Key finding:** The `nexus-orchestrator.service` uses `/usr/bin/python3` (system Python). The orchestrator itself (`dev_orchestrator.py`) only requires packages available in system Python (discord, chromadb, requests, yaml, dotenv) and is functional. However, any code path that reaches `agents/agent_workflow.py` (which needs langgraph) or `libnexus/kernel.py` (which needs web3) will fail at runtime. The agent bots (`hierarchy_manager.py`) must be run with the `.venv` or a Python environment that has langgraph + web3.
