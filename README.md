<div align="center">

# NEXUS OS

**Blockchain-Coordinated Distributed Platform for Raspberry Pi**

*Your Data. Your Hardware. Your Rules.*

[![CI](https://github.com/Acex215/Nexus-OS/actions/workflows/test.yml/badge.svg)](https://github.com/Acex215/Nexus-OS/actions)
[![Patent](https://img.shields.io/badge/Patent-Pending-blue)](https://venture-verse.org)
[![Chain](https://img.shields.io/badge/Blockchain-Live-green)]()
[![Contracts](https://img.shields.io/badge/Smart_Contracts-20-orange)]()

</div>

---

NEXUS OS is a Linux distribution built on Raspberry Pi OS (Debian bookworm)
that adds a blockchain coordination layer to every device. Every Pi is an
Ethereum wallet. Every operation has a blockchain receipt. Privacy is
enforced by mathematics, not promises.

## The Problem

Using any internet-connected device means surrendering behavioral data to
corporations. Users generate enormous value through their patterns but
receive none of that value and have no control over how it is used.
Federated learning partially addresses this but lacks economic incentives
and verifiable data lifecycle management.

## The Solution

NEXUS OS keeps all data on the user's own hardware, coordinated by a
private Ethereum blockchain with zero gas fees and ~100ms confirmation.
A dual-token economy (ECT/RST) governs resource allocation. Federated
learning enables collective intelligence without raw data ever leaving
any device. An immutable lockout mechanism ensures that after deployment,
no one — including the creator — can modify the system's guarantees.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    NEXUS OS Stack                        │
├─────────────────────────────────────────────────────────┤
│  Applications    │ Custom apps, NEXUS Monitor, Settings │
│  AI Agents       │ Node agent, gateway, LLM routing     │
│  Modules         │ Collection, extraction, privacy,     │
│                  │ mining, erasure coding, forecasting   │
│  libnexus        │ Kernel interface, token client,      │
│                  │ behavioral client, flock client       │
│  Smart Contracts │ 20 Solidity contracts on-chain        │
│  Blockchain      │ Private Ethereum (Clique PoA)         │
│  Linux           │ Raspberry Pi OS (Debian bookworm)     │
│  Hardware        │ Raspberry Pi 5 / Pi 500 cluster       │
└─────────────────────────────────────────────────────────┘
```

The blockchain does **not** replace the Linux kernel. Linux handles
hardware, I/O, and process scheduling. The blockchain provides
coordination, audit, economics, and privacy enforcement.

## Smart Contracts

| Contract | Purpose |
|----------|---------|
| **TokenManager** | ECT/RST dual-token economy (mint, spend, earn, slash) |
| **TemporalScheduler** | 8,760 hourly bins — universal scheduling abstraction |
| **ReasoningLedger** | Immutable audit trail for all agent decisions |
| **ResourceManager** | Node registration and resource tracking |
| **StorageRegistry** | Distributed file metadata (IPFS + blockchain) |
| **FlockCoordinator** | Federated learning epoch management |
| **BehavioralActionRegistry** | On-chain behavioral event recording |
| **ConsentManager** | Privacy consent management (opt-in/opt-out) |
| **DecisionQuality** | Agent quality scoring → RST adjustment |
| **TournamentManager** | Prediction tournament coordination |
| **ImmutableOS** | Admin lockout (permanent, irreversible) |
| ComputeLoadBalancer | Resource auctioning between nodes |
| MLWeightValidator | Gradient verification for federated learning |
| NetworkObscuration | Obfuscated dataset Merkle roots |
| ServiceRegistry | Service discovery and registration |
| MeshRegistry | Mesh network peer management |
| PidRegistry | Process identity tracking |
| AccessLogger | Access event logging |
| NexusPublicToken | Future public token (not yet active) |

## What's Running

- Private Ethereum chain: 3 validators, 1,800+ blocks, on-demand sealing
- 11 deployed contracts with live on-chain addresses
- Dual-token economy with real ECT/RST transactions
- Temporal scheduler with hourly bin assignment
- Federated learning coordinator with epoch management
- 18-channel behavioral intelligence collection
- Consent-gated data pipeline with on-chain proof of destruction
- Flashable desktop OS image via pi-gen (arm64 bookworm)

## Quick Start

1. Flash the NEXUS OS image with [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Boot — the first-boot wizard generates your device wallet
3. Your device is now a NEXUS node

## Hardware

**Reference deployment:**

| Device | Role |
|--------|------|
| 3x Raspberry Pi 5 (8GB) | Validators, inference, storage |
| 1x Pi 500 | Gateway, development |
| AI HAT+ (26 TOPS) | On-device ML inference |
| TP-Link TL-SG2008P | Managed PoE switch |
| GL.iNet BE9300 | OpenWrt router |

Minimum: any single Raspberry Pi 4 or 5 with 4GB+ RAM.

## Repository Structure

```
libnexus/           Core Python library
├── kernel.py           Blockchain interface (NexusKernel)
├── token_client.py     ECT/RST token operations
├── behavioral_client.py  Behavioral action recording
├── flock_client.py     Federated learning client
└── ...
contracts/          Smart contracts
├── source/             20 Solidity source files
├── deployed/           ABIs + live addresses
└── scripts/            Deployment scripts
modules/            Subsystem modules
├── channels/           18 behavioral collection channels
├── collector.py        Master collection orchestrator
├── local_insight.py    User-facing behavioral analytics
└── ...
models/             ML models
├── behavioral_sequence_model.py  TCN meta-model
agents/             OS-level agents
├── nexus_gateway.py    WebSocket gateway
├── node_agent.py       Node heartbeat + registration
├── token_hooks.py      ECT/RST enforcement
└── llm_client.py       LLM inference routing
scripts/            Operational scripts
networking/         Mesh discovery, RF, WireGuard
image/              pi-gen OS image builder
docs/               Architecture, economics, credentials
```

## Key Innovations

**Temporal Binning** — 8,760 hourly bins per year as a universal
abstraction. The same data structure handles OS process scheduling,
user calendar events, and behavioral pattern analysis.

**Behavioral Action Ledger** — Every micro-action (keystrokes, clicks,
URLs, system state) recorded as a blockchain transaction. Compound
tokens aggregate 5-minute behavioral patterns into single on-chain
entities for correlation analysis.

**Privacy by Architecture** — Raw data stays on-device. Only
irreversible gradient hashes reach the network. 6-layer privacy stack:
architectural isolation, lossy projection (1M:1 compression),
Laplace noise, daily salt rotation, gradient hashing, on-chain
destruction verification.

**Immutable Lockout** — After deployment, `ImmutableOS.finalizeLock()`
permanently sets `admin = address(0)`. No party can modify contracts,
token economics, or privacy guarantees. The system is autonomous.

## Documentation

- [Token Economics](docs/TOKEN_ECONOMICS.md)
- [Credential Rotation](docs/CREDENTIAL_ROTATION.md)
- [LLM Hierarchy](docs/LLM_HIERARCHY.md)
- [AI HAT Setup](docs/AI_HAT_SETUP.md)

## Status

**Patent pending** — Provisional filed March 6, 2026. Nonprovisional
due by March 6, 2027.

**Academic target** — OSDI/SOSP 2027.

## License

Source available under patent-pending terms. See [LICENSE](LICENSE).

## Links

- **V2 Network:** [venture-verse.org](https://venture-verse.org)
- **GitHub:** [Acex215/Nexus-OS](https://github.com/Acex215/Nexus-OS)
