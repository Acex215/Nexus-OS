# GETH INITIALIZATION EXTRACTION
## From Web3 Pi to NEXUS OS Blockchain Kernel

> **Extraction Session**: January 2, 2026
> **Component**: Geth (Go Ethereum) Initialization
> **Source**: Web3 Pi + NEXUS OS Project Knowledge
> **Target**: NEXUS OS `/opt/nexus/blockchain/`

---

## 📋 WHAT WE'RE EXTRACTING

**Purpose**: Initialize Geth as the **NEXUS OS kernel** (not just a blockchain node)

**Key Files:**
1. `deploy-geth.sh` - Main deployment script
2. `genesis.json` - Genesis block configuration (the "boot sector")
3. `password.txt` - Account password file
4. `account creation` - Ethereum wallet generation
5. `systemd service` - Geth as system service

**Transformation:**
- Web3 Pi: Geth runs as Ethereum node (application layer)
- NEXUS OS: Geth runs as kernel (system layer)

---

## 🔍 STEP 1: UNDERSTAND THE SOURCE CODE

### From Project Knowledge: `scripts/blockchain/deploy-geth.sh`

This is the ACTUAL code from NEXUS OS project (which was inspired by Web3 Pi):

```bash
#!/bin/bash
# NEXUS OS - Deploy Ethereum Geth Node
# Phase 3: Blockchain Infrastructure

set -e

GREEN='\033[0;32m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[Blockchain]${NC} $1"
}

BLOCKCHAIN_DIR="/opt/nexus/blockchain"
DATA_DIR="${BLOCKCHAIN_DIR}/data"
KEYSTORE_DIR="${BLOCKCHAIN_DIR}/keystore"

install_geth() {
    log "Installing Geth..."

    # Install dependencies
    apt-get update
    apt-get install -y software-properties-common

    # Add Ethereum PPA
    add-apt-repository -y ppa:ethereum/ethereum
    apt-get update
    apt-get install -y ethereum

    log "Geth installed: $(geth version)"
}

create_genesis() {
    log "Creating genesis block..."

    mkdir -p "${BLOCKCHAIN_DIR}"

    cat > "${BLOCKCHAIN_DIR}/genesis.json" <<'EOF'
{
  "config": {
    "chainId": 1337,
    "homesteadBlock": 0,
    "eip150Block": 0,
    "eip155Block": 0,
    "eip158Block": 0,
    "byzantiumBlock": 0,
    "constantinopleBlock": 0,
    "petersburgBlock": 0,
    "istanbulBlock": 0,
    "berlinBlock": 0,
    "londonBlock": 0,
    "clique": {
      "period": 5,
      "epoch": 30000
    }
  },
  "difficulty": "1",
  "gasLimit": "8000000",
  "extradata": "0x0000000000000000000000000000000000000000000000000000000000000000YOUR_SIGNER_ADDRESS0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
  "alloc": {
    "0x0000000000000000000000000000000000000001": {
      "balance": "1000000000000000000000000"
    }
  }
}
EOF

    log "Genesis block created"
}

create_account() {
    log "Creating Ethereum account..."

    mkdir -p "${KEYSTORE_DIR}"

    # Create account with password
    echo "nexus-blockchain-password" > "${BLOCKCHAIN_DIR}/password.txt"
    chmod 600 "${BLOCKCHAIN_DIR}/password.txt"

    geth account new \
        --keystore "${KEYSTORE_DIR}" \
        --password "${BLOCKCHAIN_DIR}/password.txt"

    # Get the created address
    SIGNER_ADDRESS=$(geth account list --keystore "${KEYSTORE_DIR}" | grep -oP '(?<={)[^}]+' | head -1)

    log "Account created: 0x${SIGNER_ADDRESS}"

    # Update genesis with signer address
    sed -i "s/YOUR_SIGNER_ADDRESS/${SIGNER_ADDRESS}/g" "${BLOCKCHAIN_DIR}/genesis.json"
}

init_blockchain() {
    log "Initializing blockchain..."

    mkdir -p "${DATA_DIR}"

    geth init \
        --datadir "${DATA_DIR}" \
        "${BLOCKCHAIN_DIR}/genesis.json"

    log "Blockchain initialized"
}

create_systemd_service() {
    log "Creating systemd service..."

    cat > /etc/systemd/system/nexus-geth.service <<EOF
[Unit]
Description=NEXUS OS Geth Node
After=network.target

[Service]
Type=simple
User=nexus
WorkingDirectory=${BLOCKCHAIN_DIR}
ExecStart=/usr/bin/geth \\
    --datadir ${DATA_DIR} \\
    --networkid 1337 \\
    --http \\
    --http.addr 0.0.0.0 \\
    --http.port 8545 \\
    --http.api eth,net,web3,personal,admin,miner \\
    --http.corsdomain "*" \\
    --ws \\
    --ws.addr 0.0.0.0 \\
    --ws.port 8546 \\
    --ws.api eth,net,web3,personal,admin,miner \\
    --allow-insecure-unlock \\
    --unlock 0x${SIGNER_ADDRESS} \\
    --password ${BLOCKCHAIN_DIR}/password.txt \\
    --mine \\
    --miner.etherbase 0x${SIGNER_ADDRESS} \\
    --miner.threads 1
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable nexus-geth

    log "Systemd service created"
}

start_node() {
    log "Starting Geth node..."

    systemctl start nexus-geth

    sleep 5

    if systemctl is-active --quiet nexus-geth; then
        log "Geth node is running"
    else
        log "Failed to start Geth node"
        journalctl -u nexus-geth -n 50
        exit 1
    fi
}

configure_firewall() {
    log "Configuring firewall..."

    ufw allow 8545/tcp  # HTTP RPC
    ufw allow 8546/tcp  # WebSocket
    ufw allow 30303/tcp # P2P
    ufw allow 30303/udp # P2P

    log "Firewall configured"
}

test_connection() {
    log "Testing connection..."

    sleep 5

    # Test RPC
    curl -X POST -H "Content-Type: application/json" \
        --data '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' \
        http://localhost:8545

    log "Connection test complete"
}

save_config() {
    log "Saving configuration..."

    cat > "${BLOCKCHAIN_DIR}/config.json" <<EOF
{
  "rpc_url": "http://$(hostname -I | awk '{print $1}'):8545",
  "ws_url": "ws://$(hostname -I | awk '{print $1}'):8546",
  "chain_id": 1337,
  "signer_address": "0x${SIGNER_ADDRESS}",
  "data_dir": "${DATA_DIR}",
  "keystore_dir": "${KEYSTORE_DIR}"
}
EOF

    log "Configuration saved to ${BLOCKCHAIN_DIR}/config.json"
}

main() {
    log "Deploying NEXUS OS Blockchain Node..."

    install_geth
    create_genesis
    create_account
    init_blockchain
    create_systemd_service
    configure_firewall
    start_node
    test_connection
    save_config

    log "Blockchain deployment complete!"
    log ""
    log "RPC URL: http://$(hostname -I | awk '{print $1}'):8545"
    log "WebSocket URL: ws://$(hostname -I | awk '{print $1}'):8546"
    log "Signer Address: 0x${SIGNER_ADDRESS}"
    log ""
    log "View logs: journalctl -u nexus-geth -f"
    log "Stop node: systemctl stop nexus-geth"
    log "Start node: systemctl start nexus-geth"
}

main "$@"
```

---

## 📝 STEP 2: ANALYZE THE CODE

### Code Breakdown (Line by Line):

**1. Installation (`install_geth`)**
```bash
add-apt-repository -y ppa:ethereum/ethereum
apt-get install -y ethereum
```
- Uses official Ethereum PPA
- Installs latest stable Geth
- Alternative: Build from source for latest features

**2. Genesis Block (`create_genesis`)**
```json
{
  "chainId": 1337,          // Private network ID
  "clique": {
    "period": 5,            // New block every 5 seconds = scheduler tick!
    "epoch": 30000
  },
  "gasLimit": "8000000",    // Max gas per block
  "alloc": {                // Pre-allocated funds
    "0x...": {"balance": "1000000000000000000000000"}
  }
}
```

**Key NEXUS OS Modification:**
- Change `chainId` from `1337` → `123454321` (NEXUS OS network)
- `period: 5` seconds = **kernel scheduler tick rate**
- Pre-allocate **multiple device wallets** (one per Pi)

**3. Account Creation (`create_account`)**
```bash
geth account new \
    --keystore "${KEYSTORE_DIR}" \
    --password "${BLOCKCHAIN_DIR}/password.txt"
```
- Creates Ethereum wallet (private/public key pair)
- Stores in keystore directory
- Protected by password file

**NEXUS OS Modification:**
- Create **one account PER DEVICE** (3 accounts for 3x Pi 5)
- Store device wallet address in `/opt/nexus/device_wallet.txt`
- Use hardware secure element (Flipper Zero) for key storage

**4. Blockchain Initialization (`init_blockchain`)**
```bash
geth init \
    --datadir "${DATA_DIR}" \
    "${BLOCKCHAIN_DIR}/genesis.json"
```
- Creates blockchain database
- Inserts genesis block (Block 0)
- Sets up state trie

**5. Systemd Service (`create_systemd_service`)**
```bash
ExecStart=/usr/bin/geth \
    --datadir ${DATA_DIR} \
    --networkid 1337 \
    --http --http.port=8545 \      # JSON-RPC API
    --mine \                        # Start mining
    --miner.threads 1 \            # CPU threads for mining
    --unlock 0x${SIGNER_ADDRESS}   # Auto-unlock account
```

**NEXUS OS KEY CHANGES:**
```diff
- --networkid 1337
+ --networkid 123454321

- --miner.threads 1
+ --miner.threads 2  # Use 2 cores on Pi 5

# ADD these flags:
+ --syncmode full \
+ --gcmode archive \    # Keep full history for audit trail
+ --maxpeers 3 \        # Only connect to other Pi nodes
+ --nodiscover \        # Private network, no peer discovery
+ --bootnodes enode://DEVICE1@IP1,enode://DEVICE2@IP2  # Hardcode cluster nodes
```

---

## 🎯 STEP 3: MODIFICATIONS FOR NEXUS OS

### Change #1: Genesis Block for NEXUS OS

**Original (Web3 Pi style):**
```json
{
  "chainId": 1337,
  "alloc": {
    "0x0000000000000000000000000000000000000001": {
      "balance": "1000000000000000000000000"
    }
  }
}
```

**NEXUS OS Version:**
```json
{
  "config": {
    "chainId": 123454321,
    "clique": {
      "period": 5,
      "epoch": 30000
    }
  },
  "difficulty": "1",
  "gasLimit": "8000000",
  "extradata": "0x0000000000000000000000000000000000000000000000000000000000000000PI5_DEVICE1_ADDRESSPI5_DEVICE2_ADDRESSPI5_DEVICE3_ADDRESS00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
  "alloc": {
    "PI5_DEVICE1_ADDRESS": {"balance": "1000000000000000000000"},
    "PI5_DEVICE2_ADDRESS": {"balance": "1000000000000000000000"},
    "PI5_DEVICE3_ADDRESS": {"balance": "1000000000000000000000"},
    "PIZERO_MONITOR_ADDRESS": {"balance": "100000000000000000000"},
    "PI500_GATEWAY_ADDRESS": {"balance": "100000000000000000000"}
  }
}
```

**What Changed:**
- Chain ID: `123454321` (NEXUS OS private network)
- `extradata`: All 3 Pi 5 devices as validators (Proof of Authority)
- `alloc`: Pre-fund all 5 device wallets
- Pi 5 nodes get 1000 ETH, support devices get 100 ETH

---

### Change #2: Multi-Device Account Creation

**Original:**
```bash
create_account() {
    geth account new \
        --keystore "${KEYSTORE_DIR}" \
        --password "${BLOCKCHAIN_DIR}/password.txt"
}
```

**NEXUS OS Version:**
```bash
create_cluster_accounts() {
    log "Creating device wallet for THIS device..."

    # Get device ID from hostname or MAC address
    DEVICE_ID=$(hostname)

    # Create account for THIS device
    echo "nexus-${DEVICE_ID}-password-CHANGE-THIS" > "${BLOCKCHAIN_DIR}/password.txt"
    chmod 600 "${BLOCKCHAIN_DIR}/password.txt"

    geth account new \
        --keystore "${KEYSTORE_DIR}" \
        --password "${BLOCKCHAIN_DIR}/password.txt"

    # Extract address
    DEVICE_WALLET=$(geth account list --keystore "${KEYSTORE_DIR}" | grep -oP '(?<={)[^}]+' | head -1)

    # Save device wallet
    echo "0x${DEVICE_WALLET}" > /opt/nexus/device_wallet.txt

    log "Device wallet created: 0x${DEVICE_WALLET}"
    log "Saved to: /opt/nexus/device_wallet.txt"

    # Export for other scripts
    export DEVICE_WALLET="0x${DEVICE_WALLET}"
}
```

**What Changed:**
- Creates ONE wallet per device (not one per cluster)
- Saves to `/opt/nexus/device_wallet.txt` for other services to use
- Each device creates its own wallet on first boot

---

### Change #3: Systemd Service as "Kernel"

**Original:**
```ini
[Unit]
Description=NEXUS OS Geth Node
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/geth --datadir ...
```

**NEXUS OS Version:**
```ini
[Unit]
Description=NEXUS OS Blockchain Kernel
After=network.target
Before=nexus-dns.service nexus-proxy.service nexus-agents.service
Wants=nexus-dns.service nexus-proxy.service

[Service]
Type=notify  # Changed from 'simple' to 'notify'
ExecStart=/usr/bin/geth \
    --datadir /data/nexus-chain \
    --networkid 123454321 \
    --http \
    --http.addr 0.0.0.0 \
    --http.port 8545 \
    --http.api eth,net,web3,personal,admin,miner,debug,txpool \
    --ws \
    --ws.addr 0.0.0.0 \
    --ws.port 8546 \
    --mine \
    --miner.threads 2 \
    --miner.etherbase $(cat /opt/nexus/device_wallet.txt) \
    --unlock $(cat /opt/nexus/device_wallet.txt) \
    --password /opt/nexus/blockchain/password.txt \
    --syncmode full \
    --gcmode archive \
    --maxpeers 3 \
    --nodiscover \
    --bootnodes enode://DEVICE1@192.168.1.101:30303,enode://DEVICE2@192.168.1.102:30303,enode://DEVICE3@192.168.1.103:30303

# Kernel-like properties
Restart=always
RestartSec=5
KillMode=process
KillSignal=SIGTERM
TimeoutStopSec=300

# Resource limits
LimitNOFILE=65536
LimitNPROC=512

[Install]
WantedBy=multi-user.target
```

**What Changed:**
- `Type=notify` (kernel service)
- `Before=` other services (Geth starts FIRST)
- `--syncmode full --gcmode archive` (keep full history)
- `--maxpeers 3 --nodiscover` (private cluster only)
- `--bootnodes` hardcoded to other Pi nodes
- Resource limits for stability

---

## 📦 STEP 4: FILES TO COPY

### Directory Structure:

```
/opt/nexus/blockchain/
├── deploy-geth.sh          # Main deployment script (COPY & MODIFY)
├── genesis.template.json   # Genesis block template (COPY & MODIFY)
├── password.txt            # Generated during deployment
├── config.json            # Generated during deployment
├── data/                  # Blockchain database (created by geth init)
│   └── geth/
│       ├── chaindata/
│       ├── lightchaindata/
│       └── nodes/
└── keystore/              # Ethereum accounts (created by geth account new)
    └── UTC--2026-01-02T...--<address>
```

### Files to Create:

**1. `/opt/nexus/blockchain/deploy-geth.sh`**
```bash
# Copy the entire script from STEP 1
# Then apply modifications from STEP 3
```

**2. `/opt/nexus/blockchain/genesis.template.json`**
```json
# Copy the NEXUS OS version from Change #1
```

**3. `/etc/systemd/system/nexus-geth.service`**
```ini
# Copy the NEXUS OS version from Change #3
```

---

## 🧪 STEP 5: TESTING PROCEDURE

### Test 1: Installation

```bash
# On Pi 5 #1
cd /opt/nexus/blockchain
sudo bash deploy-geth.sh

# Expected output:
[Blockchain] Installing Geth...
[Blockchain] Geth installed: Version: 1.13.X
[Blockchain] Creating genesis block...
[Blockchain] Genesis block created
[Blockchain] Creating Ethereum account...
[Blockchain] Account created: 0x...
[Blockchain] Initializing blockchain...
[Blockchain] Blockchain initialized
[Blockchain] Creating systemd service...
[Blockchain] Systemd service created
[Blockchain] Configuring firewall...
[Blockchain] Firewall configured
[Blockchain] Starting Geth node...
[Blockchain] Geth node is running
[Blockchain] Testing connection...
{"jsonrpc":"2.0","id":1,"result":"0x0"}
[Blockchain] Connection test complete
[Blockchain] Blockchain deployment complete!

RPC URL: http://192.168.1.101:8545
WebSocket URL: ws://192.168.1.101:8546
Signer Address: 0x...
```

### Test 2: Verify Blockchain Running

```bash
# Check systemd status
sudo systemctl status nexus-geth

# Should show:
● nexus-geth.service - NEXUS OS Blockchain Kernel
     Loaded: loaded
     Active: active (running)
```

### Test 3: Connect with Geth Console

```bash
# Attach to running node
geth attach http://localhost:8545

# In console:
> eth.blockNumber
5  # Should be incrementing every 5 seconds

> eth.mining
true

> eth.accounts
["0x..."]  # Your device wallet

> eth.getBalance(eth.accounts[0])
1000000000000000000000  # 1000 ETH in wei

> admin.peers
[]  # Empty for now (other nodes not connected yet)
```

### Test 4: Deploy on All 3 Nodes

```bash
# On Pi 5 #2
cd /opt/nexus/blockchain
sudo bash deploy-geth.sh

# On Pi 5 #3
cd /opt/nexus/blockchain
sudo bash deploy-geth.sh

# Wait 30 seconds for peer discovery

# On Pi 5 #1, check peers:
geth attach http://localhost:8545
> admin.peers
[
  {
    "id": "...",
    "name": "Geth/v1.13.X",
    "network": {
      "localAddress": "192.168.1.101:30303",
      "remoteAddress": "192.168.1.102:30303"
    }
  },
  {
    "id": "...",
    "name": "Geth/v1.13.X",
    "network": {
      "localAddress": "192.168.1.101:30303",
      "remoteAddress": "192.168.1.103:30303"
    }
  }
]
# Should show 2 peers!
```

---

## ✅ STEP 6: VERIFY SUCCESS

### Success Criteria:

✅ **Geth Installed**
```bash
geth version
# Shows: Version: 1.13.X-stable
```

✅ **Genesis Block Created**
```bash
cat /opt/nexus/blockchain/genesis.json
# Shows chainId: 123454321
```

✅ **Account Created**
```bash
cat /opt/nexus/device_wallet.txt
# Shows: 0x...
```

✅ **Blockchain Initialized**
```bash
ls /opt/nexus/blockchain/data/geth/chaindata/
# Shows database files
```

✅ **Service Running**
```bash
systemctl is-active nexus-geth
# Shows: active
```

✅ **RPC Working**
```bash
curl -X POST -H "Content-Type: application/json" \
  --data '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' \
  http://localhost:8545
# Returns: {"jsonrpc":"2.0","id":1,"result":"0x..."}
```

✅ **Peers Connected**
```bash
geth attach --exec "admin.peers.length" http://localhost:8545
# Returns: 2 (for 3-node cluster)
```

✅ **Mining Active**
```bash
geth attach --exec "eth.mining" http://localhost:8545
# Returns: true
```

✅ **Blocks Incrementing**
```bash
# Check twice with 10 second gap
geth attach --exec "eth.blockNumber" http://localhost:8545
sleep 10
geth attach --exec "eth.blockNumber" http://localhost:8545
# Second number should be ~2 higher (5 sec block time)
```

---

## 🚨 TROUBLESHOOTING

### Problem: Geth won't start

**Check logs:**
```bash
journalctl -u nexus-geth -n 100 --no-pager
```

**Common issues:**
- Account not unlocked → Check password.txt exists
- Port already in use → `sudo lsof -i :8545`
- Firewall blocking → `sudo ufw status`

### Problem: No peers connecting

**Check:**
```bash
# Verify nodes can ping each other
ping 192.168.1.102

# Check firewall
sudo ufw allow 30303

# Check bootnodes configuration
grep bootnodes /etc/systemd/system/nexus-geth.service
```

### Problem: Mining not working

**Check:**
```bash
geth attach --exec "eth.mining" http://localhost:8545
# If false:
geth attach --exec "miner.start()" http://localhost:8545
```

---

## 🎯 NEXT STEPS

Once Geth is running successfully:

1. **Deploy Smart Contracts** (Week 3-4)
   - ReasoningLedger.sol
   - ResourceManager.sol
   - etc.

2. **Create Web3 API Wrapper** (Week 10)
   - Python library for system calls
   - C library (libnexus.so) for compatibility

3. **Integrate with AI Agents** (Week 10)
   - Agents call contracts via Web3.py
   - Blockchain coordinates agent tasks

---

## 📚 REFERENCES

- Geth Official Docs: https://geth.ethereum.org/docs
- Private Networks: https://geth.ethereum.org/docs/fundamentals/private-network
- Clique PoA: https://geth.ethereum.org/docs/tools/clef/clique-signing
- NEXUS_WEB3PI_ANALYSIS.md (your analysis document)

---

**Status**: ✅ READY TO EXTRACT

**Next Command**:
```bash
cd /opt/nexus/blockchain
sudo bash deploy-geth.sh
```

---

*Generated: January 2, 2026*
*Extraction Session with Claude (Sonnet 4.5)*
*For: NEXUS OS Blockchain Kernel Deployment*
