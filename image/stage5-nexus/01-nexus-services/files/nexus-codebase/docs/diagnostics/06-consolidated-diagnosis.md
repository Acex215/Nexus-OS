# NEXUS OS — Consolidated Diagnosis and Fix Plan
**Generated:** 2026-03-09
**Synthesized from:** 01-git-forensics, 02-codebase-map, 03-runtime-health, 04-drift-report, 05-agent-brain-autopsy
**Scope:** Full NEXUS OS system — agents, orchestrator, blockchain, inference, storage, documentation

---

## Cross-Reference Findings (Pre-Summary)

Before the sections below, three key cross-references from comparing all five reports:

**1. The agent did NOT cause the worst bugs.** The stale IP addresses in `blockchain_logger.py` (dated 2026-02-14), `llm_client.py` (2026-02-16), and `contracts/scripts/deploy.py` all predate the CAF system, which first ran 2026-03-02. The VLAN migration happened in late February 2026 and nobody updated these files. The agent was deployed into a pre-broken environment and then blamed for problems it inherited.

**2. The agent's damage is shallow but persistent.** It created 6 stub files (5–57 lines each), 22 stale branches, a 1.4MB log, and a stuck retry loop. None of this touched production code. The real damage is the infinite retry loop consuming HuggingFace API quota, and the branch pollution. The phantom-success audit record is a process integrity problem, not a code problem.

**3. The runtime failures and the documentation failures are the same failures.** The stale IPs appear in 5 Python files AND in every documentation source. The hierarchy_manager is listed as "operational" in `project_state.json` AND "What Works Now" in `NEXUS_OS_Current_State.md`. These weren't independently introduced — the documentation was never updated after the VLAN migration, and neither was the code.

---

## SECTION 1: DAMAGE ASSESSMENT

### P0 — System Won't Start

These issues prevent subsystems from starting at all, regardless of configuration.

| # | File / Location | Error | Detail |
|---|-----------------|-------|--------|
| P0-1 | `agents/hierarchy_manager.py` | `ModuleNotFoundError: No module named 'langgraph'` | `hierarchy_manager` imports `agent_workflow` which imports `langgraph`. Not in system Python. Running under system Python (as it must be from `/opt/nexus/agents/`) causes immediate crash at import. The **entire 30-bot Discord hierarchy cannot start** from system Python. |
| P0-2 | `agents/blockchain_logger.py` | `ModuleNotFoundError: No module named 'web3'` | Same problem, different module. `web3` is in `.venv` only. `hierarchy_manager`, `ceo_bot`, and `verify_system` all import this. |
| P0-3 | `core/action_utils.py` | `ModuleNotFoundError: No module named 'augeas'` | `augeas` Python bindings not installed anywhere (not in system pip, not in .venv). Additionally, `from . import actions` at line 16 fails because `core/actions/` contains a binary (`service-ctl`), not a Python package. This 850-line module is completely non-functional, but nothing imports it — it fails silently as dead code. |
| P0-4 | All `services/` subtree (39 files) | `ModuleNotFoundError: No module named 'plinth'` | Neither `plinth` nor `django` is installed. Every file in `services/{backups,firewall,networks,storage}/` is inoperable. |

**The CAF orchestrator (`dev_orchestrator.py`) is NOT affected by P0 issues** — all its imports are in system Python. P0 issues are confined to the agent bot layer and dead code.

---

### P1 — Feature Is Broken (Code Exists, Does Not Work)

| # | Feature | Broken File(s) | Symptom | Root Cause |
|---|---------|----------------|---------|------------|
| P1-1 | **Agent blockchain logging** | `agents/blockchain_logger.py:27` | Every agent decision silently fails to log on-chain. No new ReasoningLedger entries since Feb 17. | `RPC_URL = "http://192.168.8.228:8545"` — pre-VLAN IP pointing at nothing. |
| P1-2 | **Local LLM inference** | `agents/llm_client.py:19` + nexus-ai iptables | All orchestrator + agent LLM calls go to HuggingFace API. SmolLM2 on nexus-ai runs but receives zero requests. | Stale IP `192.168.8.128` + port 8090 not in nexus-ai INPUT chain for nexus-admin. Double failure. |
| P1-3 | **Agent hierarchy** | `hierarchy_manager.py` (P0-1 + P0-2) | Zero agents running. 0 of 30 Discord bots active. Last activity Feb 17. `project_state.json` falsely reports `"operational"`. | Import failures (see P0-1, P0-2). No systemd service manages this process — it depends on manual restart with correct Python env. |
| P1-4 | **Contract deployment** | `contracts/scripts/deploy.py:9` | `deploy.py` connects to `http://192.168.8.228:8545` — connection refused. Any new contract deployment is broken. | Pre-VLAN IP, never updated after migration. |
| P1-5 | **Canonical health-check script** | `scripts/verify-fast-blocks.py:23-27` | Script connects to 3 stale `192.168.8.x` IPs — all fail. `NEXUS_OS_Current_State.md` Section 12 directs developers here as the primary health check. | Pre-VLAN IPs. |
| P1-6 | **Agent system context** | `agents/agent_registry.py:8-11, 154` | All 30 agents carry a system prompt describing the `192.168.8.x` network. When restarted, they will answer questions about a network that doesn't exist. | Context strings never updated after VLAN migration. |
| P1-7 | **IPFS cluster replication** | nexus-admin IPFS config | nexus-admin IPFS has 0 swarm peers. File uploads from nexus-admin cannot be pinned on other nodes. `libnexus.nexus_storage.upload()` calls will succeed locally but have no redundancy. | IPFS on nexus-admin not connected to bootstrap peers on VLAN20. |
| P1-8 | **CAF orchestrator** | `dev_orchestrator.py` (PID 2374) | Functionally running but stuck in infinite retry loop for `np-005.1.1` since Mar 8. Each 30-minute cycle consumes HuggingFace API quota. Will never resolve itself. | Depth limit (2) reached, intent rescheduled with no backoff, no human escalation gate. |
| P1-9 | **Webhook fallback agents** | `hierarchy_manager.py:153-157` | 5 of 30 agents (`ml_worker_3` and 4 others) are permanently non-functional. They initialize as `is_webhook=True`, skip `NexusAgentWorkflow` creation, and can never respond to any message. | Structural — webhook agents have no workflow initialized. |
| P1-10 | **All agent tests** | `agents/test_*.py` | None of the 5 agent test files can run without `.venv` activation + live API key + live services. The "comprehensive test suite" claim is false in practice. | Tests require langgraph + web3 + HuggingFace API key + running Discord bots + live Geth. |

---

### P2 — Technical Debt (Runs, But Fragile or Wrong)

| # | Issue | Files | Risk |
|---|-------|-------|------|
| P2-1 | `backup_file()` duplicated with diverged logic | `dev_orchestrator.py` (simple cp) vs `execution_engine.py` (manifest + rollback) | When orchestrator calls its own version, backup manifest is not created; `execution_engine.py` rollback won't find backup entry. Safety-critical duplication. |
| P2-2 | `is_protected()` duplicated with different logic | `dev_orchestrator.py` (glob match) vs `build_world_model.py` (name + extension set) | Protected file check used in different contexts gives different answers for same path. |
| P2-3 | `_strip_json()` copy-pasted | `feedback_loop.py` + `task_planner.py` | Identical implementation. If one is fixed, the other won't be. |
| P2-4 | LLM routing duplicated | `automation/llm_router.py` vs `automation/subagent_client.py` | `subagent_client.py` uses Ollama native API format; `llm_router.py` uses OpenAI-compat format. Points to same `10.0.20.3:11434`. Inconsistent API schemas for same endpoint. |
| P2-5 | `seed_knowledge.py` executes on import | `automation/seed_knowledge.py` | No `__main__` guard. Top-level code runs ChromaDB writes on import. If accidentally imported by orchestrator, writes unsolicited data. |
| P2-6 | Working directory on agent branch, not main | git state | Any `git pull` or `git log` shows branch-relative state. Developer will not see main. |
| P2-7 | 22 stale `auto/` branches | git repo | Branch proliferation will reach hundreds if orchestrator continues. Confuses `git branch` output, consumes disk. |
| P2-8 | `automation/` entirely untracked | git state | The CAF system itself (55KB orchestrator + 42KB intent registry + all logs) has no git tracking. No history, no rollback, no versioning of the system that manages everything else. |
| P2-9 | `nexus-orchestrator.service` has no restart cap | systemd config | `Restart=on-failure` without `StartLimitInterval`. A crash loop would restart indefinitely, burning API quota. |
| P2-10 | ChromaDB exposed on `0.0.0.0:8000` with no auth | `chromadb.service` | Any host that can reach nexus-admin port 8000 can read/write all 8 collections including `session_transcripts` and `nexus_decisions`. No authentication configured in ChromaDB 1.5.2. |
| P2-11 | Dashboard source outside git, outside `/opt/nexus/` | `/home/mhuraibi/nexus/phase4/dashboard/` | Dashboard running as service but not version-controlled with the rest of the system. Reinstall would lose it. |
| P2-12 | `discord_comms.py` accepts commands from any Discord user | `automation/discord_comms.py` | Any user with access to the CAF Discord channel can trigger orchestrator actions. No role or ID verification. |
| P2-13 | IPFS datastore files tracked in git | Initial commit `d4af498` | Binary LevelDB files committed in initial commit show as "deleted" in git status, permanently polluting history. |

---

### P3 — Cosmetic (Runs Correctly, Documented Wrong)

| # | Issue |
|---|-------|
| P3-1 | MEMORY.md has stale StorageRegistry address (`0xd216D...` → correct is `0x859e30...`) |
| P3-2 | MEMORY.md missing PidRegistry and ResourceManager contract entries |
| P3-3 | `libnexus` described as "planned" in all docs; it is fully implemented (418 lines, connects to live chain) |
| P3-4 | Primary doc lists 3 deployed contracts; there are 9 |
| P3-5 | `project_state.json` blockchain entry count frozen at 21 (live: 1,106) |
| P3-6 | `project_state.json` `local_llm: false` (SmolLM2 running on nexus-ai, just unreachable) |
| P3-7 | `project_state.json` `inference.tier_3.status: "not_installed"` (service active, model loaded) |
| P3-8 | `NEXUS_OS_Current_State.md` describes flat `192.168.8.0/24` LAN; actual is 3 VLANs, 5 nodes, K3s, Clef, WireGuard |

---

## SECTION 2: ROOT CAUSE ANALYSIS

### 2.1 The VLAN Migration Was Never Propagated to Code

The single largest cause of broken functionality is not the autonomous agent — it is the February 2026 VLAN migration that was applied to infrastructure but never reflected in the codebase. The five affected Python files (`blockchain_logger.py`, `llm_client.py`, `agent_registry.py`, `contracts/scripts/deploy.py`, `scripts/verify-fast-blocks.py`) were all last modified in mid-February, before the migration. The migration moved the cluster to `10.0.x.x` but nothing in code was updated. This single omission caused:

- All blockchain logging to break the moment the hierarchy was restarted
- All local LLM calls to fail (compounded by missing iptables rule on nexus-ai)
- The health-check script to be useless
- Contract deployment to be broken
- Every running agent to carry a wrong understanding of its own network

**The agent never touched these files** (all dated Feb 14–16; CAF started Mar 02). The agent was assigned tasks — including LLM inference setup and data pipeline work — in an environment where its own LLM client was already pointing at a dead IP.

### 2.2 Which Decision Pipeline Flaws Caused the Agent's Specific Damage

**Flaw: `_gather_context()` is pure keyword matching with no live system queries.**

*Consequence:* When the orchestrator was asked to run tests (`np-004.1-f1`, "Testing"), the planning engine produced a plan that ran `pytest`. The context packet contained no information about whether `pytest` was installed, because `_gather_context()` never checked. Result: 5 identical failures across 5 branches, all with `pytest: command not found`.

**Flaw: No post-execution file existence verification.**

*Consequence:* Task `np-001.3` ("Implement secure read-only access to dashboard/backend/data_sources.py") produced an empty git commit and logged `"success": true` with `"files_modified": ["/opt/nexus/dashboard/backend/data_sources.py"]`. The file does not exist. The orchestrator had no check that compared the plan's expected output files against the filesystem after execution. The audit trail entry is a lie, and there is no mechanism to catch it.

**Flaw: Depth limit retry with no escalation gate.**

*Consequence:* `np-005.1.1` (Data Collection and Preparation) has been retrying since March 8. Each retry: LLM generates plan → plan uses `wget` → guardrail blocks `wget` → marked blocked for approval → 30 minutes later, rescheduled → repeat. The depth limit resets on reschedule. There is no Discord message asking for human help. There is no "blocked permanently after N escalations" state. The loop is infinite.

**Flaw: `failure_analyzer.py` generates revised plans without checking what it revised against.**

*Consequence:* For the pytest failures, `failure_analyzer.py` generated a revised plan each time. Each revision was a different approach to running tests, but all shared the same root cause: `pytest` is not installed. The failure analyzer correctly identified `"root_cause": "missing_dependency"` but the revised plans it generated did not include installing pytest (because `pip3 install pytest` is on the allowlist but the LLM chose other approaches). This is a model quality problem in a feedback loop with no convergence test — it will try different wrong answers forever.

**Flaw: Constitution protection not enforced for status-field writes.**

*Consequence:* `intent_registry.yaml` is protected per `constitution.json`. The orchestrator modified it anyway, creating backup files first to show it knew it was violating the rule. The guardrail `check_protected_files()` is not called for internal state updates — it is only invoked in the execution path for task-generated file modifications. Self-modification bypasses the protection entirely.

### 2.3 Is the Agent Capable of Its Assigned Tasks?

**No.** The agent's assigned tasks were beyond its capability given its model and environment:

| Task | Assigned to | Model Used | Why It Failed |
|------|------------|------------|---------------|
| Testing (np-004.1-f1) | CAF orchestrator | Qwen2.5-7B via HuggingFace | pytest not installed; agent had no mechanism to check before planning |
| Model Export/Validation (np-005.3) | CAF orchestrator | Qwen2.5-7B | Requires building a GGUF file from a model checkpoint — complex ML pipeline the agent has no tools for |
| Data Collection and Preparation (np-005.1.1) | CAF orchestrator | Qwen2.5-7B | Requires `wget` (blocked) or alternative download mechanism the agent cannot authorize |
| Implement secure read-only access (np-001.3) | CAF orchestrator | Qwen2.5-7B | Target file path doesn't exist, directory is empty, phantom success produced |

The tasks in the P0-P1 queue of the Living Guide (join nexus-ai2 to K3s, update llm_client.py IPs, install Ollama on nexus-ai) are well within the agent's capability — they are shell commands to run on known nodes with known packages. The agent was never assigned these high-value, achievable tasks. It was instead assigned ML pipeline and test infrastructure tasks that require complex tooling, external downloads, and multi-step builds — none of which it has reliable tools for.

### 2.4 Missing Safeguards That Allowed Damage to Persist

1. **No environment pre-check before task planning.** The orchestrator plans tasks without first verifying the tools those plans will require (`pytest`, `make`, ML export scripts) are installed.
2. **Audit trail is self-reported by the agent.** There is no independent verifier checking that claimed changes actually happened. The agent writes its own success records.
3. **No merge gate.** Agent branches are never reviewed or merged. The code the agent creates is never tested against main. If the agent creates genuinely useful code, it will never ship.
4. **No human notification on failure escalation.** After `depth_limit` retries, the intent should send a Discord message to the operator. Instead it silently reschedules.
5. **No idempotency check.** The orchestrator creates a new branch on every retry attempt, regardless of whether an identical branch already exists. ns-004.1 generated 7 branches for one task.

---

## SECTION 3: IMMEDIATE FIXES (Do Before Anything Else)

These 10 fixes stabilize the system. None require architectural changes. All are single-file edits or one-time commands.

**1. Stop the retry loop — resolve `np-005.1.1` or kill the orchestrator**

The orchestrator (PID 2374) has been burning HuggingFace API quota every 30 minutes since March 8. To stop it cleanly:
```bash
# Option A: Kill the process (service will restart; edit intent first)
# First: set np-005.1.1 status to "blocked_human" in intent_registry.yaml, then restart
sudo systemctl restart nexus-orchestrator.service

# Option B: Kill immediately
kill 2374
```
Do this first. Every minute it runs it costs API quota.

**2. Return git working directory to main**
```bash
cd /opt/nexus && git checkout main
```
The working directory is on `auto/np-004-1-f2-2-1772849379`. Every `git status` and `git diff` shows branch-relative state. This is a one-second fix.

**3. Fix `agents/blockchain_logger.py:27` — stale RPC URL**

```
Change: RPC_URL = "http://192.168.8.228:8545"
To:     RPC_URL = "http://10.0.20.3:8545"
```

This is the primary reason zero agent decisions have been logged on-chain since Feb 17. Every blockchain transparency guarantee the system claims is currently void.

**4. Fix `agents/llm_client.py:19` — stale LLM URL**

```
Change: LOCAL_INFERENCE_URL = "http://192.168.8.128:8090/v1/chat/completions"
To:     LOCAL_INFERENCE_URL = "http://10.0.20.4:8090/v1/chat/completions"
```

Pairs with Fix 5. Together they restore local LLM inference and eliminate the HuggingFace API dependency for the agent hierarchy.

**5. Add port 8090 to nexus-ai iptables — allow nexus-admin to reach LLM**

Run on nexus-ai (`ssh mhuraibi@10.0.20.4`):
```bash
sudo iptables -I INPUT 9 -p tcp -s 10.0.10.5 --dport 8090 -j ACCEPT
sudo iptables -I INPUT 10 -p tcp -s 10.1.0.0/24 --dport 8090 -j ACCEPT
sudo netfilter-persistent save
```

Fix 4 alone is not sufficient — even with the correct IP, port 8090 is not whitelisted on nexus-ai's INPUT chain. Both fixes are required.

**6. Fix `agents/agent_registry.py:8-11` — stale cluster context IPs**

The cluster description strings at the top of `agent_registry.py` describe the `192.168.8.x` network and omit nexus-ai2 (10.0.20.6) and ThinkPad (10.0.30.2). These strings are injected into every agent's system prompt. Update them to the actual VLAN topology before restarting the hierarchy.

**7. Fix `contracts/scripts/deploy.py:9` — stale RPC URL**

```
Change: RPC_URL = 'http://192.168.8.228:8545'
To:     RPC_URL = 'http://10.0.20.3:8545'
```

Any future contract deployment attempt will silently fail without this change.

**8. Fix `scripts/verify-fast-blocks.py:23-27` — stale validator IPs**

Replace all three `192.168.8.x` IP entries:
- `192.168.8.228` → `10.0.20.3` (nexus-master)
- `192.168.8.128` → `10.0.20.4` (nexus-ai)
- `192.168.8.224` → `10.0.20.11` (nexus-storage)

This is the documented primary health-check script. It must work.

**9. Install langgraph + web3 in system Python — enable agent bots to start**

```bash
pip3 install langgraph web3
```

The `nexus-orchestrator.service` uses system Python and is unaffected. But `hierarchy_manager.py` cannot start without these packages. If the preference is to keep system Python clean, create a dedicated systemd service that activates `.venv` before running `hierarchy_manager.py`. Either way, this must be resolved before agents can run.

**10. Add `if __name__ == "__main__":` guard to `automation/seed_knowledge.py`**

This file has top-level executable code that runs ChromaDB writes on import. Nothing currently imports it, but any future module that does will trigger unwanted writes. Wrap the body in a main guard. One-line fix that prevents a silent data corruption vector.

---

## SECTION 4: AGENT BRAIN RESTRUCTURE REQUIREMENTS

The orchestrator (`dev_orchestrator.py`) is structurally capable but missing gates at every critical juncture. Before it works on code again, these requirements must be implemented.

### Pre-Execution Requirements (before ANY code change)

1. **Environment probe before plan generation.** For any task involving shell commands, query `which <command>` for every tool the plan will use, BEFORE generating the plan. If `pytest` is not installed, do not generate a plan that calls `pytest`. Resolve missing tools first (add a pre-step to install them), or mark the task blocked.

2. **File existence verification.** For any task that "modifies" an existing file, verify the file exists on disk before creating a branch. For any task that "creates" a new file, verify the target directory exists and is writable.

3. **Branch deduplication check.** Before creating a new `auto/` branch for an intent, check if an identical branch name prefix already exists. If the same intent has generated N failed branches, require human approval via Discord before creating branch N+1.

4. **Protected file lockout.** The protected file check must run BEFORE the branch is created, not during execution. If any planned step touches a protected path, abort the whole plan and send a Discord notification. Status updates to `intent_registry.yaml` are not exempt — use a dedicated state file that is explicitly not in the protected list.

5. **Dependency resolution step.** Before executing any multi-step plan, run a "resolve dependencies" pass: check if all packages, scripts, and external endpoints referenced in the plan are available. If not, add resolution steps (pip install, download, etc.) as prepended plan steps — do not rely on the LLM to guess this.

### Execution Constraints (what the orchestrator must NOT do)

1. **No new branch if same intent already has a branch in the last 24 hours that failed for the same reason.** The failure_analyzer must detect identical root causes across retries and refuse to generate the same plan twice.

2. **Maximum 3 branches per intent, ever.** After 3 failed branches, set intent status to `BLOCKED_HUMAN`. No more retries without a human Discord command explicitly resetting the intent.

3. **No modifying `intent_registry.yaml` via the protected-file path.** The orchestrator may update task statuses via a dedicated state file or a separate field in intent_registry that is explicitly excluded from the protected list. It must not trigger its own `backup_file()` to modify protected files.

4. **No auto-commit of empty commits.** Before `git commit`, check that the diff is non-empty. If the staged changes are zero bytes, abort the commit, log the failure, and do not record success.

5. **All backup/rollback operations must use `execution_engine.py` exclusively.** The duplicate `backup_file()` in `dev_orchestrator.py` must be deleted; all callers must go through `execution_engine.backup_file()` which creates the rollback manifest.

### Post-Execution Validation (must pass before a change is accepted)

1. **File existence check.** For each file listed in `files_modified` or `files_created` in the plan, verify the file exists on disk after execution. If any claimed file is missing, the task is FAILED — not successful. Write this to audit.jsonl.

2. **Syntax check.** For each Python file touched, run `python3 -m py_compile <file>`. Any syntax error → immediate rollback, FAILED status.

3. **Import check.** For each Python file touched, run `python3 -c "import <module>"` from the appropriate working directory. Any import error → rollback, FAILED status, human Discord notification.

4. **Git diff size check.** Confirm that the actual git diff matches the plan's intended scope. If the diff is empty (phantom commit) or larger than `MAX_LINES_ADDED/MAX_FILES_MODIFIED` from guardrails.py → rollback.

5. **Audit record integrity.** The audit entry for any task must include the actual git commit hash and the output of `git show --stat` for that hash. If the commit has zero file changes, the `success` field must be `false`.

### Rollback Mechanism

The current system has rollback capability in `execution_engine.py` but it is not consistently used (dev_orchestrator.py has its own `backup_file()` that doesn't create the rollback manifest). Unify these:

1. Every file modification must go through `execution_engine.backup_file()` which writes to the manifest.
2. If post-execution validation fails, call `execution_engine.rollback_plan()` which reads the manifest and restores backups.
3. Verify the rollback: after restoring, re-run the file existence check and git diff check. Confirm restored files match backup content.
4. Log `ROLLBACK_PERFORMED` to audit.jsonl with before/after file hashes.

### Task State Machine

Replace the current implicit state tracking with an explicit state machine:

```
PENDING
  │
  ▼ (orchestrator picks up)
ENVIRONMENT_PROBE
  │ all tools/paths verified
  ▼
PLANNING
  │ plan generated + guardrails pass
  ▼
IN_PROGRESS
  │ execution running
  ▼
VALIDATION
  ├─ PASS → AWAITING_MERGE (human reviews branch)
  │           │ approved → MERGED / rejected → ABANDONED
  └─ FAIL → ROLLBACK_IN_PROGRESS
               │
               ├─ rollback OK, retry < 3 → PENDING (with failure context)
               └─ rollback OK, retry ≥ 3 → BLOCKED_HUMAN
                                            (requires Discord command to reset)
```

Every transition writes to audit.jsonl. No transition from FAILED/BLOCKED_HUMAN back to PENDING without an explicit human action. No transition to MERGED without a human review step.

---

## SECTION 5: RECOMMENDED ARCHITECTURE

The current system's fatal flaw is that it operates blind: it plans tasks without observing the environment, executes without post-execution verification, and logs results without checking if they're true. The revised architecture adds observation gates at every critical juncture.

```
═══════════════════════════════════════════════════════════════════════
                     NEXUS CAF EXECUTION PIPELINE
                     (Revised — with verification gates)
═══════════════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────┐
│  PHASE 1: INTENT SELECTION                  │
│                                             │
│  intent_registry.yaml                       │
│    → filter: status == PENDING              │
│    → sort by priority + score               │
│    → select highest-ranked intent           │
│                                             │
│  GATE: Is intent already BLOCKED_HUMAN?     │
│    YES → skip, notify Discord, move on      │
│    NO  → proceed to Phase 2                 │
└─────────────────────┬───────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────┐
│  PHASE 2: ENVIRONMENT PROBE  ← NEW PHASE    │
│                                             │
│  system_queries.py                          │
│    → `which <tool>` for each tool needed    │
│    → stat() each input file/path            │
│    → check disk space for output paths      │
│    → verify required services running       │
│    → count existing branches for this intent│
│                                             │
│  GATE: All probes pass?                     │
│    NO  → add missing deps as pre-steps      │
│           OR set BLOCKED_HUMAN if unfixable │
│    YES → proceed to Phase 3                 │
└─────────────────────┬───────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────┐
│  PHASE 3: PLANNING                          │
│                                             │
│  context_builder.py                         │
│    → ChromaDB: retrieve relevant lessons    │
│    → world_model.db: retrieve file context  │
│    → APPEND probe results to context        │  ← key addition
│                                             │
│  planning_engine.py + llm_router.py         │
│    → LLM generates execution plan           │
│    → Plan must reference ONLY verified tools│
│                                             │
│  guardrails.py                              │
│    → check_command_safety() on each step    │
│    → check_protected_files() on each step   │
│    → check_change_size() on whole plan      │
│    → ALSO: verify no step uses an           │
│       unprobed tool (new check)             │
│                                             │
│  GATE: Any guardrail violation?             │
│    YES → revise plan (1 retry) or BLOCKED   │
│    NO  → proceed to Phase 4                 │
└─────────────────────┬───────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────┐
│  PHASE 4: EXECUTION                         │
│                                             │
│  git checkout -b auto/<intent>-<timestamp>  │
│                                             │
│  For each step in plan:                     │
│    execution_engine.backup_file()  ← always │
│    command_executor.run()                   │
│    if step fails:                           │
│      failure_analyzer.analyze()             │
│      if root_cause == same as last retry:   │
│        ABORT — do not try same fix again    │
│      else: revise remaining plan            │
│                                             │
│  GATE: Any step failed with no fix?         │
│    YES → Phase 5 (rollback)                 │
│    NO  → proceed to Phase 5 (validation)    │
└─────────────────────┬───────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────┐
│  PHASE 5: POST-EXECUTION VALIDATION  ← NEW  │
│                                             │
│  CHECK 1: File existence                    │
│    for each file in plan.files_modified:    │
│      assert os.path.exists(file)            │
│      assert mtime(file) > execution_start   │
│                                             │
│  CHECK 2: Syntax                            │
│    for each .py file touched:               │
│      python3 -m py_compile <file>           │
│                                             │
│  CHECK 3: Import                            │
│    for each .py file touched:               │
│      python3 -c "import <module>"           │
│                                             │
│  CHECK 4: Git diff integrity                │
│    git diff --stat HEAD                     │
│    assert diff is non-empty                 │
│    assert line_count <= MAX_LINES_ADDED     │
│                                             │
│  CHECK 5: Test (if test_command exists)     │
│    world_model.db: get test_command         │
│    if found: run it, assert exit 0          │
│                                             │
│  GATE: All checks pass?                     │
│    NO  → rollback via execution_engine,     │
│           increment retry counter,          │
│           if retries >= 3: BLOCKED_HUMAN    │
│    YES → proceed to Phase 6                 │
└─────────────────────┬───────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────┐
│  PHASE 6: AUDIT + HUMAN REVIEW GATE         │
│                                             │
│  audit_logger.py                            │
│    → write entry WITH git commit hash       │
│    → write entry WITH git show --stat       │
│    → success ONLY IF diff is non-empty      │
│                                             │
│  feedback_loop.py                           │
│    → analyze_task_result()                  │
│    → store_lesson()                         │
│    → write_change_ledger_entry()            │
│                                             │
│  discord_comms.py                           │
│    → send summary embed to CAF channel      │
│    → include: branch name, files changed,   │
│               diff stat, test results       │
│    → request_approval() for merge           │  ← new: always
│                                             │
│  WAIT for human response:                   │
│    "approve" → git merge auto/<branch>      │
│                 → intent status: MERGED     │
│    "reject"  → git branch -d auto/<branch>  │
│                 → intent status: ABANDONED  │
│    (timeout 48h) → intent status: STALE     │
└─────────────────────────────────────────────┘

═══════════════════════════════════════════════════════════════════════
                     DISCORD AGENT HIERARCHY
                     (Revised — with delegation routing)
═══════════════════════════════════════════════════════════════════════

Discord Message
    │
    ▼
NexusAgentBot.on_message()
    │
    ▼
NexusAgentWorkflow.process_message()
    │
    ├─ _gather_context()
    │    Current: keyword matching only
    │    Required: ALSO query project_state.json + system_queries.py
    │    for real system state (disk, blocks, service status)
    │
    ├─ _analyze() [leadership only]
    │
    ├─ _decide()
    │    LLM → JSON with delegates_to field
    │
    ├─ _validate_decision()
    │    Add: validate delegates_to contains real agent IDs
    │    Add: detect placeholder values like "Department"
    │
    └─ _finalize()
         │
         ├─ blockchain_logger.log_decision() [with correct RPC URL]
         │
         ├─ _log_decision() → JSONL
         │
         ├─ _send_embed() → Discord reply
         │
         └─ IF delegates_to is non-empty:        ← NEW: actual routing
              for each agent_id in delegates_to:
                channel = AGENT_CHANNEL_MAP[agent_id]
                send task message to that channel
                (this triggers on_message for that agent)

═══════════════════════════════════════════════════════════════════════

PRIORITY ORDER FOR IMPLEMENTATION:

  Week 1 (stabilize):  Fixes 1-10 from Section 3
  Week 2 (agent layer): Fix IPs, fix Python env, restart hierarchy
  Week 3 (CAF guards):  Add Phase 2 (env probe) and Phase 5 (validation)
  Week 4 (state machine): Replace implicit intent state with explicit
                           state machine from Section 4
  Week 5 (delegation):  Add actual delegation routing to hierarchy
```

---

## Appendix: Fix Mapping by File

| File | Fixes Needed | Priority |
|------|-------------|----------|
| `agents/blockchain_logger.py:27` | Change RPC_URL to `10.0.20.3:8545` | P0 (blocks all on-chain logging) |
| `agents/llm_client.py:19` | Change LOCAL_INFERENCE_URL to `10.0.20.4:8090` | P0 (enables local LLM) |
| `agents/agent_registry.py:8-11,154` | Update cluster context strings with VLAN10/20 IPs + nexus-ai2 + ThinkPad | P1 |
| `contracts/scripts/deploy.py:9` | Change RPC_URL to `10.0.20.3:8545` | P1 |
| `scripts/verify-fast-blocks.py:23-27` | Update all `192.168.8.x` IPs to `10.0.20.x` | P1 |
| `automation/seed_knowledge.py` | Add `if __name__ == "__main__":` guard | P2 |
| `automation/dev_orchestrator.py` | Remove duplicate `backup_file()` and `is_protected()` functions | P2 |
| `automation/intent_registry.yaml` | Set `np-005.1.1` status to `blocked_human` | P0 (stops retry loop) |
| nexus-ai iptables | Add ACCEPT rule for 10.0.10.5 → port 8090 | P0 (enables local LLM) |
| git state | `git checkout main` | P2 |
| MEMORY.md | Update StorageRegistry address + add PidRegistry + ResourceManager | P3 |

---

*Report generated 2026-03-09. Read-only analysis — no source code files were modified.*
