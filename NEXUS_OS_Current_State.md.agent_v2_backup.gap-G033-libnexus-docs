# NEXUS OS — Current System State

**Generated:** 2026-02-15 12:45 UTC
**Report Version:** 1.0
**Cluster Uptime:** 17+ hours (hierarchy manager)

---

## 1. Architecture Summary

NEXUS OS is a hybrid blockchain-native operating system running on a 4-node Raspberry Pi 5 cluster. The architecture separates concerns into three planes:

- **Blockchain (Control Plane):** Metadata, permissions, coordination, audit trail
- **IPFS (Data Plane):** Distributed file storage, content addressing, deduplication
- **AI Agents (Operations Plane):** 30 autonomous agents organized in a corporate hierarchy, coordinating via Discord

```
                        ┌──────────────────────────────────────────────┐
                        │              THE ENTERPRISE                  │
                        │           (Discord Guild)                    │
                        │                                              │
                        │   CEO ─┬─ COO                                │
                        │        ├─ Compute Director ─── 3 Workers     │
                        │        ├─ Storage Director ─── 3 Workers     │
                        │        ├─ Network Director ─── 3 Workers     │
                        │        ├─ Security Director ── 3 Workers     │
                        │        ├─ Blockchain Director ─ 3 Workers    │
                        │        ├─ ML Director ───────── 1 Worker     │
                        │        └─ Quantum Director                   │
                        └──────────────────────────────────────────────┘
                                           │
                    ┌──────────────────────┼──────────────────────┐
                    ▼                      ▼                      ▼
          ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
          │  nexus-master   │   │    nexus-ai      │   │  nexus-storage  │
          │  192.168.8.228  │   │  192.168.8.128   │   │  192.168.8.224  │
          │                 │   │                  │   │                 │
          │  Geth Validator │◄─►│  Geth Validator  │◄─►│  Geth Validator │
          │  IPFS Node      │◄─►│  IPFS Node       │◄─►│  IPFS Node      │
          │  256GB NVMe     │   │  AI HAT+ 26TOPS  │   │  1.8TB HDD      │
          └────────┬────────┘   └────────┬─────────┘   └────────┬────────┘
                   │                     │                      │
                   └─────────────────────┼──────────────────────┘
                                         │
                              ┌──────────┴──────────┐
                              │    nexus-admin       │
                              │   192.168.8.153      │
                              │                      │
                              │   IPFS Node          │
                              │   Dev Workstation    │
                              │   Hierarchy Manager  │
                              │   Pi 500             │
                              └─────────────────────┘
```

---

## 2. Hardware Configuration

### Cluster Nodes

| Node | IP | Hardware | RAM | Storage | Roles |
|------|----|----------|-----|---------|-------|
| **nexus-master** | 192.168.8.228 | Raspberry Pi 5 | 8 GB | 256 GB NVMe SSD | Geth validator, IPFS node |
| **nexus-ai** | 192.168.8.128 | Raspberry Pi 5 | 8 GB | 128 GB SD | Geth validator, IPFS node, AI HAT+ (26 TOPS) |
| **nexus-storage** | 192.168.8.224 | Raspberry Pi 5 | 4 GB | 128 GB SD + 1.8 TB HDD | Geth validator, IPFS node, primary storage |
| **nexus-admin** | 192.168.8.153 | Raspberry Pi 500 | 8 GB | 32 GB SD | IPFS node, dev workstation, hierarchy manager |

**Total:** 4 nodes, 28 GB RAM, 2.3 TB raw storage
**Kernel:** Linux 6.12.62+rpt-rpi-2712 (aarch64)

### Current Resource Usage

| Node | CPU Load | RAM Used | Disk Used | Disk Free |
|------|----------|----------|-----------|-----------|
| nexus-master | 0.02 | 1,292 / 8,058 MB (16%) | 10 / 235 GB (5%) | 216 GB |
| nexus-ai | 0.00 | 810 / 8,062 MB (10%) | 11 / 117 GB (10%) | 102 GB |
| nexus-storage | 0.00 | 961 / 4,045 MB (24%) | 9 / 117 GB (9%) | 103 GB + 1.8 TB |
| nexus-admin | 0.60 | 5,880 / 8,058 MB (73%) | 10 / 29 GB (36%) | 18 GB |

---

## 3. Blockchain Layer

### Network Configuration

| Parameter | Value |
|-----------|-------|
| Chain ID | 123454321 |
| Consensus | Clique Proof of Authority |
| Block period | 0 (on-demand sealing) |
| Gas limit | 30,000,000 |
| Validators | 3 (nexus-master, nexus-ai, nexus-storage) |
| Network type | Private (isolated from public Ethereum) |
| Geth version | 1.13.15-stable |
| Gas price | 0 (free transactions) |

### Live Metrics

| Metric | Value |
|--------|-------|
| Current block height | **48** (reset with period=0 migration) |
| Mean confirmation | ~102ms (3-validator PoA) |
| Empty blocks/day | 0 (on-demand sealing) |
| Peer connectivity | 2/2 on all validators |
| Deployer balance | ~999.99 ETH |

### Chaindata Size

| Node | Chaindata | Notes |
|------|-----------|-------|
| nexus-master | 287 MB | Lower — recent chaindata rebuild from test |
| nexus-ai | 845 MB | Full archive since genesis |
| nexus-storage | 845 MB | Full archive since genesis |

### Block Time Migration (Completed)

Migrated from `period=5` to `period=0` (on-demand sealing) via clean slate reinit:

| Metric | Before (period=5) | After (period=0) |
|--------|-------------------|-------------------|
| Mean confirmation | 14,204 ms | **~102 ms** |
| Throughput | ~0.07 tx/s effective | **~10 tx/s** |
| Empty blocks/day | 17,280 (100%) | **0** |
| Disk growth/day (idle) | ~1,279 MB | **0 MB** |

**Status:** Deployed. 19 ReasoningLedger entries re-imported from backup. All 3 contracts redeployed.

### Deployed Smart Contracts

| # | Contract | Address | Purpose | State |
|---|----------|---------|---------|-------|
| 1 | **ReasoningLedger** | `0x0317451264E1de1A0696A81f6141e72E58686DE4` | AI agent decision audit trail | 19 entries |
| 2 | **ResourceManager** | `0x7E7f5e6cd9d7d485eeFa4Ec3Fb211705A3A8c6C6` | Cluster resource allocation | Operational |
| 3 | **StorageRegistry** | `0x859e30a6b752Af6D96d309Dc3a5bECfCfFDe31A6` | Distributed storage metadata | Operational |

#### ReasoningLedger Functions
- `logReasoning(decision, reasoning)` → entryId
- `getEntry(entryId)` → (agent, timestamp, decision, reasoning, hash)
- `getEntryCount()` → count
- `getAgentHistory(agent)` → entryId[]

#### StorageRegistry Functions
- `registerFile(cid, merkleRoot, fileSize, numChunks)` → fileId
- `assignChunks(fileId, chunkIndices, storageNodes[][])` → event
- `submitStorageProof(fileId, chunkIndex, proof)` → valid
- `getFileMetadata(fileId)` → FileMetadata
- `getChunkAssignments(fileId)` → ChunkAssignment[]
- `getUserFiles(owner)` → fileId[]
- `getStorageCommitment(node)` → bytes

---

## 4. IPFS Layer

### Network Configuration

| Parameter | Value |
|-----------|-------|
| IPFS version | Kubo 0.32.1 |
| Network type | **Private** (swarm.key protected) |
| Bootstrap peers | 4 (cluster nodes only) |
| Public IPFS connections | **0** (fully isolated) |
| MDNS discovery | Disabled |
| Auto relay | Disabled |
| Connection limits | Low=20, High=40 (low-power profile) |

### Per-Node IPFS Status

| Node | Objects | Repo Size | Max Capacity | Peers |
|------|---------|-----------|-------------|-------|
| nexus-master | 214 | 51.8 MB | 200 GB | 3 |
| nexus-ai | 10 | 1.1 MB | 200 GB | 3 |
| nexus-storage | 219 | 51.8 MB | 800 GB | 3 |
| nexus-admin | 216 | 52.4 MB | 15 GB | 3 |

### Peer Connectivity Matrix

| From \ To | master | ai | storage | admin |
|-----------|:---:|:---:|:---:|:---:|
| **master** | — | Y | Y | Y |
| **ai** | Y | — | Y | Y |
| **storage** | Y | Y | — | Y |
| **admin** | Y | Y | Y | — |

### IPFS Peer IDs

| Node | Peer ID |
|------|---------|
| nexus-master | `12D3KooWFmWdJWuYt5RLW89qWT3MjNnBbSEw7hKQpGUuMSbXzgFx` |
| nexus-ai | `12D3KooWFj5VeXvu6Aagr9ehpL3qsmtNBxTzzwkJSaYubauhEGzX` |
| nexus-storage | `12D3KooWPjmi4v4yEx8WX1Qs3z4xzJoWPqJkkQZ13Khu2q61VmsX` |
| nexus-admin | `12D3KooWLfCQcQTVDcKUREMoyJzFoNvSRqsjPFMT3KE9FwixUMEk` |

### Measured Performance

| Operation | Speed |
|-----------|-------|
| Add 1 MB file | 123 ms |
| Retrieve 1 MB (cross-node) | 263–336 ms |
| Add 50 MB file | 2,423 ms (~20 MB/s) |
| Retrieve 50 MB (cross-node) | 1,474–4,114 ms (~12–33 MB/s) |
| Chunk size | 256 KB |
| 50 MB file chunks | 203 blocks |

---

## 5. AI Agent Hierarchy

### Overview

| Level | Count | LLM Model | ECT Budget |
|-------|-------|-----------|------------|
| C-Suite (CEO, COO) | 2 | Qwen/Qwen2.5-7B-Instruct | 100 |
| Directors | 7 | meta-llama/Llama-3.2-3B-Instruct | 50 |
| Workers | 21 | meta-llama/Llama-3.2-1B-Instruct | 30 |
| **Total** | **30** | | |

### Agent Roster

| Department | Director | Workers |
|------------|----------|---------|
| **C-Suite** | CEO, COO | — |
| **Compute** | Compute Director | Process Scheduler, Load Balancer, Resource Monitor |
| **Storage** | Storage Director | Backup Agent, Cache Manager, FLock Federator |
| **Network** | Network Director | Mesh Coordinator, VPN Manager, DNS Agent |
| **Security** | Security Director | Auth Agent, Anomaly Detector, Audit Logger |
| **Blockchain** | Blockchain Director | Contract Deployer, Token Manager, Consensus Monitor |
| **ML** | ML Director | Training Coordinator |
| **Quantum** | Quantum Director | — |

### Discord Integration

| Metric | Value |
|--------|-------|
| Guild | "The Enterprise" (ID: 1441732155225931869) |
| Active bot tokens | 25 |
| Webhook fallback | 5 |
| Hierarchy manager | Running (PID 29575, uptime 17h+) |
| Channel categories | 11 |
| Total channels | 34+ |

### Blockchain Integration

Every AI agent decision is:
1. Processed through the agent's LLM
2. SHA-256 hashed (reasoning chain)
3. Logged to ReasoningLedger on-chain
4. Recorded in local JSONL decision logs
5. Displayed in Discord with tx hash in embed footer

**21 on-chain decision entries** logged to date.

---

## 6. Storage Architecture

### Data Flow

```
Upload:
  File → Split into 256KB chunks → IPFS add → CID
    └→ StorageRegistry.registerFile(CID, merkleRoot, size, chunks)
    └→ StorageRegistry.assignChunks(fileId, indices, nodes[][])
    └→ Blockchain stores metadata ONLY (CID, Merkle root, node assignments)
    └→ IPFS distributes actual data across cluster

Download:
  fileId → StorageRegistry.getFileMetadata() → CID
    └→ IPFS cat/get(CID) → parallel retrieval from multiple nodes
    └→ Verify against Merkle root
    └→ Return reassembled file
```

### Design Principle

> **Blockchain stores metadata. IPFS stores data.** This separation ensures fast blockchain operations (small tx), scalable storage (IPFS handles GB-scale files), content deduplication, and cryptographic integrity verification.

### Storage Capacity

| Node | Role | IPFS Allocation | Available Disk |
|------|------|-----------------|---------------|
| nexus-master | Validator + Store | 200 GB | 216 GB |
| nexus-ai | Validator + Store | 200 GB | 102 GB |
| nexus-storage | **Primary Storage** | 800 GB | 1.8 TB (HDD) + 103 GB (SD) |
| nexus-admin | Dev + Store | 15 GB | 18 GB |
| **Total** | | **1.215 TB** | **~2.2 TB raw** |

---

## 7. Services & Processes

### systemd Services

| Service | nexus-master | nexus-ai | nexus-storage | nexus-admin |
|---------|:---:|:---:|:---:|:---:|
| `nexus-geth` | active | active | active | N/A |
| `ipfs` | active | active | active | active |

### Per-Process Resource Usage

| Process | Node | CPU | Memory |
|---------|------|-----|--------|
| Geth | nexus-master | 0.9% | 124 MB |
| Geth | nexus-ai | 0.6% | 133 MB |
| Geth | nexus-storage | 0.8% | 137 MB |
| IPFS | nexus-master | 0.2% | 64 MB |
| IPFS | nexus-ai | 0.2% | 56 MB |
| IPFS | nexus-storage | 0.2% | 61 MB |
| IPFS | nexus-admin | 0.1% | 56 MB |
| Hierarchy Manager | nexus-admin | 0.0% | 137 MB |

**Total cluster process overhead:** ~5% CPU, ~768 MB RAM across 4 nodes.

---

## 8. Network Topology

### Port Map

| Port | Protocol | Purpose |
|------|----------|---------|
| 30303 | TCP/UDP | Geth P2P (blockchain sync) |
| 8545 | TCP | Geth HTTP RPC |
| 4001 | TCP | IPFS Swarm (file transfer) |
| 5001 | TCP | IPFS API |
| 8080 | TCP | IPFS Gateway |
| 22 | TCP | SSH (cluster management) |

### Network Addresses

```
192.168.8.0/24 (Private LAN)
├── 192.168.8.228  nexus-master
├── 192.168.8.128  nexus-ai
├── 192.168.8.224  nexus-storage
└── 192.168.8.153  nexus-admin

10.42.x.0/24 (WireGuard VPN overlay, also active)
├── 10.42.0.x  nexus-master
├── 10.42.1.x  nexus-ai
└── 10.42.3.x  nexus-storage
```

---

## 9. File System Layout

```
/opt/nexus/
├── agents/
│   ├── hierarchy_manager.py      # 30-agent orchestrator
│   ├── ceo_bot.py                # Standalone CEO bot
│   ├── agent_registry.py         # Agent definitions (30 agents)
│   ├── agent_workflow.py         # LLM-based decision workflow
│   ├── blockchain_logger.py      # On-chain decision logging
│   ├── llm_client.py             # HuggingFace inference client
│   ├── .env                      # Bot tokens (25 active + 5 webhook)
│   ├── verify_system.py          # 5-point health check
│   ├── test_delegation.py        # CEO→Director→Worker chain test
│   └── logs/
│       ├── hierarchy.log         # Bot connection/message logs
│       └── decisions/            # Per-agent JSONL decision logs
│
├── blockchain/                   # On validator nodes
│   ├── genesis.json              # Active genesis (period=0)
│   ├── genesis-fast.json         # Optimized genesis (period=0)
│   ├── genesis-original-backup.json
│   ├── geth/                     # Chaindata
│   ├── keystore/                 # Wallet keystore
│   └── password.txt              # Wallet password
│
├── contracts/
│   ├── source/
│   │   ├── ReasoningLedger.sol
│   │   ├── ResourceManager.sol
│   │   └── StorageRegistry.sol
│   ├── deployed/
│   │   ├── ReasoningLedger.json  # ABI + address
│   │   ├── ResourceManager.json
│   │   └── StorageRegistry.json
│   ├── scripts/
│   │   ├── deploy.py
│   │   ├── deploy_storage_registry.py
│   │   └── test_storage_registry.py
│   └── .venv/                    # Python virtualenv (web3, solcx, etc.)
│
├── ipfs/                         # IPFS data directory
│   ├── config                    # IPFS node config
│   ├── swarm.key                 # Private network key
│   └── datastore/                # Block storage
│
├── scripts/
│   ├── install-ipfs-cluster.sh
│   ├── setup-ipfs-private.sh
│   ├── test-ipfs-distribution.sh
│   └── verify-fast-blocks.py
│
└── NEXUS_OS_Current_State.md     # This file
```

---

## 10. What Works Now

### Operational (Verified)

- [x] Private Ethereum blockchain (Clique PoA, 3 validators, synced)
- [x] 3 smart contracts deployed and functional
- [x] AI agent decision logging to blockchain (21 entries)
- [x] 30-agent hierarchy running on Discord (25 bots + 5 webhooks)
- [x] CEO → Director → Worker delegation chain (tested end-to-end)
- [x] IPFS private cluster (4 nodes, full mesh, swarm.key protected)
- [x] Distributed file storage with content addressing
- [x] Cross-node file replication (add on any node, retrieve from any)
- [x] Pin management and garbage collection
- [x] StorageRegistry: file registration, chunk assignment, storage proofs
- [x] systemd services for Geth and IPFS (auto-start on boot)
- [x] Zero gas fees (private chain)
- [x] Comprehensive test suites for all components

### Tested But Not Deployed

- [x] Period=0 on-demand sealing (~102ms confirmation, ~10 tx/s)

### Planned / In Progress

- [x] Cluster-wide block time migration (period=5 → period=0)
- [ ] Erasure coding for storage redundancy
- [ ] `libnexus` Python library (unified API for storage operations)
- [ ] End-to-end encrypted file upload/download pipeline
- [ ] AI agent integration with StorageRegistry
- [ ] Storage proof verification (Merkle proofs)
- [ ] Automated replication policies
- [ ] IPFS cluster pinning service

---

## 11. Key Credentials & Configuration

| Item | Location |
|------|----------|
| Deployer wallet | `0x817B0842B208B76A7665948F8D1A0592F9b1e958` (unlocked on Geth) |
| Wallet keystore | `/opt/nexus/blockchain/keystore/` |
| Wallet password | `/opt/nexus/blockchain/password.txt` |
| Bot tokens | `/opt/nexus/agents/.env` |
| IPFS swarm key | `/opt/nexus/ipfs/swarm.key` |
| Contract ABIs | `/opt/nexus/contracts/deployed/*.json` |
| Python venv | `/opt/nexus/contracts/.venv/` |
| Geth service | `/etc/systemd/system/nexus-geth.service` |
| IPFS service | `/etc/systemd/system/ipfs.service` |

---

## 12. Operational Commands

### Quick Health Check
```bash
# Blockchain
/opt/nexus/contracts/.venv/bin/python3 /opt/nexus/scripts/verify-fast-blocks.py

# Agents
/opt/nexus/contracts/.venv/bin/python3 /opt/nexus/agents/verify_system.py

# IPFS
bash /opt/nexus/scripts/test-ipfs-distribution.sh
```

### Start/Stop Services
```bash
# Geth (on validators)
sudo systemctl start|stop|restart nexus-geth

# IPFS (on all nodes)
sudo systemctl start|stop|restart ipfs

# Hierarchy manager
cd /opt/nexus/agents
nohup /opt/nexus/contracts/.venv/bin/python3 hierarchy_manager.py >> logs/hierarchy.log 2>&1 &
```

### Deploy a Contract
```bash
cd /opt/nexus/contracts
solcjs --abi --bin source/ContractName.sol
.venv/bin/python3 scripts/deploy.py
```

---

*End of NEXUS OS Status Report*
