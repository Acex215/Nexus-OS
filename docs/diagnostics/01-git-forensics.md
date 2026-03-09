# NEXUS OS — Git Forensics Report
**Generated:** 2026-03-09
**Audited by:** Claude Code (read-only, no modifications made)
**Scope:** /opt/nexus git repository

---

## Executive Summary

The autonomous **Cognitive Autonomy Framework (CAF)** has been operating since at least 2026-03-02. It is an intentional system built by the repo owner (Acex215 / mhuraibi), not an external intrusion. However, it has accumulated significant operational debt: 22 auto/ branches, none merged to main, a working directory checked out to an agent branch instead of main, and a process that has been running continuously since 2026-03-05.

**No production code on `main` was corrupted.** All agent-generated code lives in unreviewed, unmerged branches. The primary risks are branch pollution, a stuck retry loop generating LLM API calls, and a working directory that is off main.

**ALERT: `dev_orchestrator.py` (PID 2374) is actively running right now** as of this audit.

---

## 1. Branch Inventory

### Main Branch
| Branch | Commits | Status |
|--------|---------|--------|
| `main` | 1 (Initial commit only, 2026-02-25) | Clean — no agent code merged |
| `remotes/origin/main` | 1 (same) | In sync with local main |

### Agent Branches (22 total, all `auto/` prefix)

| Branch | Commits Ahead Main | Merged? | Last Activity | Notes |
|--------|--------------------|---------|---------------|-------|
| `auto/np-004-1-f2-2-1772849379` | **2** | NO | 2026-03-06 | **CURRENTLY CHECKED OUT** |
| `auto/np-004-1-f2-1-1772849148` | **1** | NO | 2026-03-06 | |
| `auto/np-004-1-1772719610` | **6** | NO | 2026-03-05 | Largest unmerged set |
| `auto/np-004-1-f1-1772720041` | **6** | NO | 2026-03-05 | Duplicate of above |
| `auto/rm-001-5-1772575635` | **5** | NO | 2026-03-03 | |
| `auto/rm-001-4-1772575142` | **4** | NO | 2026-03-03 | |
| `auto/np-001-3-1772565108` | **3** | NO | 2026-03-03 | |
| `auto/rm-001-1-1772561755` | **2** | NO | 2026-03-03 | |
| `auto/ns-004-1-1772560645` | **1** | NO | 2026-03-03 | |
| `auto/np-004-1-f1-1-1772734298` | 0 | "merged" (empty) | 2026-03-05 | |
| `auto/np-004-1-f1-1772722060` | 0 | "merged" (empty) | 2026-03-05 | |
| `auto/np-004-1-f1-1772722444` | 0 | "merged" (empty) | 2026-03-05 | |
| `auto/np-004-1-f1-1772725616` | 0 | "merged" (empty) | 2026-03-05 | |
| `auto/np-004-1-f1-1772725668` | 0 | "merged" (empty) | 2026-03-05 | |
| `auto/np-005-3-1772754109` | 0 | "merged" (empty) | 2026-03-05 | |
| `auto/np-005-3-1772754222` | 0 | "merged" (empty) | 2026-03-05 | |
| `auto/ns-004-1-1772546622` | 0 | "merged" (empty) | 2026-03-03 | |
| `auto/ns-004-1-1772558861` | 0 | "merged" (empty) | 2026-03-03 | |
| `auto/ns-004-1-1772559172` | 0 | "merged" (empty) | 2026-03-03 | |
| `auto/ns-004-1-1772559478` | 0 | "merged" (empty) | 2026-03-03 | |
| `auto/ns-004-1-1772560150` | 0 | "merged" (empty) | 2026-03-03 | |
| `auto/ns-004-1-1772560444` | 0 | "merged" (empty) | 2026-03-03 | |
| `auto/rm-001-1-1772550066` | 0 | "merged" (empty) | 2026-03-03 | |

**Note on "merged" branches:** The 13 branches showing 0 commits ahead are at the same SHA as `main`. They appear to have been created and immediately abandoned (zero-commit branches), not genuinely merged via pull request. No git merge commit exists on main.

---

## 2. Commit Timeline (All Agent Commits)

Total commits across all branches: **9 substantive commits** + 1 initial commit = 10 total.

| Hash | Date | Author | Message | Files Changed |
|------|------|--------|---------|---------------|
| `d4af498` | 2026-02-25 | Acex215 | Initial commit | ~150 files (full codebase) |
| `bde02c0` | 2026-03-03 12:57 | Acex215 | [CAF auto] ns-004.1: Create tool_registry.yaml | `automation/tool_registry.yaml` (+21), `docs/encoding_protocol.md` (+57) |
| `c7c7cee` | 2026-03-03 13:15 | Acex215 | [CAF auto] rm-001.1: Define initial action types | (0 file changes — empty commit) |
| `e30ea6b` | 2026-03-03 14:11 | Acex215 | [CAF auto] np-001.3: Implement secure read-only access | (0 file changes — empty commit) |
| `9104be7` | 2026-03-03 16:59 | Acex215 | [CAF auto] rm-001.4: Implement tx_to_action() | `automation/action_decoder.py` (+5) |
| `0685d66` | 2026-03-03 17:07 | Acex215 | [CAF auto] rm-001.5: Encoding protocol documentation | (0 file changes — repeat of bde02c0 content) |
| `c0d34fb` | 2026-03-05 09:06 | Acex215 | [CAF auto] np-004.1: Set up data processing pipeline | `automation/knowledge_base/processor.py` (+9) |
| `2e85dbc` | 2026-03-06 21:05 | Acex215 | [CAF auto] np-004.1-f2.1: Create installation instructions | `docs/pipeline_installation.md` (+12) |
| `840b916` | 2026-03-06 21:09 | Acex215 | [CAF auto] np-004.1-f2.2: Create usage examples | `docs/pipeline_usage_examples.md` (+45) |

**Last agent commit: 2026-03-06 21:09** (3 days before this audit). The orchestrator has not committed since, but is still running.

---

## 3. Unmerged Agent Branches — Risk Assessment

### Files Created in Agent Branches (Never Landed on Main)

These files exist in unmerged branches. They are small and largely trivial:

| File | Branch | Lines | Risk |
|------|--------|-------|------|
| `automation/tool_registry.yaml` | ns-004.1 | 21 | Low — stub YAML |
| `docs/encoding_protocol.md` | rm-001.1 | 57 | Low — documentation |
| `automation/action_decoder.py` | rm-001.4 | 5 | Low — stub function |
| `automation/knowledge_base/processor.py` | np-004.1 | 9 | Low — stub |
| `docs/pipeline_installation.md` | np-004.1-f2.1 | 12 | Low — sparse docs |
| `docs/pipeline_usage_examples.md` | np-004.1-f2.2 | 45 | Low — example docs |

**Verdict:** The agent created very small stub files (5–57 lines each). None touch production logic. The content is trivially safe — a 5-line decoder function, a 21-line YAML stub, some sparse docs.

### Phantom Audit Record (CONCERNING)

The audit log records that `np-001.3` "modified" `/opt/nexus/dashboard/backend/data_sources.py`. However:
- The `dashboard/backend/` directory **exists but is completely empty**
- The git commit `e30ea6b` has **zero file changes** (confirmed via `git show --stat`)
- The file `data_sources.py` **does not exist** anywhere in the tree

**The agent logged a false success.** The orchestrator recorded the task as complete (`"success": true`, `"files_modified": ["/opt/nexus/dashboard/backend/data_sources.py"]`) but the git commit it created is empty and the file does not exist on disk. This is a reliability issue in the CAF audit trail — the audit cannot be fully trusted.

### Tasks That Tried Dangerous Operations

| Task | Attempted Action | Blocked By | Outcome |
|------|-----------------|------------|---------|
| `np-005.3` | Create GGUF model file at `/mnt/nexus-nas/models/smollm2-1.7b-instruct-q4_k_m.gguf` | Missing export script | Failed — file NOT created |
| `np-005.1.1` | `wget` (download external data) | Command allowlist guardrail | Blocked for approval — never executed |
| `ns-004.1` | Write to `/opt/nexus/automation/` | Permission denied (5 retries) | Eventually succeeded on 6th attempt |

---

## 4. Orphaned/Untracked Files

### The `automation/` Directory (UNTRACKED — NOT IN GIT)

The entire `/opt/nexus/automation/` directory (45+ files) is **completely untracked by git**. This is the CAF system itself. Key files:

| File | Size | Last Modified | Notes |
|------|------|---------------|-------|
| `orchestrator.log` | 1.4 MB | **2026-03-09 09:27** (TODAY) | Active — written this morning |
| `indexer.log` | 356 KB | 2026-03-09 03:00 (TODAY) | Active |
| `dev_orchestrator.py` | 55 KB | 2026-03-05 | The running agent |
| `intent_registry.yaml` | 42 KB | **2026-03-08 22:19** | **PROTECTED FILE** (per constitution.json) — modified |
| `intent_registry.yaml.bak.20260305_074832` | 59 KB | 2026-03-05 | Backup from Mar 5 |
| `intent_registry.yaml.bak.20260305_084151` | 31 KB | 2026-03-05 | Second backup — content shrank |
| `command_executor.py` | 24 KB | 2026-03-05 | Executes shell commands |
| `planning_engine.py` | 19 KB | 2026-03-05 | LLM-driven task planner |
| `audit.jsonl` | 13 KB | 2026-03-08 22:19 | 31 audit records |
| `change_ledger.md` | 8 KB | 2026-03-06 21:10 | Human-readable change log |
| `constitution.json` | 2.7 KB | 2026-03-03 | Agent rules (PROTECTED) |

**Constitution violation:** `constitution.json` explicitly lists `intent_registry.yaml` as a protected file that must "Never be modified autonomously." The file has been modified. The `.bak` files suggest the orchestrator was aware of this (it backed up before modifying).

**The `automation/` directory is not in `.gitignore` either** — it appears to have been intentionally excluded from commits but the decision was never formalized.

### The `backups/` Directory (UNTRACKED)

Contains 26 subdirectories mirroring each `auto/` branch name (e.g., `backups/auto/np-004-1-1772719610/`). Appears to be pre-execution snapshots taken by the orchestrator before attempting branch work. Last modified 2026-03-06.

### The `Makefile` (UNTRACKED)

Located at `/opt/nexus/backups/Makefile`, 90 bytes, dated 2026-03-05. Appears to be a stub file created by the agent (referenced in error: `make: *** No rule to make target 'test_all'. Stop.`).

---

## 5. Suspicious / Noteworthy Patterns

### 1. Working Directory Is NOT on Main
**Current branch: `auto/np-004-1-f2-2-1772849379`**

The orchestrator checks out branches to do work but never returns to `main`. Any developer `git pull` or `git status` from this machine will see branch-relative state, not main. If the developer runs `git checkout main`, the agent-created files in the checked-out branch disappear from the working tree (they exist only in that branch).

### 2. Infinite Retry Loop (Currently Active)
The orchestrator has been retrying `np-005.1.1` (Data Collection and Preparation) approximately every 30 minutes since 2026-03-08 22:19. Each retry:
- Queries ChromaDB twice
- Calls the LLM (2-3 minute round trip to Tier 1)
- Generates a Discord notification
- Fails with "depth limit (2) reached"

This loop has been running for ~11 hours and is still active now (Discord gateway resumed at 09:27 today). It will continue until the task is manually resolved or the process is stopped.

### 3. Repeated Branch Proliferation for Same Task
The task `ns-004.1` generated **7 branches** (6 failures + 1 success) for a single intent. The task `np-004.1-f1` generated **5 branches** (all failures, all for the same `pytest not found` error). The orchestrator does not deduplicate — it creates a new branch on every retry. Over time, this will accumulate hundreds of stale branches.

### 4. Intent Registry Modified Despite Protection
The `intent_registry.yaml` (a protected file per constitution) was last modified 2026-03-08, most recently by the orchestrator itself (updating task statuses). The two `.bak` files from 2026-03-05 show it was backed up before significant modifications. Protection rules are not being enforced for status updates.

### 5. Audit Trail Unreliable
As noted above, at least one audit entry (`id: 9`, task `np-001.3`) records a file modification that did not occur. The audit JSONL should not be trusted as a source of truth for what was actually changed.

### 6. IPFS Datastore in Git (Pre-existing)
The initial commit included live IPFS datastore `.ldb` and `.log` files. These are binary database files that change constantly. Git now shows them as "deleted" (they were replaced by newer LevelDB files). This was a bad initial commit — IPFS datastore should be in `.gitignore`.

---

## 6. Files Confirmed Modified on main or Production Filesystem

**None.** Every agent commit is in an unmerged branch. The working filesystem outside `automation/` is unchanged from the initial commit state (confirmed by git status showing only IPFS datastore churn and the automation/backups/Makefile untracked directories).

---

## 7. What Did NOT Happen (Clearing the Record)

- The orchestrator did **NOT** modify any smart contract source (`.sol` files)
- The orchestrator did **NOT** modify blockchain genesis files
- The orchestrator did **NOT** push any branches to remote (remote/origin/main is unchanged)
- The orchestrator did **NOT** touch Geth, Clef, or K3s configuration
- The orchestrator did **NOT** modify agent core files (`hierarchy_manager.py`, `agent_registry.py`, etc.)
- The orchestrator did **NOT** access VLAN 20 nodes autonomously (no SSH commands in audit)
- The np-005.3 NAS model write **failed** — the file does not exist on the NAS

---

## 8. Recommended Actions

**Immediate (before next dev session):**
1. `git checkout main` — return working directory to main
2. Decide whether to kill the orchestrator: `kill 2374` stops the retry loop
3. Or resolve `np-005.1.1` in the intent registry to stop the loop without killing the process

**Short term:**
4. Delete the 22 `auto/` branches: `git branch | grep '^  auto/' | xargs git branch -d`
5. Review the 6 unmerged branches with actual code — decide to merge, squash-merge, or abandon
6. Add `/opt/nexus/automation/orchestrator.log` and `indexer.log` to `.gitignore`
7. Add `/opt/nexus/ipfs/datastore/` to `.gitignore`
8. Formalize `automation/` as either tracked or gitignored

**Audit reliability:**
9. Do not trust `audit.jsonl` as ground truth — cross-check against `git log` for actual changes
10. Fix the false-success logging bug (task `np-001.3` case) in the orchestrator

---

*Report generated 2026-03-09. Read-only analysis — no files were modified.*
