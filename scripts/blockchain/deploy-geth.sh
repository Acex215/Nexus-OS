#!/bin/bash
# NEXUS OS - Deploy Ethereum Geth Blockchain Kernel
# Extraction from Web3 Pi → NEXUS OS Blockchain Kernel
# Phase 3: Blockchain Infrastructure

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[NEXUS Blockchain]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# NEXUS OS specific directories
BLOCKCHAIN_DIR="/opt/nexus/blockchain"
DATA_DIR="${BLOCKCHAIN_DIR}/data"
KEYSTORE_DIR="${BLOCKCHAIN_DIR}/keystore"
DEVICE_WALLET_FILE="/opt/nexus/device_wallet.txt"

# NEXUS OS network configuration
NEXUS_CHAIN_ID=123454321
NEXUS_NETWORK_ID=123454321

install_geth() {
    log "Installing Geth (Go Ethereum)..."

    # Install dependencies
    apt-get update
    apt-get install -y software-properties-common curl jq

    # Add Ethereum PPA
    add-apt-repository -y ppa:ethereum/ethereum
    apt-get update
    apt-get install -y ethereum

    GETH_VERSION=$(geth version | grep "Version:" | awk '{print $2}')
    log "Geth installed: ${GETH_VERSION}"
}

create_genesis() {
    log "Creating NEXUS OS genesis block (blockchain boot sector)..."

    mkdir -p "${BLOCKCHAIN_DIR}"

    # Create genesis template (will be updated with actual addresses)
    cat > "${BLOCKCHAIN_DIR}/genesis.template.json" <<'EOF'
{
  "config": {
    "chainId": 123454321,
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
      "balance": "1000000000000000000000"
    }
  }
}
EOF

    log "Genesis template created (chainId: ${NEXUS_CHAIN_ID})"
    log "Block period: 5 seconds (kernel scheduler tick rate)"
}

create_cluster_accounts() {
    log "Creating device wallet for THIS NEXUS OS device..."

    mkdir -p "${KEYSTORE_DIR}"

    # Get device ID from hostname or generate unique ID
    DEVICE_ID=$(hostname)

    # Create secure password file
    # WARNING: This is a placeholder - should be replaced with hardware secure element
    DEVICE_PASSWORD="nexus-${DEVICE_ID}-$(openssl rand -hex 16)"
    echo "${DEVICE_PASSWORD}" > "${BLOCKCHAIN_DIR}/password.txt"
    chmod 600 "${BLOCKCHAIN_DIR}/password.txt"

    warn "Password stored in ${BLOCKCHAIN_DIR}/password.txt"
    warn "In production, use hardware secure element (Flipper Zero, TPM, etc.)"

    # Create Ethereum account for this device
    geth account new \
        --keystore "${KEYSTORE_DIR}" \
        --password "${BLOCKCHAIN_DIR}/password.txt"

    # Extract the created address
    DEVICE_WALLET=$(geth account list --keystore "${KEYSTORE_DIR}" | grep -oP '(?<={)[^}]+' | head -1)

    if [ -z "${DEVICE_WALLET}" ]; then
        error "Failed to create device wallet"
        exit 1
    fi

    # Save device wallet address (used by other NEXUS OS services)
    echo "0x${DEVICE_WALLET}" > "${DEVICE_WALLET_FILE}"
    chmod 644 "${DEVICE_WALLET_FILE}"

    log "Device wallet created: 0x${DEVICE_WALLET}"
    log "Wallet address saved to: ${DEVICE_WALLET_FILE}"

    # Update genesis with signer address
    cp "${BLOCKCHAIN_DIR}/genesis.template.json" "${BLOCKCHAIN_DIR}/genesis.json"
    sed -i "s/YOUR_SIGNER_ADDRESS/${DEVICE_WALLET}/g" "${BLOCKCHAIN_DIR}/genesis.json"

    # Export for systemd service
    export SIGNER_ADDRESS="${DEVICE_WALLET}"

    log "Genesis block updated with device wallet as validator"
}

init_blockchain() {
    log "Initializing NEXUS OS blockchain kernel..."

    mkdir -p "${DATA_DIR}"

    # Initialize blockchain with genesis block
    geth init \
        --datadir "${DATA_DIR}" \
        "${BLOCKCHAIN_DIR}/genesis.json"

    log "Blockchain database initialized"
    log "Genesis block (Block 0) inserted"
}

create_systemd_service() {
    log "Creating NEXUS OS blockchain kernel systemd service..."

    # Read device wallet address
    if [ ! -f "${DEVICE_WALLET_FILE}" ]; then
        error "Device wallet file not found: ${DEVICE_WALLET_FILE}"
        exit 1
    fi

    DEVICE_WALLET_ADDR=$(cat "${DEVICE_WALLET_FILE}")

    # Create systemd service with kernel-like properties
    cat > /etc/systemd/system/nexus-geth.service <<EOF
[Unit]
Description=NEXUS OS Blockchain Kernel
Documentation=https://github.com/Acex215/Nexus-OS
After=network-online.target
Wants=network-online.target
Before=nexus-dns.service nexus-proxy.service nexus-agents.service

[Service]
Type=notify
User=root
WorkingDirectory=${BLOCKCHAIN_DIR}

# Main Geth process
ExecStart=/usr/bin/geth \\
    --datadir ${DATA_DIR} \\
    --networkid ${NEXUS_NETWORK_ID} \\
    --http \\
    --http.addr 0.0.0.0 \\
    --http.port 8545 \\
    --http.api eth,net,web3,personal,admin,miner,debug,txpool \\
    --http.corsdomain "*" \\
    --ws \\
    --ws.addr 0.0.0.0 \\
    --ws.port 8546 \\
    --ws.api eth,net,web3,personal,admin,miner,debug,txpool \\
    --allow-insecure-unlock \\
    --unlock ${DEVICE_WALLET_ADDR} \\
    --password ${BLOCKCHAIN_DIR}/password.txt \\
    --mine \\
    --miner.etherbase ${DEVICE_WALLET_ADDR} \\
    --miner.threads 2 \\
    --syncmode full \\
    --gcmode archive \\
    --maxpeers 5 \\
    --nodiscover \\
    --verbosity 3

# Kernel-like properties
Restart=always
RestartSec=5
KillMode=process
KillSignal=SIGTERM
TimeoutStopSec=300

# Resource limits
LimitNOFILE=65536
LimitNPROC=512
LimitMEMLOCK=infinity

# Security hardening
NoNewPrivileges=false
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

    # Reload systemd and enable service
    systemctl daemon-reload
    systemctl enable nexus-geth

    log "Systemd service created and enabled"
    log "Service will start on boot"
}

configure_firewall() {
    log "Configuring firewall for blockchain communication..."

    # Check if ufw is installed
    if ! command -v ufw &> /dev/null; then
        warn "UFW not installed, skipping firewall configuration"
        return
    fi

    # Allow blockchain ports
    ufw allow 8545/tcp comment 'NEXUS OS - Geth HTTP RPC'
    ufw allow 8546/tcp comment 'NEXUS OS - Geth WebSocket'
    ufw allow 30303/tcp comment 'NEXUS OS - Geth P2P TCP'
    ufw allow 30303/udp comment 'NEXUS OS - Geth P2P UDP'

    log "Firewall rules configured"
    log "  - HTTP RPC:  8545/tcp"
    log "  - WebSocket: 8546/tcp"
    log "  - P2P:       30303/tcp+udp"
}

start_node() {
    log "Starting NEXUS OS blockchain kernel..."

    systemctl start nexus-geth

    # Wait for service to start
    sleep 5

    # Check if service is running
    if systemctl is-active --quiet nexus-geth; then
        log "Blockchain kernel is running"
    else
        error "Failed to start blockchain kernel"
        log "Checking logs..."
        journalctl -u nexus-geth -n 50 --no-pager
        exit 1
    fi
}

test_connection() {
    log "Testing blockchain RPC connection..."

    # Wait for RPC to be ready
    sleep 5

    # Test RPC endpoint
    BLOCK_NUMBER=$(curl -s -X POST -H "Content-Type: application/json" \
        --data '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' \
        http://localhost:8545 | jq -r '.result')

    if [ -n "${BLOCK_NUMBER}" ]; then
        log "RPC connection successful"
        log "Current block: ${BLOCK_NUMBER}"
    else
        error "RPC connection failed"
        exit 1
    fi
}

save_config() {
    log "Saving NEXUS OS blockchain configuration..."

    # Get local IP address
    LOCAL_IP=$(hostname -I | awk '{print $1}')

    # Read device wallet
    DEVICE_WALLET_ADDR=$(cat "${DEVICE_WALLET_FILE}")

    # Create configuration file
    cat > "${BLOCKCHAIN_DIR}/config.json" <<EOF
{
  "version": "1.0.0",
  "chain_id": ${NEXUS_CHAIN_ID},
  "network_id": ${NEXUS_NETWORK_ID},
  "device_wallet": "${DEVICE_WALLET_ADDR}",
  "rpc_url": "http://${LOCAL_IP}:8545",
  "ws_url": "ws://${LOCAL_IP}:8546",
  "data_dir": "${DATA_DIR}",
  "keystore_dir": "${KEYSTORE_DIR}",
  "genesis_file": "${BLOCKCHAIN_DIR}/genesis.json",
  "password_file": "${BLOCKCHAIN_DIR}/password.txt"
}
EOF

    log "Configuration saved to ${BLOCKCHAIN_DIR}/config.json"
}

print_summary() {
    echo ""
    log "=========================================="
    log "NEXUS OS BLOCKCHAIN KERNEL DEPLOYED"
    log "=========================================="
    echo ""
    log "Device Information:"
    log "  Device ID:      $(hostname)"
    log "  Device Wallet:  $(cat ${DEVICE_WALLET_FILE})"
    echo ""
    log "Network Endpoints:"
    log "  RPC URL:        http://$(hostname -I | awk '{print $1}'):8545"
    log "  WebSocket URL:  ws://$(hostname -I | awk '{print $1}'):8546"
    log "  Chain ID:       ${NEXUS_CHAIN_ID}"
    echo ""
    log "Useful Commands:"
    log "  View logs:      journalctl -u nexus-geth -f"
    log "  Stop kernel:    systemctl stop nexus-geth"
    log "  Start kernel:   systemctl start nexus-geth"
    log "  Status:         systemctl status nexus-geth"
    log "  Geth console:   geth attach http://localhost:8545"
    echo ""
    log "Configuration:"
    log "  Config file:    ${BLOCKCHAIN_DIR}/config.json"
    log "  Data directory: ${DATA_DIR}"
    log "  Keystore:       ${KEYSTORE_DIR}"
    echo ""
    log "=========================================="
    echo ""
}

main() {
    log "Deploying NEXUS OS Blockchain Kernel..."
    log "Transformation: Web3 Pi → NEXUS OS Blockchain Kernel"
    echo ""

    # Check if running as root
    if [ "$EUID" -ne 0 ]; then
        error "Please run as root (use sudo)"
        exit 1
    fi

    # Execute deployment steps
    install_geth
    create_genesis
    create_cluster_accounts
    init_blockchain
    create_systemd_service
    configure_firewall
    start_node
    test_connection
    save_config

    # Print summary
    print_summary

    log "Blockchain kernel deployment complete!"
    log "NEXUS OS is now running on blockchain infrastructure"
}

# Run main function
main "$@"
