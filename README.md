# NEXUS OS - Blockchain Operating System

![Version](https://img.shields.io/badge/version-0.1.0-blue)
![Status](https://img.shields.io/badge/status-development-yellow)
![License](https://img.shields.io/badge/license-MIT-green)

> **An operating system built on blockchain infrastructure**
>
> NEXUS OS transforms Ethereum's Geth into a kernel-level component, enabling blockchain-based system calls, distributed computation, and AI agent coordination across Raspberry Pi clusters.

---

## 🎯 Project Vision

NEXUS OS reimagines the traditional operating system by placing blockchain at its core. Instead of Geth running as an application on top of Linux, **Geth becomes the kernel** - handling process coordination, resource allocation, and inter-process communication through smart contracts.

### Key Innovations

- **Blockchain-as-Kernel**: Geth runs as a systemd service with kernel-like properties
- **Smart Contract System Calls**: System operations execute as blockchain transactions
- **Distributed Computation**: Multi-node Raspberry Pi cluster shares workload via blockchain
- **AI Agent Coordination**: AI agents interact through on-chain reasoning ledgers
- **Immutable Audit Trail**: All system operations recorded on-chain for forensics

---

## 🏗️ Architecture

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

## 📦 Repository Structure

```
Nexus-OS/
├── docs/                           # Documentation
│   └── extraction/                 # Component extraction guides
│       └── GETH_INITIALIZATION_EXTRACTION.md
├── scripts/                        # Deployment scripts
│   └── blockchain/                 # Blockchain initialization
│       ├── deploy-geth.sh          # Main deployment script
│       └── genesis.template.json   # Genesis block template
├── systemd/                        # Systemd service templates
│   └── nexus-geth.service.template # Blockchain kernel service
└── README.md                       # This file
```

---

## 🚀 Quick Start

### Prerequisites

- **Hardware**: Raspberry Pi 5 (8GB RAM recommended)
- **OS**: Ubuntu 22.04 LTS or Debian 12
- **Storage**: 64GB+ SD card or SSD
- **Network**: Ethernet connection (WiFi not recommended for blockchain)

### Installation

```bash
# Clone the repository
git clone https://github.com/Acex215/Nexus-OS.git
cd Nexus-OS

# Run the Geth deployment script
sudo bash scripts/blockchain/deploy-geth.sh
```

The script will:
1. Install Geth (Go Ethereum)
2. Create a genesis block with NEXUS OS chain ID (123454321)
3. Generate a device wallet for this Pi
4. Initialize the blockchain database
5. Create and start the `nexus-geth` systemd service
6. Configure firewall rules
7. Test the RPC connection

### Verification

```bash
# Check Geth is running
sudo systemctl status nexus-geth

# Attach to Geth console
geth attach http://localhost:8545

# In the Geth console, check block number
> eth.blockNumber
5  # Should increment every 5 seconds

# Check your device wallet
> eth.accounts
["0x..."]

# Exit console
> exit
```

---

## 🔧 Configuration

### Network Configuration

NEXUS OS uses a private Ethereum network:

- **Chain ID**: 123454321
- **Network ID**: 123454321
- **Consensus**: Clique (Proof of Authority)
- **Block Time**: 5 seconds
- **Gas Limit**: 8,000,000

### Ports

- **8545**: HTTP JSON-RPC API
- **8546**: WebSocket API
- **30303**: P2P (TCP + UDP)

### Files & Directories

- `/opt/nexus/blockchain/` - Blockchain root directory
- `/opt/nexus/blockchain/data/` - Blockchain database
- `/opt/nexus/blockchain/keystore/` - Ethereum accounts
- `/opt/nexus/device_wallet.txt` - This device's wallet address
- `/opt/nexus/blockchain/config.json` - Network configuration

---

## 📚 Documentation

### Extraction Guides

NEXUS OS is built by extracting and adapting components from various sources:

- **[Geth Initialization Extraction](docs/extraction/GETH_INITIALIZATION_EXTRACTION.md)** - How Geth was transformed from a blockchain node into the NEXUS OS kernel

### Planned Documentation

- Smart Contract Deployment (Week 3-4)
- AI Agent Integration (Week 10)
- Multi-Node Cluster Setup
- Web3 API Usage Guide
- Security & Hardening

---

## 🛠️ Development Roadmap

### Phase 1: Blockchain Infrastructure ✅ (Current)
- [x] Geth installation and configuration
- [x] Genesis block creation
- [x] Device wallet generation
- [x] Systemd service setup
- [ ] Multi-node cluster networking

### Phase 2: Smart Contracts (Week 3-4)
- [ ] ReasoningLedger.sol - AI reasoning storage
- [ ] ResourceManager.sol - CPU/memory allocation
- [ ] ProcessCoordinator.sol - Inter-process communication
- [ ] ContractRegistry.sol - Service discovery

### Phase 3: System Integration (Week 10)
- [ ] Web3.py wrapper library
- [ ] C library (libnexus.so) for system calls
- [ ] Kernel module for direct blockchain integration
- [ ] DNS service integration

### Phase 4: AI Agents (Week 10+)
- [ ] Agent runtime environment
- [ ] Multi-agent coordination via blockchain
- [ ] Distributed reasoning engine
- [ ] Agent-to-agent communication protocol

### Phase 5: Applications (Future)
- [ ] Blockchain-based file system
- [ ] Distributed task scheduler
- [ ] On-chain package manager
- [ ] Forensics and audit tools

---

## 🧪 Testing

### Single Node Test

```bash
# Check Geth version
geth version

# Test RPC endpoint
curl -X POST -H "Content-Type: application/json" \
  --data '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' \
  http://localhost:8545

# Attach and check mining
geth attach http://localhost:8545
> eth.mining
true
```

### Multi-Node Cluster Test

1. Deploy NEXUS OS on 3x Raspberry Pi 5
2. Configure bootnodes with each device's enode URL
3. Verify peer connections: `admin.peers.length` should return 2

See [GETH_INITIALIZATION_EXTRACTION.md](docs/extraction/GETH_INITIALIZATION_EXTRACTION.md) for detailed testing procedures.

---

## 🐛 Troubleshooting

### Geth Won't Start

```bash
# Check logs
journalctl -u nexus-geth -n 100 --no-pager

# Common issues:
# - Port 8545 already in use: sudo lsof -i :8545
# - Account not unlocked: check /opt/nexus/blockchain/password.txt
# - Firewall blocking: sudo ufw status
```

### No Peer Connections

```bash
# Verify network connectivity
ping <other-pi-ip>

# Check P2P port
sudo ufw allow 30303

# Verify bootnodes in service file
grep bootnodes /etc/systemd/system/nexus-geth.service
```

### Mining Not Working

```bash
# Check mining status
geth attach --exec "eth.mining" http://localhost:8545

# Start mining if stopped
geth attach --exec "miner.start()" http://localhost:8545
```

---

## 🤝 Contributing

NEXUS OS is in active development. Contributions are welcome!

### How to Contribute

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Guidelines

- Follow the extraction methodology (document source → analyze → adapt → test)
- Include comprehensive documentation for new components
- Test on Raspberry Pi hardware before submitting PRs
- Use the issue tracker for bugs and feature requests

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **Ethereum Foundation** - For Geth (Go Ethereum)
- **Web3 Pi Project** - Inspiration for blockchain on Raspberry Pi
- **Raspberry Pi Foundation** - For amazing hardware
- **Claude (Anthropic)** - AI assistance in development and extraction sessions

---

## 📞 Contact

- **GitHub**: [@Acex215](https://github.com/Acex215)
- **Project**: [Nexus-OS](https://github.com/Acex215/Nexus-OS)
- **Issues**: [Issue Tracker](https://github.com/Acex215/Nexus-OS/issues)

---

## 🌟 Star History

If you find this project interesting, please consider giving it a star!

---

*Built with blockchain, powered by AI, running on Raspberry Pi*

**NEXUS OS** - Where distributed systems meet intelligent coordination
