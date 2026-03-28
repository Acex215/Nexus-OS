# NEXUS OS

**Blockchain-coordinated distributed platform for Raspberry Pi**

A Linux distribution built on Raspberry Pi OS (Debian bookworm) where
every device is a cryptographic wallet, every operation is blockchain-
coordinated, and privacy is mathematical — not policy.

*Your Data. Your Hardware. Your Rules.*

## What NEXUS OS Is

NEXUS OS adds a blockchain coordination layer to standard Linux:

- **Private Ethereum network** (Clique PoA) — immutable audit trails,
  token economics, resource management. Zero gas, on-demand sealing,
  ~100ms confirmation.
- **20 smart contracts** — TokenManager, TemporalScheduler, StorageRegistry,
  ReasoningLedger, ResourceManager, FlockCoordinator, ConsentManager,
  ImmutableOS, BehavioralActionRegistry, and more.
- **Dual-token economy** (ECT/RST) — Execution Credit Tokens for daily
  compute budgets, Reputation Staking Tokens for quality scoring.
  Real on-chain mint/spend/earn/slash.
- **Temporal binning** — 8,760 hourly bins per year as a universal
  scheduling abstraction for both system processes and user tasks.
- **Distributed storage** — Reed-Solomon erasure coding with AES-256
  per-file encryption, IPFS content-addressing, blockchain metadata.
- **Device identity** — every Pi generates an Ethereum wallet at first boot.
  Node registration and heartbeating happen on-chain.
- **Federated learning** — FlockCoordinator manages gradient submissions,
  epoch cycles, and contribution scoring. Privacy-preserving by design.
- **Mesh networking** — BLE + WiFi Direct discovery with sub-GHz
  fallback via Flipper Zero integration.
- **Immutable lockout** — admin keys permanently burned after deployment.
  No one (including the creator) can modify contracts post-lockout.

## What's Deployed (block 1,839+)

- Private Ethereum chain: 3 validators (Clique PoA, period=0)
- 20 Solidity contracts compiled and deployed
- 11 contracts with live on-chain addresses
- Dual-token economy with real ECT/RST transactions
- Temporal scheduler with hourly bin assignment
- Federated learning coordinator with epoch management
- On-chain consent management (opt-in/opt-out)
- Flashable desktop OS image via pi-gen (arm64 bookworm)
- Patent filed March 6, 2026 (provisional)

## Quick Start

1. Flash the NEXUS OS image with Raspberry Pi Imager
2. Boot — first-boot wizard generates your device wallet
3. Your device is now a NEXUS node on the private chain

## Hardware

Reference deployment: 3x Raspberry Pi 5 (8GB), 1x Pi 500,
AI HAT+ (26 TOPS), managed PoE switch, OpenWrt router.
Runs on any Pi 4/5 hardware.

## Repository Structure

    libnexus/        Core Python library (blockchain, storage, tokens, federation)
    contracts/       20 Solidity smart contracts (source + deployed ABIs)
    modules/         Subsystem modules (erasure coding, mining, forecasting, privacy)
    agents/          Node agent, WebSocket gateway, LLM routing, token enforcement
    scripts/         Operational scripts (first boot, daily cycles, deployment)
    networking/      Mesh discovery, RF daemon, Flipper bridge, WireGuard
    config/          Configuration templates
    image/           pi-gen OS image builder (stage5-nexus custom stage)
    models/          ML model definitions (behavioral sequence, autoencoder)
    docs/            Token economics, LLM hierarchy, credential rotation
    services/        Systemd service definitions

## Architecture

The blockchain does NOT replace the Linux kernel. Linux handles hardware,
I/O, and process scheduling. The blockchain provides:

- **Coordination** — resource allocation, task assignment, node identity
- **Audit** — every significant operation logged immutably on-chain
- **Economics** — token-gated compute access prevents resource abuse
- **Privacy** — consent management, daily salt rotation, federated learning
  with differential privacy guarantees
- **Storage metadata** — file CIDs, Merkle roots, chunk assignments on-chain;
  actual data on IPFS

## Smart Contracts

| Contract | Purpose |
|----------|---------|
| TokenManager | ECT/RST dual-token economy |
| TemporalScheduler | 8,760-bin temporal grid |
| ReasoningLedger | Immutable AI decision audit trail |
| ResourceManager | Node registration + resource tracking |
| StorageRegistry | Distributed file metadata |
| FlockCoordinator | Federated learning epoch management |
| BehavioralActionRegistry | On-chain behavioral event recording |
| ConsentManager | Privacy consent management |
| ImmutableOS | Admin lockout (90-day countdown) |
| DecisionQuality | AI agent quality scoring |
| TournamentManager | Prediction tournament coordination |

## License

Patent pending (provisional filed March 6, 2026).
Source available. License terms TBD after nonprovisional filing.

## Links

- V2 Network: [venture-verse.org](https://venture-verse.org)
