# NEXUS OS — Architecture Overview

## Layers

### 1. Hardware Layer
Raspberry Pi 5 cluster with AI HAT+ (26 TOPS), managed PoE switch,
OpenWrt router. Each device has a unique Ethereum wallet generated
at first boot.

### 2. Linux Layer
Standard Raspberry Pi OS (Debian bookworm, arm64). The blockchain
does not replace the kernel. Linux handles hardware, I/O, processes.

### 3. Blockchain Layer
Private Ethereum network (Clique PoA, Chain ID 123454321).
- Zero gas fees (private chain)
- On-demand block sealing (blocks only when transactions exist)
- ~100ms confirmation time
- 3 validators
- 20 smart contracts deployed

### 4. Coordination Layer (libnexus)
Python library providing a syscall-like interface to blockchain:
- `kernel.py` — NexusKernel (block queries, contract loading)
- `token_client.py` — ECT/RST operations
- `behavioral_client.py` — Action recording
- `flock_client.py` — Federated learning

### 5. Module Layer
17+ Python modules providing OS services:
- 18-channel behavioral collection
- 288-dim feature extraction (lossy, irreversible)
- Differential privacy (Laplace noise, ε=1.0/day)
- Daily salt rotation (Numerai-style obfuscation)
- Cross-channel correlation discovery
- Temporal bin mapping (actions → 8,760-bin grid)
- Proactive intelligence (focus detection, break suggestions)
- Erasure-coded distributed storage
- Data mining on blockchain history

### 5b. Rust Collector Layer
High-performance behavioral data capture at screen fidelity:
- Built with tokio async runtime, evdev, x11rb, zbus
- Captures at full evdev rate (125-1000 Hz for mouse, all keycodes)
- 18 parallel channel tasks + compound token minter
- Multi-keyboard support including Pi Pico 2 HID microcontrollers
- Framebuffer OCR via Tesseract for pixel-level screen text extraction
- JSON-RPC direct writes to BehavioralActionRegistry on private chain
- Python reads the same contract via web3.py (no IPC needed)

The Rust collector replaces the Python collector for production use.
The Python collector remains as a development/debugging fallback.

### 6. Agent Layer
OS-level services:
- WebSocket gateway (inter-node communication)
- Node agent (heartbeat, registration, resource reporting)
- LLM routing (4-tier inference pipeline)
- Token enforcement (ECT gating on operations)

### 7. Application Layer
Custom GTK4 desktop applications (in nexus-distro repo):
- NEXUS Files, Docs, Messages, Settings, Monitor

## Data Flow: Behavioral Intelligence Pipeline

```
User activity → Rust collector (18 channels, evdev/X11/D-Bus/inotify)
→ on-chain actions (BehavioralActionRegistry via JSON-RPC)
→ compound tokens (5-min aggregates) → feature extraction (288-dim)
→ Laplace noise → daily salt rotation → gradient hash (keccak256)
→ FlockCoordinator submission → federated averaging
```

Raw data stays on the user's private chain permanently.
Only the 32-byte gradient hash reaches the network.

## Token Economy

**ECT (Ephemeral Coordination Tokens):**
Minted daily per node. Spent on operations (behavioral collection,
gradient submission, inference requests). Burned at epoch end.
Purpose: rate-limiting and resource coordination.

**RST (Reputation Stake Tokens):**
Long-term quality signal. Earned by contributing high-quality gradients.
Slashed for low-quality or missing contributions. Determines weight
in federated averaging.

## Privacy Stack (6 Layers)

1. **Architectural isolation** — raw data on private chain, never transmitted
2. **Lossy projection** — 288-dim features from millions of events (~1M:1)
3. **Differential privacy** — Laplace noise, ε=1.0 daily budget
4. **Daily salt rotation** — orthogonal rotation prevents cross-epoch correlation
5. **Gradient hashing** — keccak256 produces irreversible 32-byte output
6. **Verified destruction** — temporary caches destroyed with on-chain proof

## Immutable Lockout

ImmutableOS.sol provides a 90-day countdown after which:
- `admin` is permanently set to `address(0)`
- No smart contracts can be modified
- Token economics are permanently fixed
- Privacy guarantees are cryptographically enforced
- The system is fully autonomous
