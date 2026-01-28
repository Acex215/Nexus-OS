# NEXUS OS - Blockchain Operating System

![Version](https://img.shields.io/badge/version-0.2.0-blue)
![Status](https://img.shields.io/badge/status-development-yellow)
![License](https://img.shields.io/badge/license-MIT-green)

> **An operating system built on blockchain infrastructure**
>
> NEXUS OS transforms Ethereum's Geth into a kernel-level component, enabling blockchain-based system calls, distributed computation, and AI agent coordination across Raspberry Pi clusters.

---

## Quick Start

### Option 1: Installation Package (Recommended)

Download and install on an existing Raspberry Pi OS:

```bash
# On your build machine
git clone https://github.com/Acex215/Nexus-OS.git
cd Nexus-OS
make package

# Copy to Raspberry Pi
scp deploy/nexus-os-*.tar.gz pi@raspberrypi:~/

# On the Raspberry Pi
tar xzf nexus-os-*.tar.gz
cd nexus-os-*
sudo ./install.sh
sudo reboot
```

### Option 2: Direct Installation

```bash
# Clone directly on Raspberry Pi
git clone https://github.com/Acex215/Nexus-OS.git
cd Nexus-OS
sudo ./install.sh
sudo reboot
```

### Option 3: Build Custom SD Card Image

```bash
# Build with Docker (recommended)
./build.sh docker

# Or build natively (requires root and pi-gen dependencies)
sudo ./build.sh full

# Image will be in: deploy/
```

---

## Project Vision

NEXUS OS reimagines the traditional operating system by placing blockchain at its core. Instead of Geth running as an application on top of Linux, **Geth becomes the kernel** - handling process coordination, resource allocation, and inter-process communication through smart contracts.

### Key Innovations

- **Blockchain-as-Kernel**: Geth runs as a systemd service with kernel-like properties
- **Smart Contract System Calls**: System operations execute as blockchain transactions
- **Distributed Computation**: Multi-node Raspberry Pi cluster shares workload via blockchain
- **AI Agent Coordination**: AI agents interact through on-chain reasoning ledgers
- **Immutable Audit Trail**: All system operations recorded on-chain for forensics

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   NEXUS OS STACK                        │
├─────────────────────────────────────────────────────────┤
│  Applications & AI Agents                               │
│  ├─ Claude, GPT-4, Llama (via Ollama)                  │
│  └─ Custom distributed applications                     │
├─────────────────────────────────────────────────────────┤
│  System Services                                        │
│  ├─ nexus-dns.service                                  │
│  ├─ nexus-proxy.service                                │
│  └─ nexus-agents.service                               │
├─────────────────────────────────────────────────────────┤
│  Blockchain Kernel (Geth)                               │
│  ├─ Smart Contracts (ReasoningLedger, ResourceManager) │
│  ├─ Web3 API (JSON-RPC, WebSocket)                     │
│  └─ Consensus Layer (Clique PoA)                       │
├─────────────────────────────────────────────────────────┤
│  Linux Base (Debian/Ubuntu on Raspberry Pi)            │
└─────────────────────────────────────────────────────────┘
```

---

## Repository Structure

```
Nexus-OS/
├── build.sh                    # Main build script
├── install.sh                  # Installation script
├── Makefile                    # Build automation
├── build/                      # Build configuration
│   └── config                  # pi-gen configuration
├── scripts/                    # Runtime scripts
│   ├── run-setup.sh            # Setup orchestrator
│   ├── run-first-boot.sh       # First-boot orchestrator
│   ├── pre-start-geth.sh       # Geth pre-start checks
│   └── blockchain/             # Blockchain scripts
│       ├── deploy-geth.sh      # Full Geth deployment
│       ├── create_genesis_block.sh    # Multi-node genesis
│       ├── generate_device_wallets.sh # Wallet generation
│       └── genesis.template.json      # Genesis template
├── setup.d/                    # Installation-time scripts
│   ├── 10_blockchain           # Blockchain setup
│   └── 20_networking           # Network setup
├── first-run.d/                # First-boot scripts
│   ├── 05_cluster_discovery    # Auto-detect cluster
│   └── 10_configure_vlans      # VLAN configuration
├── systemd/                    # Systemd services
│   ├── nexus-geth.service      # Blockchain kernel service
│   ├── nexus-setup.service     # Setup service
│   └── nexus-first-run.service # First-boot service
├── core/                       # Python framework
│   └── service_framework.py    # Service base classes
├── network/                    # Network management
│   └── vlan_manager.py         # VLAN management
├── backup/                     # Backup utilities
│   └── blockchain_backup.py    # Blockchain backup/restore
└── docs/                       # Documentation
    ├── GENESIS_BLOCK_GUIDE.md
    └── extraction/             # Extraction guides
```

---

## Build System

### Prerequisites

**For building packages:**
- Git, Make
- Any Linux/macOS system

**For building SD card images:**
- Docker (recommended), or
- Debian/Ubuntu with pi-gen dependencies

### Available Build Commands

```bash
# Show help
make help

# Create installation package (tar.gz)
make package

# Build SD card image with Docker
./build.sh docker

# Build SD card image natively (requires root)
sudo ./build.sh full

# Run syntax tests
make test

# Clean build artifacts
make clean
```

### Build Outputs

| Command | Output | Description |
|---------|--------|-------------|
| `make package` | `deploy/nexus-os-YYYYMMDD.tar.gz` | Installation package |
| `./build.sh docker` | `deploy/nexus-os.img.xz` | Flashable SD card image |
| `./build.sh lite` | `deploy/nexus-os-installer.tar.gz` | Lightweight installer |

---

## Installation

### Hardware Requirements

- **Recommended**: Raspberry Pi 5 (8GB RAM)
- **Minimum**: Raspberry Pi 4 (4GB RAM)
- **Storage**: 32GB+ SD card or SSD (64GB+ recommended)
- **Network**: Ethernet (WiFi not recommended for blockchain)

### Software Requirements

- Raspberry Pi OS Lite (64-bit) - Bookworm or newer
- Or Ubuntu Server 22.04 LTS for ARM64

### Installation Methods

#### Method 1: Package Installation

```bash
# Extract package
tar xzf nexus-os-*.tar.gz
cd nexus-os-*

# Run installer
sudo ./install.sh

# Reboot to complete setup
sudo reboot
```

#### Method 2: Flash Pre-built Image

```bash
# Flash to SD card (Linux/macOS)
xz -d nexus-os.img.xz
sudo dd if=nexus-os.img of=/dev/sdX bs=4M status=progress

# Or use Raspberry Pi Imager
```

#### Method 3: Manual Installation

```bash
# Clone repository
git clone https://github.com/Acex215/Nexus-OS.git
cd Nexus-OS

# Install
sudo ./install.sh

# Reboot
sudo reboot
```

### Post-Installation

After first boot, NEXUS OS will automatically:
1. Generate a device wallet
2. Scan for existing cluster nodes
3. Initialize or join the blockchain network
4. Start the Geth blockchain kernel

Verify installation:

```bash
# Check service status
sudo systemctl status nexus-geth

# View logs
sudo journalctl -u nexus-geth -f

# Attach to Geth console
geth attach http://localhost:8545

# Check block number (should increment every 5 seconds)
> eth.blockNumber
```

---

## Multi-Node Cluster Setup

### Step 1: Install NEXUS OS on All Nodes

Install on each Raspberry Pi using any method above.

### Step 2: Generate Wallets on Each Node

```bash
# On each Pi
/opt/nexus/scripts/blockchain/generate_device_wallets.sh
```

Save the wallet addresses displayed.

### Step 3: Create Shared Genesis Block

On the first node:

```bash
/opt/nexus/scripts/blockchain/create_genesis_block.sh
```

Enter the wallet addresses from all nodes when prompted.

### Step 4: Distribute Genesis Block

```bash
# Copy genesis.json to all other nodes
scp /opt/nexus/blockchain/genesis.json pi@node2:/opt/nexus/blockchain/
scp /opt/nexus/blockchain/genesis.json pi@node3:/opt/nexus/blockchain/
```

### Step 5: Initialize All Nodes

On each node:

```bash
sudo geth init \
    --datadir /opt/nexus/blockchain/data \
    /opt/nexus/blockchain/genesis.json

sudo systemctl restart nexus-geth
```

### Step 6: Verify Cluster

```bash
# Check peer connections
geth attach --exec "admin.peers.length" http://localhost:8545
# Should return number of connected peers

# Check sync status
geth attach --exec "eth.syncing" http://localhost:8545
# Should return 'false' when synced
```

---

## Configuration

### Main Configuration File

`/etc/nexus/nexus.conf`:

```bash
# Network Configuration
NEXUS_CHAIN_ID=123454321
NEXUS_NETWORK_ID=123454321
NEXUS_BLOCK_PERIOD=5

# Node Configuration
NEXUS_DATA_DIR=/opt/nexus/blockchain/data
NEXUS_KEYSTORE_DIR=/opt/nexus/blockchain/keystore

# RPC Configuration
NEXUS_RPC_PORT=8545
NEXUS_WS_PORT=8546
NEXUS_P2P_PORT=30303
```

### Network Ports

| Port | Protocol | Description |
|------|----------|-------------|
| 8545 | TCP | HTTP JSON-RPC API |
| 8546 | TCP | WebSocket API |
| 30303 | TCP+UDP | P2P Discovery |

### Directory Structure

| Path | Description |
|------|-------------|
| `/opt/nexus/` | NEXUS OS root |
| `/opt/nexus/blockchain/data/` | Blockchain database |
| `/opt/nexus/blockchain/keystore/` | Wallet keys |
| `/opt/nexus/device_wallet.txt` | This node's wallet address |
| `/etc/nexus/nexus.conf` | Configuration |
| `/var/log/nexus-*.log` | Log files |

---

## Troubleshooting

### Geth Won't Start

```bash
# Check service status and logs
sudo systemctl status nexus-geth
sudo journalctl -u nexus-geth -n 100 --no-pager

# Common issues:
# - Port in use: sudo lsof -i :8545
# - Account locked: check /opt/nexus/blockchain/password.txt
# - Firewall: sudo ufw status
```

### No Peer Connections

```bash
# Check network connectivity
ping <other-node-ip>

# Verify firewall
sudo ufw allow 30303

# Get enode URL to share
geth attach --exec "admin.nodeInfo.enode" http://localhost:8545

# Add peer manually
geth attach --exec "admin.addPeer('enode://...')" http://localhost:8545
```

### Blockchain Not Mining

```bash
# Check mining status
geth attach --exec "eth.mining" http://localhost:8545

# Start mining
geth attach --exec "miner.start()" http://localhost:8545

# Check if account is unlocked
geth attach --exec "personal.listWallets" http://localhost:8545
```

---

## Development Roadmap

### Phase 1: Blockchain Infrastructure - COMPLETE
- [x] Geth installation and configuration
- [x] Genesis block creation
- [x] Device wallet generation
- [x] Systemd service setup
- [x] Build system and installer
- [x] Multi-node cluster support

### Phase 2: Smart Contracts (In Progress)
- [ ] ReasoningLedger.sol - AI reasoning storage
- [ ] ResourceManager.sol - CPU/memory allocation
- [ ] ProcessCoordinator.sol - Inter-process communication
- [ ] ContractRegistry.sol - Service discovery

### Phase 3: System Integration
- [ ] Web3.py wrapper library
- [ ] C library (libnexus.so) for system calls
- [ ] DNS service integration

### Phase 4: AI Agents
- [ ] Agent runtime environment
- [ ] Multi-agent coordination via blockchain
- [ ] Distributed reasoning engine

---

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Run tests (`make test`)
4. Commit your changes
5. Push and open a Pull Request

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

- **Ethereum Foundation** - For Geth (Go Ethereum)
- **Web3 Pi Project** - Inspiration for blockchain on Raspberry Pi
- **FreedomBox** - Service framework patterns
- **RaspAP** - Networking patterns
- **Raspberry Pi Foundation** - Hardware platform

---

*Built with blockchain, powered by AI, running on Raspberry Pi*

**NEXUS OS** - Where distributed systems meet intelligent coordination
