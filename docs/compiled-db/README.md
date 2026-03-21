# NEXUS OS Compiled Database — v2.0

**Generated:** 2026-03-21
**Scope:** Dev Assistant pipeline (`/opt/nexus/agents/`) + shared infrastructure
**Supersedes:** Previous compiled-db generated against CAF (`/opt/nexus/automation/`)

## What This Is

A structured knowledge base describing the LIVE NEXUS OS system — its components,
code index, interfaces, dependencies, gaps, and architectural decisions. Intended
for use by humans, AI assistants, and automated tools that need to understand the
current state of the codebase.

## Files

| File | Contents |
|------|----------|
| `components.yaml` | All system components with status, files, dependencies |
| `code_index.yaml` | Every significant file with purpose, imports, category |
| `interfaces.yaml` | API/protocol interfaces between components |
| `dependencies.yaml` | Dependency graph with modification risk ratings |
| `gaps.yaml` | Known issues and technical debt (G100+) |
| `decisions.yaml` | Architectural decisions with rationale (D100+) |

## ID Numbering

Gap IDs start at G100 and decision IDs at D100 to clearly distinguish from the
deprecated CAF gaps (G001-G039) and decisions (D001-D024). The old IDs described
the CAF orchestrator which is no longer running.

## What Changed from v1

The previous compiled-db was generated on 2026-03-09 against the Cognitive Autonomy
Framework (CAF) — a 28-file orchestrator in `/opt/nexus/automation/`. CAF has been
replaced by the Dev Assistant pipeline in `/opt/nexus/agents/`. Key differences:

- **Entry point:** `dev_orchestrator.py` (1216 lines, untracked) → `dev_assistant.py` (tracked, tested)
- **Task tracking:** `intent_registry.yaml` → `task_queue.yaml`
- **LLM routing:** `automation/llm_router.py` (2-tier) → `agents/llm_router_v2.py` (4-tier)
- **Safety:** `guardrails.py` (allowlist) → `safety_gates.py` (risk-based approval + scope enforcement)
- **Knowledge:** `context_builder.py` (3-tier context) → `knowledge_planner.py` (ChromaDB semantic retrieval)
- **Tests:** None → 101/101 passing

## Keeping This Current

Update this compiled-db when:
- New files are added to `/opt/nexus/agents/`
- Component status changes (e.g., agent-hierarchy goes from dormant → operational)
- New gaps are discovered or existing gaps are resolved
- Architectural decisions are made or reversed
- Infrastructure changes (new nodes, IP changes, contract deployments)

## Authoritative References

1. **Roadmap v2.0** (`NEXUS_AI_ASSISTANT_ROADMAP.md`, 2026-03-20) — phases, exit criteria, target architecture
2. **This compiled-db** — current system state, gaps, decisions
3. **Test suite** (101 tests in `/opt/nexus/agents/test_*.py`) — ground truth for what works
