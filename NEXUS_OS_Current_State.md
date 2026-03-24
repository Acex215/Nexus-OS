# NEXUS OS — Current System State

**Last Updated:** 2026-03-23
**Chain Height:** 1816 blocks
**Blockchain:** Geth Clique PoA, chain ID 123454321, period=0

---

## 1. What Works (with evidence)

### Blockchain (Geth PoA)
- 3 validators running: nexus-master, nexus-ai, nexus-storage (all `nexus-geth` + `clef` active)
- Chain height: 1816, period=0 (blocks only on pending tx — expected behavior)
- Clef signing via IPC on all validators, rules.js auto-approval
- 1187 ReasoningLedger entries logged
- 14,024 ECT minted, 320 ECT spent, 414 RST earned, 362 RST slashed
- Deployer balance: 999.5 ETH, 1000 ECT, 52 RST

### Smart Contracts (10 deployed)
| Contract | Address | Source | Notes |
|---|---|---|---|
| ReasoningLedger | 0x0317…DE4 | ✅ .sol | 1187 entries |
| StorageRegistry | 0x859e…A6 | ✅ .sol | |
| TokenManager | 0x08C9…E48 | ✅ .sol (reconstructed) | Active daily mints |
| DecisionQuality | 0x4198…218 | ✅ .sol (reconstructed) | 25 decisions evaluated, score=62 |
| AgentGovernance | 0xA4f8…207 | ❌ no source | Deployed JSON only |
| ServiceRegistry | 0xbd01…8d8 | ✅ .sol | Block 1709 |
| MeshRegistry | 0x21e5…E2F | ✅ .sol | 1 peer registered |
| ResourceManager | (deployed) | ✅ .sol | 0 nodes registered (see Known Issues) |
| PidRegistry | (deployed) | ✅ .sol | |
| TemporalScheduler | (deployed) | ✅ .sol | 2 assignments, 2 bins used |

### Token Economy
- Daily ECT mint cycle: `nexus-ect-cycle.timer` fires at 00:05 UTC (active, last ran 2026-03-23)
- Mints 1000 ECT/node/day via `batchMintECT` or `mintDailyECT`
- Token enforcement: **OFF** (`NEXUS_TOKEN_ENFORCEMENT` not set)
- `token_hooks.py` wired to real blockchain calls — logs real balances, spends real ECT
- Deployer authorized as minter, spender, and RST manager

### IPFS (Kubo 0.32.1)
- Private cluster with swarm.key
- 2 peers connected from nexus-admin
- Repo: 330 objects, ~76 MB, 15 GB limit on admin node
- Running on all 4 nodes (master, ai, storage, admin)

### Discord Agents
- `nexus-agent-v2.service`: **active** (autonomous dev assistant)
- 30 agents defined (2 C-Suite, 7 Directors, 21 Workers)
- Agent hierarchy managed by `/opt/nexus/agents/hierarchy_manager.py`
- LLM client supports local-first with HuggingFace API fallback

### Dashboard ("NEXUS Command Center")
- **Frontend**: Vite + React, served at `http://0.0.0.0:3000` (built production assets)
- **API**: FastAPI at `http://0.0.0.0:8768`, 35+ endpoints
- Both `nexus-dashboard.service` and `nexus-dashboard-api.service` **active**
- All tested API endpoints return HTTP 200:
  - `/api/config`, `/api/blockchain/summary`, `/api/blockchain/blocks`
  - `/api/tokens/summary`, `/api/tokens/balances`
  - `/api/tasks/queue`, `/api/tasks/history`
  - `/api/agents/status`, `/api/git/log`
  - `/api/temporal/summary`, `/api/temporal/heatmap`
  - `/api/health/services`, `/api/knowledge/collections`

### LLM Inference
- 4-tier router (`llm_router_v2.py`):
  - **Coordinator**: `qwen3.5-35b-a3b` @ ThinkStation 10.0.30.3:1234 — ✅ healthy
  - **Coder**: `qwen2.5-coder-14b` @ ThinkPad 10.0.30.2:1234 — ✅ healthy
  - **Director**: same as coordinator — ✅ healthy
  - **Worker**: `llama3.2:1b` @ nexus-ai2 10.0.20.6:11434 (Ollama) — ✅ healthy
- Local inference (nexus-ai): `local-inference.service` **active**, SmolLM2-1.7B @ 10.0.20.4:8090

### Gateway
- `nexus-gateway.service` **active**, listening on port 8766
- WebSocket + HTTP protocol for agent communication
- Dashboard API health check shows gateway error to 10.0.20.1:8766 (see Known Issues)

### Autonomous Loop
- Pre-flight coder health check before each task iteration
- Safety gates: risk classification, approval timeouts, retry policy
- Destructive patch guard: configurable `MAX_NET_DELETIONS=20`, `MAX_SHRINKAGE_PERCENT=0.20`
- ChromaDB warm-up at startup to avoid heartbeat warnings
- Test validator runs after execution

### K3s Cluster
- Master at 10.0.20.3:6443, `k3s.service` **active**
- Admin node has `k3s-agent.service` **active**, configured as `role=admin`
- `kubectl` not configured on nexus-admin (kubeconfig missing or expired)

### libnexus
- `NexusKernel` — full syscall interface covering all 7+ contracts (v0.3.0)
- `TokenClient` — dedicated ECT/RST client with wallet unlock
- `NexusStorage` — IPFS upload/download with on-chain CID registration
- 42 public methods on NexusKernel

---

## 2. What Is Designed But Not Built

- **AgentGovernance.sol source**: Deployed contract exists but no source recovered yet
- **ResourceManager node registration**: 0 nodes registered on-chain (nodes run but aren't self-registering)
- **MeshRegistry**: Only 1 peer registered (should be 4)
- **BATMAN-adv mesh**: Scripts exist at `/opt/nexus/networking/` but not deployed in production
- **WireGuard overlay**: Keys generated, scripts exist, not activated
- **pi-gen custom images**: Image built (748 MB) but not used for provisioning
- **Token enforcement**: All infrastructure wired but `NEXUS_TOKEN_ENFORCEMENT=false`
- **Node agents on cluster**: `nexus-node-agent` service **inactive** on all 3 validator nodes
- **nexus-ai2**: Unreachable via SSH (may be powered off)
- **ECT burn cycle**: No burn function in TokenManager ABI; daily script only mints
- **FreedomBox integration**: Source extracted, service framework exists, not activated

---

## 3. Hardware Topology

| Node | IP | VLAN | Role | Storage | Accelerator |
|---|---|---|---|---|---|
| nexus-master | 10.0.20.3 | 20 | K3s control-plane, Geth validator | 235G NVMe | — |
| nexus-ai | 10.0.20.4 | 20 | K3s worker (ai-inference), Geth validator | 128G SD | Hailo-8 (vision only) |
| nexus-storage | 10.0.20.11 | 20 | K3s worker (storage), Geth validator | 128G SD | — |
| nexus-ai2 | 10.0.20.6 | 20 | K3s worker, Ollama inference | — | Hailo-10H AI HAT+ |
| nexus-admin | 10.0.10.5 | 10 | K3s worker (admin), dev/ops (THIS machine) | 32G SD | — |
| ThinkPad | 10.0.30.2 | 30 | External dev, LM Studio (coder model) | — | — |
| ThinkStation | 10.0.30.3 | 30 | External dev, LM Studio (coordinator model) | — | — |

**Network**: VLAN 20 = validator cluster, VLAN 10 = admin, VLAN 30 = external dev machines.
iptables on nexus-admin blocks VLAN 30 → VLAN 20 forwarding; allows SSH from ThinkPad.

---

## 4. Deployed Contracts

All on Geth Clique PoA, chain ID 123454321.

| Contract | Address | Block | Source |
|---|---|---|---|
| ReasoningLedger | `0x0317451264E1de1A0696A81f6141e72E58686DE4` | early | ✅ |
| StorageRegistry | `0x859e30a6b752Af6D96d309Dc3a5bECfCfFDe31A6` | — | ✅ |
| TokenManager | `0x08C96540A286a6b3cDe1E20F77B246E53D238E48` | 1543 | ✅ |
| DecisionQuality | `0x4198228d18c8435d73E51105b912032f657f7218` | 1544 | ✅ |
| AgentGovernance | `0xA4f8CA77065bE462324624083990F58ff1f12207` | — | ❌ |
| ServiceRegistry | `0xbd015B6A2C0E10E1f31b7C50580A2Cc86e3A0dd8` | 1709 | ✅ |
| MeshRegistry | `0x21e59f66850bbC7333dE62fF5f7d6c2bcaD9A26F` | 1717 | ✅ |
| ResourceManager | (see deployed JSON) | — | ✅ |
| PidRegistry | (see deployed JSON) | — | ✅ |
| TemporalScheduler | (see deployed JSON) | — | ✅ |

Deployer: `0x817B0842B208B76A7665948F8D1A0592F9b1e958`
Source directory: `/opt/nexus/contracts/source/`
Deployed ABI+address: `/opt/nexus/contracts/deployed/`

---

## 5. Token Economy Status

| Metric | Value |
|---|---|
| ECT Minted (total) | 14,024 |
| ECT Spent (total) | 320 |
| RST Earned (total) | 414 |
| RST Slashed (total) | 362 |
| Deployer ECT Balance | 1,000 |
| Deployer RST Balance | 52 |
| Enforcement | **OFF** (logging + real blockchain writes, no blocking) |
| Daily Mint | 1,000 ECT/node via `nexus-ect-cycle.timer` at 00:05 UTC |
| Registered Nodes | 0 (mint falls back to deployer only) |

---

## 6. Temporal Binning Status

| Metric | Value |
|---|---|
| Total Assignments | 2 |
| Total Bins Used | 2 |
| Current Bin | Week 13, Tuesday, hour 1 UTC |
| Contract | TemporalScheduler (deployed) |
| Dashboard Panel | `/api/temporal/summary` and `/api/temporal/heatmap` — working |

Temporal binning is deployed and functional but underutilized — only 2 tasks assigned.

---

## 7. Node Agent Status

| Node | `nexus-node-agent` | `nexus-geth` | `clef` | `ipfs` |
|---|---|---|---|---|
| nexus-master | **inactive** | active | active | active |
| nexus-ai | **inactive** | active | active | active |
| nexus-storage | **inactive** | active | active | active |
| nexus-ai2 | unreachable | — | — | — |
| nexus-admin | n/a (runs agent-v2) | n/a | n/a | active |

Node agents were deployed (Tier 3 commit) but are not running on any cluster node.
The autonomous agent (`nexus-agent-v2.service`) runs on nexus-admin and is **active**.

---

## 8. Dashboard Status

**Services**: `nexus-dashboard.service` (port 3000) + `nexus-dashboard-api.service` (port 8768)

| Panel / Endpoint | Status | Notes |
|---|---|---|
| Blockchain Summary | ✅ 200 | Block height, tx count |
| Blockchain Blocks | ✅ 200 | Recent blocks |
| Token Summary | ✅ 200 | Totals, enforcement flag |
| Token Balances | ✅ 200 | Per-address balances |
| Task Queue | ✅ 200 | Active task list |
| Task History | ✅ 200 | Completed tasks |
| Agent Status | ✅ 200 | 5 entries (LLM tier health) |
| Git Log | ✅ 200 | Recent commits |
| Temporal Summary | ✅ 200 | Bin stats |
| Temporal Heatmap | ✅ 200 | Utilization grid |
| Health Services | ✅ 200 | systemd service states |
| Knowledge Collections | ✅ 200 | ChromaDB collections |
| Nodes (via gateway) | ⚠️ error | Gateway at 10.0.20.1:8766 unreachable |

The `/api/nodes` and `/api/health` endpoints fail because they proxy through the gateway
which tries to reach `10.0.20.1:8766` — this IP doesn't exist (should be `10.0.10.5:8766`
or `localhost:8766`). Direct dashboard API endpoints that don't need the gateway all work.

---

## 9. Known Issues

1. **Gateway proxy IP wrong**: Dashboard API tries to reach gateway at `10.0.20.1:8766` — no such host. Gateway listens on `0.0.0.0:8766` on nexus-admin (10.0.10.5). Affects `/api/nodes` and `/api/health`.

2. **Node agents inactive**: `nexus-node-agent.service` is inactive on all 3 validator nodes. Heartbeat/metrics pipeline not running.

3. **ResourceManager empty**: 0 nodes registered on-chain. Nodes have never called `registerNode()`. Daily ECT mint falls back to deployer-only.

4. **MeshRegistry sparse**: Only 1 peer registered (should be 4 nodes).

5. **nexus-ai2 unreachable**: SSH times out to 10.0.20.6. May be powered off or network issue. Ollama endpoint (11434) shows healthy from dashboard health check — may be intermittent.

6. **kubectl not working on admin**: kubeconfig not set up on nexus-admin despite k3s-agent running. Cannot manage cluster from this node.

7. **AgentGovernance.sol**: No source recovered. Only deployed JSON exists.

8. **DecisionQuality score low**: Current deployer score is 62 (below reward threshold of 75). 21/25 successes, avg impact 7.4.

9. **Token enforcement off**: All wiring complete but enforcement disabled. Switching on requires ensuring all active agents have sufficient ECT budgets.

10. **No ECT burn function**: TokenManager has `ECTBurned` event but no public burn method. ECT accumulates indefinitely.

---

## 10. Next Steps

1. **Fix gateway proxy IP** — update dashboard API config to use `localhost:8766` or `10.0.10.5:8766`
2. **Activate node agents** — start `nexus-node-agent.service` on master/ai/storage, debug why inactive
3. **Register nodes on-chain** — call `registerNode()` for each validator to populate ResourceManager
4. **Register mesh peers** — call `registerPeer()` for all 4 nodes in MeshRegistry
5. **Recover AgentGovernance.sol** — reverse-engineer from deployed ABI (same pattern as TokenManager/DecisionQuality)
6. **Fix nexus-ai2** — investigate connectivity, ensure Ollama stays up
7. **Configure kubectl on admin** — copy kubeconfig from master or set `KUBECONFIG`
8. **Enable token enforcement** — set `NEXUS_TOKEN_ENFORCEMENT=true` after confirming agent ECT budgets
9. **Populate temporal bins** — wire task execution to `assignTask()` calls
10. **Activate mesh networking** — deploy BATMAN-adv + WireGuard from existing scripts
