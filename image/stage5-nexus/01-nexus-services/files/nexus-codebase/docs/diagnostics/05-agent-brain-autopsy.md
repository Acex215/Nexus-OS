# NEXUS OS — Agent Brain Autopsy
**Generated:** 2026-03-09
**Audited by:** Claude Code (read-only, no modifications made)
**Scope:** `/opt/nexus/agents/` + `/opt/nexus/automation/`

---

## Executive Summary

The NEXUS agent system has **two completely separate brains** that never talk to each other: the 30-bot Discord hierarchy (`hierarchy_manager.py`) and the Cognitive Autonomy Framework orchestrator (`dev_orchestrator.py`). Both are structurally broken in complementary ways.

**The Discord hierarchy** has been offline since February 17, 2026. Its blockchain logger points to a stale pre-VLAN IP and has been silently failing since the migration. Its core delegation mechanism is cosmetic — `delegates_to` is printed in a Discord embed but never actually routes work to subordinate agents. Ten total decisions were logged across 4 of 30 agents.

**The CAF orchestrator** is running (PID 2374) but stuck in an infinite retry loop since March 8. Its local LLM endpoint URL is stale (pre-VLAN migration). All LLM calls fall through to HuggingFace. It has violated its own constitution by modifying protected files and logged at least one phantom success.

Together, the system has no functioning end-to-end decision loop: decisions are produced, written to Discord embeds and blockchain, but never executed by subordinate agents.

---

## Section A: Decision Pipeline Flow

### A.1 Discord Hierarchy Pipeline (agents/)

```
Discord Message (user)
        │
        ▼
on_message [hierarchy_manager.py:196]
  ├─ Filters: author != self, not bot (unless webhook), correct channel
  │
  ▼
workflow.process_message(content) [agent_workflow.py]
  │
  ├─ Leadership agents (CEO, COO, Directors):
  │     gather_context → analyze → decide → finalize
  │
  └─ Worker agents:
        gather_context → decide → finalize
  │
  ▼
_gather_context() [agent_workflow.py:87-115]
  └─ KEYWORD MATCHING ONLY: scans message text for dept names, node names,
     urgency words, numeric patterns. No live system queries.
     Context entirely determined by what the human typed.
  │
  ▼
_analyze() [leadership only, agent_workflow.py:118-145]
  └─ LLM call: system_prompt + context_packet + user_message
     temperature=0.7, max_tokens=512
  │
  ▼
_decide() [agent_workflow.py:148-215]
  └─ LLM call: system_prompt + context + message → JSON response
     Expected: {decision, reasoning, delegates_to, priority, ect_cost}
     On parse failure → hardcoded fallback, NO actual manual review gate
  │
  ▼
_validate_decision() [agent_workflow.py:317-343]
  └─ Field presence + type coercion ONLY. No semantic validation.
  │
  ▼
_finalize() [agent_workflow.py:218-270]
  └─ SHA256(reasoning) → reasoning_hash
     Returns: {decision, delegates_to, ect_cost, timestamp, reasoning_hash}
  │
  ├─ bc.log_decision() [blockchain_logger.py:121]
  │    └─ RPC to 192.168.8.228:8545 (STALE IP — broken since VLAN migration)
  │       On failure: queued in pending_logs (grows indefinitely)
  │
  ├─ _log_decision() [hierarchy_manager.py:115]
  │    └─ Append to /opt/nexus/agents/logs/decisions/{agent_id}.jsonl
  │
  └─ _send_embed() [hierarchy_manager.py:248]
       └─ Discord embed showing: decision, reasoning, delegates_to, priority, ECT
          delegates_to is DISPLAYED ONLY — no routing to subordinate agents
```

**Critical gap:** After `_send_embed()`, the pipeline ends. If CEO decides `delegates_to: ["Storage"]`, the Storage Director channel receives nothing. No bot dispatches the task. The human must manually post to the storage-director channel to continue the chain.

### A.2 CAF Orchestrator Pipeline (automation/)

```
intent_registry.yaml
  └─ Selects next pending/retrying intent
        │
        ▼
context_builder.py → chroma_memory.py
  └─ Retrieves relevant past lessons from ChromaDB world model
        │
        ▼
planning_engine.py → LLM (Tier 1: ThinkPad / Tier 2: Ollama / HuggingFace)
  └─ Produces execution plan: list of {command, description} steps
        │
        ▼
guardrails.py — pre-execution checks:
  ├─ check_command_safety() → allowlist + blocklist
  ├─ check_protected_files()
  └─ check_change_size()
        │
        ▼
execution_engine.py → command_executor.py
  └─ Runs each step via subprocess on nexus-admin
     Creates auto/* git branch, backs up files, commits on success
        │
        ▼
feedback_loop.py → failure_analyzer.py
  └─ On failure: LLM diagnoses root cause, generates revised plan
     Stores lessons in world_model.db (SQLite on NAS)
     Retries up to depth limit (2)
        │
        ▼
audit_logger.py → audit.jsonl
  └─ Records success/failure (UNRELIABLE — confirmed phantom entries)
        │
        ▼
discord_reporter.py
  └─ Notifications to Discord channel(s)
```

---

## Section B: Critical Flaws (File:Line References)

### B.1 Stale RPC URL — All Blockchain Logging Broken

**File:** `blockchain_logger.py:27`
```python
RPC_URL = "http://192.168.8.228:8545"
```
**Should be:** `http://10.0.20.3:8545`

Every call to `bc.log_decision()` from every agent has failed since the VLAN migration in late February 2026. The `is_connected()` check returns `False`, entries are queued in `self.pending_logs`, and since the process is stopped (since Feb 17), the queue is discarded on restart. **No agent decision has been logged to the blockchain since the VLAN migration.**

The 1106 entries in ReasoningLedger predate the migration. The `project_state.json` claim of `"on_chain_decisions": 21` is frozen from February 2026 documentation and is doubly wrong.

### B.2 Stale Local LLM URL — Always Falls to HuggingFace

**File:** `llm_client.py:19`
```python
LOCAL_INFERENCE_URL = "http://192.168.8.128:8090/v1/chat/completions"
```
**Should be:** `http://10.0.20.4:8090/v1/chat/completions`

`_check_local_health()` (llm_client.py:~71) hits this URL, gets a connection refused, returns `False`, and every LLM call routes to HuggingFace. The local SmolLM2-1.7B model on nexus-ai (llama-server, 7–9 tok/s) is completely unused by the agent hierarchy. HuggingFace API calls are slower, rate-limited at 28 RPM across all 30 agents, and incur external network cost.

The CAF orchestrator uses a separate `llm_router.py` path with a different stale IP (`192.168.8.x`), causing the same problem.

### B.3 Delegation Is Cosmetic — No Routing Mechanism Exists

**File:** `hierarchy_manager.py:278-281`
```python
delegates = result.get("delegates_to", [])
embed.add_field(
    name="Delegates To",
    value=", ".join(delegates) if delegates else "None",
)
```

`delegates_to` is embedded in the Discord reply and logged to JSONL. That is the full extent of delegation. There is no code anywhere in `hierarchy_manager.py` that:
- Looks up the subordinate agent's channel
- Posts a task message to that channel
- Waits for or tracks the result

A CEO decision of `delegates_to: ["Storage", "Network"]` produces a pretty embed and nothing else. The Storage Director and Network Director never receive a task. The human operator is the only routing mechanism.

### B.4 No Task State Tracking — Tasks Enter Permanent Limbo

There is no task state machine in the agent hierarchy. Decision log entries have:
```json
{"agent_id": "ceo", "timestamp": "...", "decision": {...}, "delegates_to": [...], ...}
```

There is no `task_id`, no `status` field, no linkage between a CEO delegation and a Director's subsequent action. A task delegated by the CEO to Storage has:
- No created/in-progress/completed/failed lifecycle
- No timeout or escalation trigger
- No way for CEO to know the task was received, attempted, or completed
- No way to detect if it was silently dropped

Tasks can remain "delegated" indefinitely. There is no recovery mechanism.

### B.5 LLM Parse Failure Produces Garbage On-Chain

**File:** `agent_workflow.py:186-195` (fallback decision)
```python
result = {
    "decision": "Unable to parse decision - manual review needed",
    "reasoning": f"LLM response parsing error: {str(e)[:200]}",
    "delegates_to": [],
    "priority": 3,
    "ect_cost": 10,
}
```

**File:** `hierarchy_manager.py:218-225`
```python
tx_hash = await bc.log_decision(
    agent_id=self.agent_id,
    task=content[:100],
    reasoning_hash=result.get("reasoning_hash", ""),
    ect_cost=result.get("ect_cost", 0),
)
```

The blockchain logger is called unconditionally, even on parse failure. Confirmed in `ceo.jsonl` (Feb 16 entry):
```json
{"decision": {"decision": "Unable to parse decision - manual review needed",
  "reasoning": "LLM response parsing error: Bad request for model Qwen/Qwen2.5-7B-Instruct..."},
 "tx_hash": "4dcee3ca..."}
```

Garbage decisions are permanently recorded on-chain with a valid transaction hash. There is no validation gate that prevents submitting failed decisions to the immutable ledger. The "manual review needed" message implies human intervention that never occurs — no alert is raised, no queue is created, the bot simply proceeds.

### B.6 `_gather_context()` Is Pure Keyword Matching

**File:** `agent_workflow.py:87-115`

The context gathering step performs no live system queries. It scans the raw message text for:
- Department name substrings ("storage", "compute", "network", etc.)
- Node name substrings ("nexus-master", "nexus-ai2", etc.)
- Urgency keywords ("urgent", "critical", "emergency", etc.)
- Numeric patterns (percentages, numbers followed by units)

If a user types "we need to fix the issue", the context packet is empty. The LLM then decides with no system state. Context quality is entirely dependent on the human phrasing their message with the correct keywords.

No actual system state is queried at context-gathering time: no `kubectl get pods`, no `geth.eth.blockNumber`, no `ipfs swarm peers`, no disk usage. The agents produce decisions about a system they cannot observe.

### B.7 Singleton LLM Client Shared Across 30 Agents — Lock Contention

**File:** `llm_client.py` (singleton `_client_instance`)

All 30 Discord bot coroutines share a single `NexusLLMClient` instance via `get_llm_client()`. The rate limiter (`asyncio.Semaphore(28)` allowing 28 RPM) is per-instance, so all agents compete for 28 RPM. Under peak load (multiple messages simultaneously in different channels), agents will queue and stall. The 60-second ready timeout in `start_all()` could be violated if several agents simultaneously try to make LLM calls during startup.

### B.8 Webhook Agents Have No Workflow

**File:** `hierarchy_manager.py:153-157`
```python
async def start(self):
    if self.is_webhook:
        self._log.info("Webhook fallback — skipping client start")
        self.ready.set()
        return
```

The 5 webhook-fallback agents (`ml_worker_3` and 4 others) never initialize a `NexusAgentWorkflow`. Their `workflow` is `None`. They can never process a message. They are permanently silent stubs. The system reports 30 agents but only 25 are capable of any response.

### B.9 `pending_logs` Grows Indefinitely

**File:** `blockchain_logger.py:54`
```python
self.pending_logs: List[Dict] = []
```

Failed blockchain submissions are appended with no cap. With the RPC URL broken, every decision from every agent is appended. Since the hierarchy manager runs in-process until stopped, a session with many decisions would grow this list unbounded. On process restart the list is reset (in-memory only) — all pending entries are lost. No retry persistence exists across restarts.

---

## Section C: Missing Safeguards

| # | Missing Safeguard | Impact |
|---|-------------------|--------|
| 1 | **No delegation execution** | `delegates_to` produces UI output only; no agent ever receives the delegated task |
| 2 | **No task completion feedback** | CEO cannot know if delegated work succeeded, failed, or was lost |
| 3 | **No decision semantic validation** | LLM can return any `decision` string and pass validation |
| 4 | **No circuit breaker on HuggingFace** | HF API outage = all 30 agents fail silently on every message |
| 5 | **No blockchain pre-submission gate** | Parse failures submitted to immutable ledger with "manual review needed" text |
| 6 | **No pending log persistence** | Failed blockchain entries lost on process restart |
| 7 | **No live context gathering** | All decisions made without observing actual system state |
| 8 | **No task deduplication** | Same task can be delegated repeatedly with no idempotency check |
| 9 | **No context window management** | `max_tokens=512` hard-coded; long conversations silently truncated by provider |
| 10 | **No local LLM health enforcement** | Wrong URL accepted without startup warning or validation |
| 11 | **No authorization check** | Any Discord user in the channel can trigger CEO-level decisions; no role gating |
| 12 | **Constitution not self-enforcing** | `intent_registry.yaml` is marked protected but orchestrator modifies it freely |

---

## Section D: Decision Log Anomalies

### D.1 Coverage Gap — 26 of 30 Agents Have Zero Logs

Only 4 agents produced decision logs:
| Agent | Entries | Date Range |
|-------|---------|------------|
| `ceo` | 7 | 2026-02-15 to 2026-02-16 |
| `coo` | 1 | 2026-02-15 |
| `compute_worker_3` | 1 | 2026-02-15 |
| `storage_director` | 1 | 2026-02-15 |

26 agents (all workers except compute_worker_3, all other directors, all webhook agents) have no logs. Either they never received a message, or logs were deleted. The hierarchy manager last ran Feb 17, 2026 — 20 days before this audit.

### D.2 Last Activity: February 16-17, 2026

The hierarchy.log file (3.2 MB) was last modified Feb 17 14:17. The process has been stopped for 20 days. `project_state.json:75` claims `"hierarchy_manager": "operational"` — this is false.

### D.3 Model Not Supported Error — Garbage On-Chain (Feb 16 entry)

CEO decision log entry from 2026-02-16 10:20:
```json
{
  "decision": "Unable to parse decision - manual review needed",
  "reasoning": "LLM response parsing error: Bad request for model Qwen/Qwen2.5-7B-Instruct (400):
    {\"error\":{\"message\":\"The requested model 'Qwen/Qwen2.5-7B-Instruct' is not
    supported by any provider you have enabled.\"}}",
  "tx_hash": "4dcee3ca..."
}
```

**The LLM model itself was unavailable.** The CEO's LLM model (`Qwen/Qwen2.5-7B-Instruct`, llm_client.py:~100) was returning HTTP 400 from HuggingFace. The fallback decision text was submitted to the blockchain and stored permanently. This illustrates the full failure cascade: local LLM unreachable (wrong IP) → HuggingFace → model not available → parse error → garbage submitted to ledger.

### D.4 Invalid `delegates_to` Values

Several logged `delegates_to` values are not valid agent IDs or department names recognized by the workflow:

| Agent | `delegates_to` value | Valid? |
|-------|---------------------|--------|
| `ceo` | `["Storage"]` | Partial — capitalized dept name, but no routing exists |
| `ceo` | `["Network", "Security"]` | Same |
| `coo` | `["Communication"]` | **Invalid** — no "Communication" department in hierarchy |
| `compute_worker_3` | `["Department"]` | **Invalid** — literal placeholder from LLM prompt template |

The LLM prompt instructs the model to write `["Department"]` as an example in the system prompt (agent_workflow.py:161), and at least one worker has copied the example verbatim into its output. This is never caught by `_validate_decision()`, which only checks type (list), not content.

### D.5 ECT Cost Pattern

Fallback decisions uniformly produce `ect_cost: 10` (the hardcoded default in agent_workflow.py:192). Two entries in the CEO log have `ect_cost: 10`, including the parse-failure entry — confirming those decisions were produced by the error fallback path, not the LLM. Any entry with `ect_cost: 10` in the decision log is suspect.

### D.6 Blockchain Entry Count Discrepancy

| Source | Claim | Actual |
|--------|-------|--------|
| `project_state.json` (`on_chain_decisions`) | 21 | **Wrong** |
| `NEXUS_OS_Current_State.md` | 21 | **Wrong** |
| Live `getEntryCount()` call | — | **1,106** |
| Hierarchy agent decision logs | 10 off-chain JSONL entries | Only 4 agents |

The 1,106 on-chain entries predate the VLAN migration (all logged before blockchain_logger.py's stale IP broke in late February). Since the migration, zero new entries have been logged by agents. The 21-entry claim appears to have been frozen from early February testing.

---

## Section E: CAF Orchestrator Structural Issues (Additional)

### E.1 Duplicate Functions Diverge

`dev_orchestrator.py` contains its own implementations of `backup_file()` and `is_protected()` that duplicate (and differ from) the same functions in `execution_engine.py`. Neither imports the other for these functions. If `guardrails.py` PROTECTED_FILES is updated, only one copy reflects the change.

### E.2 No Depth-Limited Retry Recovery

The orchestrator retries failed intents up to `depth_limit=2` via `failure_analyzer.py`. After 2 revisions, the intent status is set to `retrying` and rescheduled — but with no backoff and no circuit break. The current stuck intent (`np-005.1.1`) has been retrying since March 8 because the depth limit is reached, the intent is rescheduled, and the cycle restarts. The `feedback_loop.py` accumulates lessons but the planning_engine generates the same plan each time.

### E.3 Constitution Violation Active

`constitution.json` lists `/opt/nexus/automation/intent_registry.yaml` as a protected file: `"Never be modified autonomously"`. The file's mtime is 2026-03-08 22:19 — modified by the orchestrator updating task statuses. The orchestrator creates backup files (`intent_registry.yaml.bak.*`) before modifying, showing awareness of the protection, but proceeds anyway. The guardrails do not enforce this protection for status-field updates.

### E.4 Audit Trail Unreliable

`audit.jsonl` entry id:9 records:
```json
{"success": true, "files_modified": ["/opt/nexus/dashboard/backend/data_sources.py"]}
```
The file does not exist. The directory is empty. The corresponding git commit (`e30ea6b`) has zero file changes. The orchestrator recorded a false success. `audit.jsonl` cannot be trusted as ground truth for what was actually modified.

---

## Summary of Critical Paths to Failure

```
CRITICAL PATH 1 (Blockchain logging — CURRENTLY BROKEN)
  blockchain_logger.py:27  RPC_URL stale pre-VLAN IP
  → Every bc.log_decision() queued to pending_logs
  → Queue discarded on restart
  → Zero agent decisions on-chain since VLAN migration

CRITICAL PATH 2 (Local LLM — CURRENTLY BROKEN)
  llm_client.py:19  LOCAL_INFERENCE_URL stale pre-VLAN IP
  → _check_local_health() always False
  → All 30 agents exclusively use HuggingFace API
  → SmolLM2 on nexus-ai completely unused
  → External dependency for every decision

CRITICAL PATH 3 (Delegation — STRUCTURALLY BROKEN)
  hierarchy_manager.py:278-281  delegates_to displayed only
  → CEO decides → delegates_to embed field
  → No channel.send() to subordinate agent
  → Storage/Network/Security Directors never receive tasks
  → All hierarchy workflow is single-hop CEO→Discord→human

CRITICAL PATH 4 (Hierarchy manager — OFFLINE)
  hierarchy.log last modified: 2026-02-17
  → 0 agents active for 20 days
  → project_state.json claims "operational" (wrong)
  → No decisions being made, no blockchain logging happening

CRITICAL PATH 5 (CAF orchestrator — STUCK)
  PID 2374, retrying np-005.1.1 since 2026-03-08 22:19
  → Infinite retry loop, depth_limit reached and reset
  → Each retry: 2x ChromaDB query + LLM call + Discord notification
  → Consumes HuggingFace API quota
  → Will continue until manually stopped or task resolved
```

---

*Report generated 2026-03-09. Read-only analysis — no files were modified.*
