# NEXUS OS Living Development Guide
## Last Updated: 2026-02-27T00:00:00Z
## Updated By: human (initial creation)

---

## SECTION 1: What NEXUS OS Is

NEXUS OS is the world's first blockchain-native operating system where
Ethereum consensus functions as the actual kernel. Smart contracts replace
traditional system calls, every device operates as an Ethereum wallet,
and all operations are recorded as immutable blockchain transactions.

Core tagline: Your Data. Your Hardware. Your Rules.

---

## SECTION 2: Current System State

See /opt/nexus/automation/project_state.json for machine-readable state.

Human-readable summary:
- Cluster: 5 nodes on 3 VLANs (10, 20, 30), K3s running, VLAN 20 air-gapped
- Blockchain: 3 validators, period=0, 3 contracts deployed
- Agents: 30 Discord bots with LangGraph, logging to blockchain
- Storage: IPFS 4-node mesh + 2TB NAS via NFS
- Inference: ThinkPad (Tier 1, Qwen3.5-35B) + nexus-ai2 (Tier 2, Qwen2.5-7B)
- OS Image: v0.1 beta built (913MB), not flashed to test hardware

---

## SECTION 3: Priority Queue

### P0 — Do Now (Score 1-2, fully autonomous)
1. Verify all services healthy after VLAN migration (Geth, IPFS, K3s, agents)
2. Join nexus-ai2 to K3s cluster as worker
3. Install Ollama on nexus-ai (Tier 3, for simple execution)
4. Run existing test suites and log results

### P1 — Do This Week (Score 2, autonomous with summary)
5. Update agent_registry.py to include nexus-ai2 in cluster context
6. Update llm_client.py to support Ollama endpoints as additional fallback
7. Create monitoring script that checks all service health every 5 minutes
8. Seed ChromaDB with all agent decision logs from /opt/nexus/agents/logs/

### P2 — Needs Planning (Score 2-3, propose first)
9. Switch agent LLM calls from HuggingFace API to local Ollama (Tier 2)
10. Implement libnexus unified Python library for storage operations
11. End-to-end encrypted file upload/download pipeline
12. Storage proof verification (Merkle proofs)

### P3 — Needs Tier 0 Approval (Score 3, wait for Md)
13. Agent system prompt updates for new network topology
14. Token economy parameter adjustments
15. Academic paper draft preparation
16. Flashable image testing on physical hardware

---

## SECTION 4: Completed Work Log

(Auto-populated by orchestrator after each task)

---

## SECTION 5: Failed Attempts Log

(Auto-populated by orchestrator when tasks fail)

---

## SECTION 6: Architecture Decisions

See ChromaDB 'nexus_decisions' collection. Key principles:
1. Blockchain IS the kernel
2. Every device = Ethereum wallet
3. Smart contracts replace syscalls
4. Zero cloud dependency
5. Air-gapped security with 3 VLANs
6. LangGraph for agent workflows
7. Patent filed — innovations are fixed

---

## SECTION 7: Ideas Not Yet Implementable

- Satellite mesh networking (SatNOGS integration)
- Federated learning revenue via FLock.io
- Quantum optimization (SKQ/Q4P) for scheduling
- Prayer tracking DeFi system
- Enterprise marketing and V2 Network branding
- Pi Zero 2W as NEXUS Sentinel (Byzantine failure detector)
- Flipper Zero RF monitoring integration

- [2026-03-03 12:29] [FAILED] Create tool_registry.yaml with expanded tool definitions

- [2026-03-03 12:34] [FAILED] Create tool_registry.yaml with expanded tool definitions

- [2026-03-03 12:39] [FAILED] Create tool_registry.yaml with expanded tool definitions

- [2026-03-03 12:50] [FAILED] Create tool_registry.yaml with expanded tool definitions

- [2026-03-03 13:01] [DONE] Create tool_registry.yaml with expanded tool definitions

- [2026-03-03 13:21] [DONE] Action Type Registry Design

- [2026-03-03 14:15] [DONE] Data Integration Layer

- [2026-03-03 17:03] [DONE] Python Decoder Module

- [2026-03-03 17:11] [DONE] Documentation and Protocol Specification

- [2026-03-05 09:10] [DONE] Data Processing Pipeline Setup

- [2026-03-05 09:15] [FAILED] Testing

- [2026-03-05 09:49] [FAILED] Testing

- [2026-03-05 09:55] [FAILED] Testing

- [2026-03-05 10:57] [FAILED] Testing

- [2026-03-05 13:19] [FAILED] Run Unit Tests

- [2026-03-05 18:45] [FAILED] Model Export and Validation

- [2026-03-06 21:00] [FAILED] Data Collection and Preparation

- [2026-03-06 21:06] [DONE] Create Installation Instructions

- [2026-03-06 21:10] [DONE] Create Usage Examples

- [2026-03-07 21:14] [FAILED] Model Export and Validation

- [2026-03-08 22:19] [FAILED] Run Unit Tests
