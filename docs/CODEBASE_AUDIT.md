# NEXUS OS Codebase Audit

*Conducted: 2026-03-17 | Auditor: Claude Code (nexus-admin)*

---

## 1. Repository State

```
Branch:  main  (30 commits ahead of origin/main — unpushed)
Dirty:   agents/agent_workflow.py, agents/hierarchy_manager.py (Prompt 2 changes, unstaged)
         ipfs/datastore/* (runtime churn — expected)
Untracked: agents/llm_router_v2.py, docs/LLM_HIERARCHY.md, scripts/verify-llm-endpoints.sh
```

### Stale Branches (25 `auto/*`, 2 `agent/v2`)

The autonomous `nexus_agent_v2.py` pipeline creates branches for every task attempt:

| Prefix | Count | Origin |
|--------|-------|--------|
| `auto/np-*` | ~12 | nexus_agent_v2 task branches (NP = new project?) |
| `auto/ns-*` | ~10 | nexus_agent_v2 task branches (NS = nexus state?) |
| `auto/rm-*` | ~3  | nexus_agent_v2 task branches (RM = refactor/modify?) |
| `agent/v2/*` | 2  | Manual agent-v2 dev branches |

**Recommendation**: Delete all merged `auto/*` branches. They are completed (or abandoned)
task branches from the autonomous pipeline and clutter `git branch -a`. Use:
```bash
git branch | grep auto/ | xargs git branch -d
```
(use `-D` for unmerged ones after verifying they're safe to discard)

---

## 2. Python Files — Full Inventory

### `/opt/nexus/agents/` — Discord Agent System (Active)

| File | Status | Purpose |
|------|--------|---------|
| `agent_registry.py` | ✅ Updated | 30-agent config database; `legacy_model` + `tier` fields added |
| `agent_workflow.py` | ✅ Updated | LangGraph 3/4-node reasoning pipeline; now uses `LLMRouter` |
| `hierarchy_manager.py` | ✅ Updated | Launches 30 Discord bots; removed `llm_client` dependency |
| `llm_router_v2.py` | ✅ New | 3-tier LLM router for local LM Studio endpoints |
| `blockchain_logger.py` | ✅ Active | Logs decisions to ReasoningLedger; has pending-queue and retry logic |
| `llm_client.py` | ⚠️ Legacy | HuggingFace-based LLM client; **kept as fallback**, not in active path |
| `ceo_bot.py` | ⚠️ Stale | PoC single-bot predecessor to hierarchy_manager; still imports `llm_client` |
| `invite_bots.py` | ℹ️ Utility | One-time script to generate Discord invite URLs for all 30 bot tokens |
| `verify_system.py` | ℹ️ Utility | Pre-flight check: env vars, registry, blockchain connectivity |
| `test_workflow.py` | ⚠️ Stale | Tests `NexusAgentWorkflow` but tears down via `w.llm_client.close()` — broken |
| `test_integration.py` | ⚠️ Stale | Integration tests; 4 references to `w.llm_client.close()` — broken after Prompt 2 |
| `test_delegation.py` | ⚠️ Stale | Delegation chain tests; 3 references to `w.llm_client.close()` — broken |
| `test_blockchain_logger.py` | ⚠️ Stale | Blockchain logger tests; 1 reference to `w.llm_client.close()` — broken |
| `test_llm_client.py` | ⚠️ Stale | Tests for old `llm_client.py`; expects old HuggingFace model names |

### `/opt/nexus/automation/` — Autonomous Dev Agent v2 Pipeline (Separate System)

This is the **agent v2 pipeline** — an autonomous 24/7 coding agent distinct from the Discord
agent hierarchy. It operates via an 8-gate pipeline (G1–G8) with guardrails, rollback, and
ChromaDB memory.

| File | Purpose |
|------|---------|
| `nexus_agent_v2.py` | Entry point; 8-gate pipeline (PROBE→SCOPE→PLAN→SPEC→EXECUTE→VERIFY→COMMIT→REFLECT) |
| `dev_orchestrator.py` | Unified async event loop; git tracking; autonomous intent execution (v4.0, predates v2) |
| `llm_router.py` | **Automation's own LLM router** — role-based routing, separate from `agents/llm_router_v2.py` |
| `guardrails.py` | Single source of truth for safety policies (CAF = Contextual Autonomy Framework) |
| `planning_engine.py` | Deterministic task selection from intent registry |
| `execution_engine.py` | Safe, audited execution of structured task plans |
| `failure_analyzer.py` | Diagnoses failed pipeline steps; produces revised execution plans |
| `feedback_loop.py` | Closes the learn loop; updates world model and ChromaDB from task outcomes |
| `intent_parser.py` | Converts Discord messages into structured command objects |
| `context_builder.py` | 3-tier memory system (ChromaDB + SQLite + in-context) |
| `chroma_memory.py` | ChromaDB knowledge graph interface |
| `health_monitor.py` | Cluster-wide health checks; stores results in world_model.db |
| `git_monitor.py` | Watches git state; detects dirty working tree and branch anomalies |
| `task_planner.py` | Generates multi-step task plans from intents |
| `audit_logger.py` | Structured audit logging for all pipeline actions |
| `command_executor.py` | Sandboxed shell command execution |
| `system_queries.py` | Structured queries against cluster state |
| `discord_comms.py` | Discord send/receive for automation pipeline |
| `discord_reporter.py` | Formatted Discord embeds for pipeline status |
| `subagent_client.py` | HTTP client to delegate tasks to subagents |
| `web_research.py` | Web search/scrape for context gathering |
| `build_world_model.py` | Bootstraps the world model database |
| `create_collections.py` | Initializes ChromaDB collections |
| `seed_knowledge.py` | Seeds ChromaDB with initial codebase knowledge |
| `persona.py` | Agent personality/role definitions for automation pipeline |
| `utils.py` | Shared utilities (`_strip_json`, etc.) extracted by agent v2 |
| `proactive_tasks.py` | Schedules proactive maintenance tasks |
| `indexer.py` | Code indexer for ChromaDB ingestion |

**Configuration files:**
- `intent_registry.yaml` — Registered intents and their action templates
- `task_queue.yaml` — Runtime task queue (gitignored)
- `constitution.json` — Agent constitution / ethical constraints
- `project_state.json` — Persistent project state across runs
- `change_ledger.md` — Human-readable log of all autonomous changes

### `/opt/nexus/contracts/` — Blockchain Deployment

| File | Purpose |
|------|---------|
| `scripts/deploy.py` | Deploys all core contracts (ReasoningLedger, TokenManager, etc.) |
| `scripts/deploy_service_registry.py` | Deploys ServiceRegistry |
| `scripts/deploy_storage_registry.py` | Deploys StorageRegistry |
| `scripts/deploy_pid_registry.py` | Deploys PidRegistry |
| `scripts/test_storage_registry.py` | Integration test for StorageRegistry |
| `benchmark_fast.py` | Benchmarks PoA block confirmation latency |

### `/opt/nexus/core/` — Service Framework

| File | Purpose |
|------|---------|
| `service_framework.py` | `NexusService` base class; SQLite config DB at services.db |
| `action_utils.py` | Helpers for privileged actions via sudo |

### `/opt/nexus/libnexus/` — Storage Library

| File | Purpose |
|------|---------|
| `nexus_storage.py` | IPFS upload/download/list/verify via HTTP API |
| `contracts.py` | Web3 bindings for deployed contracts |
| `kernel.py` | Blockchain-as-kernel abstraction layer |
| `test_storage.py` | Integration tests for IPFS storage |

### `/opt/nexus/networking/` — Mesh Networking

| File | Purpose |
|------|---------|
| `mesh_discovery.py` | BATMAN-adv node discovery |
| `degradation_manager.py` | Network degradation detection and recovery |
| `rf_mesh_daemon.py` | RF mesh radio daemon |
| `rf_relay.py` | RF relay controller |
| `flipper_bridge.py` | Flipper Zero RF bridge |

### `/opt/nexus/scripts/` — Operational Scripts

| File | Purpose |
|------|---------|
| `verify-llm-endpoints.sh` | ✅ New — health check all 4 LLM tiers |
| `deploy-k3s-safe.sh` | K3s deployment with safety checks |
| `setup-ipfs-private.sh` | Private IPFS cluster setup |
| `install-ipfs-cluster.sh` | IPFS cluster binary install |
| `validate-phase1.sh` | Phase 1 blockchain validation |
| `verify-fast-blocks.py` | Verifies PoA block production rate |
| `phase2_validation.py` | Phase 2 K3s + IPFS validation |
| `register_nodes.py` | Registers cluster nodes on-chain |
| `test-ipfs-distribution.sh` | IPFS content distribution test |

---

## 3. Issues Found

### 3A. Broken Test Suite (Post Prompt 2 Migration)

**Impact: Medium** — Tests will fail when run; does not affect production agents.

`agent_workflow.py` now uses `self.router` (LLMRouter) instead of `self.llm_client`.
Four test files still reference `w.llm_client.close()` which no longer exists:

| File | Line(s) | Issue |
|------|---------|-------|
| `test_integration.py` | 16, 65, 85, 228 | `w.llm_client.close()` — attribute gone |
| `test_delegation.py` | 26, 45, 63 | `w.llm_client.close()` — attribute gone |
| `test_blockchain_logger.py` | 105 | `w.llm_client.close()` — attribute gone |
| `test_workflow.py` | (implicit) | May patch `llm_client` internals |

**Fix**: Replace `w.llm_client.close()` with `pass` (LLMRouter is stateless, no close needed).
Also update any mocking of `llm_client.chat_completion` to mock `llm_router_v2.LLMRouter.generate`.

### 3B. `ceo_bot.py` — Superseded PoC Still Imports `llm_client`

**Impact: Low** — `ceo_bot.py` is the predecessor to `hierarchy_manager.py` and is no longer
the active entry point. It still imports `get_llm_client` (line 19) and hardcodes
`"Qwen/Qwen2.5-7B-Instruct"` in a Discord embed (line 123).

**Fix**: Either update to use `LLMRouter` for consistency, or mark it explicitly as a
`DEPRECATED - use hierarchy_manager.py` file. Do not delete — it serves as reference for
the single-bot pattern.

### 3C. Agent v2 Backup Files

Three `.agent_v2_backup.*` files left by the autonomous pipeline:

| File | Gap | Size | Date |
|------|-----|------|------|
| `automation/feedback_loop.py.agent_v2_backup.gap-G019-strip-json-dedup` | G019 | 17K | 2026-03-09 |
| `automation/seed_knowledge.py.agent_v2_backup.gap-G021-seed-knowledge-guard` | G021 | 2.0K | 2026-03-09 |
| `NEXUS_OS_Current_State.md.agent_v2_backup.gap-G033-libnexus-docs` | G033 | 19K | 2026-02-15 |

These are pre-modification snapshots from autonomous pipeline gap-filling. They are safe to
delete once the corresponding changes have been verified. The `.gitignore` already excludes
`*.agent_v2_backup.*` so they are not tracked.

### 3D. Dual LLM Routers (Potential Confusion)

Two separate LLM routers exist in the codebase:

| File | Used By | Endpoints |
|------|---------|-----------|
| `agents/llm_router_v2.py` | Discord agent hierarchy (active) | Local LM Studio |
| `automation/llm_router.py` | Autonomous dev pipeline (active) | Different routing logic |

These are intentionally separate systems. However, the naming could cause confusion.
**No action needed** but document this distinction clearly.

### 3E. Stale HuggingFace References in Active Files

| File | Line | Reference | Action Needed |
|------|------|-----------|---------------|
| `ceo_bot.py` | 123 | `"Qwen/Qwen2.5-7B-Instruct"` hardcoded in embed | Update if ceo_bot is maintained |
| `test_llm_client.py` | 30,47,62 | Asserts on old HF model names | Only affects `llm_client.py` tests — acceptable |
| `llm_client.py` | throughout | Entire HuggingFace API implementation | Kept as fallback; no change needed |

### 3F. `_CLUSTER_CONTEXT` Stale Data in `agent_registry.py`

Line 7–14: the shared cluster context string still says `"5s blocks"` but the chain uses
`period=0` (blocks on demand, ~28ms confirmation). Minor inaccuracy in agent prompts.

---

## 4. No Conflicts Found

The autonomous agent v2 pipeline **did not modify** any of the files changed in Prompt 2:
- `agent_workflow.py` — only modified by `find ... -newer llm_router_v2.py` (our change)
- `hierarchy_manager.py` — same
- `agent_registry.py` — not in the recent-files list before our audit

The `auto/*` git branches are all separate from `main` and contain no uncommitted changes
that would conflict.

---

## 5. Recommended Cleanup Actions (Priority Order)

| Priority | Action | Risk |
|----------|--------|------|
| **P1** | Fix test teardown: replace `w.llm_client.close()` → `pass` in 4 test files | Low |
| **P1** | Commit our 3 file changes (workflow, manager, registry) to git | Low |
| **P2** | Add untracked files to git: `llm_router_v2.py`, `docs/LLM_HIERARCHY.md`, `scripts/verify-llm-endpoints.sh`, `docs/CODEBASE_AUDIT.md` | Low |
| **P2** | Delete stale `auto/*` branches (25 branches): `git branch \| grep auto/ \| xargs git branch -D` | Low (already merged or abandoned) |
| **P3** | Update `ceo_bot.py` — add deprecation notice or migrate to `LLMRouter` | Low |
| **P3** | Delete 3 `.agent_v2_backup.*` files after verifying G019/G021/G033 changes are stable | Low |
| **P4** | Fix `_CLUSTER_CONTEXT` "5s blocks" → "period=0 (on-demand)" in `agent_registry.py` | Low |
| **P4** | Push `main` to origin (30 commits ahead) | Medium — coordinate with team |

---

## 6. Summary

| Category | Count | Status |
|----------|-------|--------|
| Active agent system files | 6 | ✅ Healthy post-Prompt-2 changes |
| Test files needing update | 4 | ⚠️ Will fail on teardown |
| Superseded PoC files | 1 (`ceo_bot.py`) | ⚠️ Stale imports |
| Agent v2 backup files | 3 | ℹ️ Safe to delete after verification |
| Stale git branches | 25 | ℹ️ Safe to delete |
| Dual LLM routers (intentional) | 2 | ℹ️ Document, no action |

*No files were deleted. No production code was broken.*
