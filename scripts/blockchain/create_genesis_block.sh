#!/bin/bash
#
# NEXUS OS - Genesis Block Generator
# Creates the genesis block for NEXUS OS private blockchain
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[Genesis]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Configuration
BLOCKCHAIN_DIR="/opt/nexus/blockchain"
GENESIS_FILE="${BLOCKCHAIN_DIR}/genesis.json"

# NEXUS OS Network Configuration
CHAIN_ID=123454321
NETWORK_ID=123454321
BLOCK_PERIOD=5          # 5 seconds per block = kernel scheduler tick
EPOCH=30000             # Epoch length for PoA
GAS_LIMIT=8000000       # Max gas per block
DIFFICULTY=1            # Low difficulty for private network

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log "NEXUS OS Genesis Block Generator"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Create directory if it doesn't exist
mkdir -p "${BLOCKCHAIN_DIR}"

# Interactive mode or automatic mode
if [ "$1" = "--auto" ]; then
    warn "Running in automatic mode with example addresses"
    warn "This is for TESTING ONLY - replace with real addresses!"
    AUTO_MODE=true
else
    AUTO_MODE=false
fi

# Collect device wallet addresses
echo ""
info "Enter the Ethereum wallet addresses for each device"
info "(Run generate_device_wallets.sh on each device first)"
echo ""

if [ "$AUTO_MODE" = true ]; then
    # Example addresses for testing
    PI5_DEVICE1="0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf"
    PI5_DEVICE2="0x2B5AD5c4795c026514f8317c7a215E218DcCD6cF"
    PI5_DEVICE3="0x6813Eb9362372EEF6200f3b1dbC3f819671cBA69"
    PIZERO_MONITOR="0x1aB3F2e345C678901d2345E678f9012a3B4C5D6E"
    PI500_GATEWAY="0x9F8e7D6C5b4A3210987f6e5D4c3b2A1098765432"

    warn "Using example addresses - REPLACE THESE!"

else
    # Interactive input
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    info "Pi 5 Device #1 (Validator)"
    echo -n "Address (0x...): "
    read PI5_DEVICE1

    echo ""
    info "Pi 5 Device #2 (Validator)"
    echo -n "Address (0x...): "
    read PI5_DEVICE2

    echo ""
    info "Pi 5 Device #3 (Validator)"
    echo -n "Address (0x...): "
    read PI5_DEVICE3

    echo ""
    info "Pi Zero 2W (Monitor - Optional)"
    echo -n "Address (0x...) [press Enter to skip]: "
    read PIZERO_MONITOR

    echo ""
    info "Pi 500 (Gateway - Optional)"
    echo -n "Address (0x...) [press Enter to skip]: "
    read PI500_GATEWAY
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

fi

# Validate addresses
validate_address() {
    local addr=$1
    if [[ ! $addr =~ ^0x[a-fA-F0-9]{40}$ ]]; then
        error "Invalid Ethereum address: $addr"
        error "Must be 42 characters starting with 0x"
        exit 1
    fi
}

validate_address "$PI5_DEVICE1"
validate_address "$PI5_DEVICE2"
validate_address "$PI5_DEVICE3"

if [ ! -z "$PIZERO_MONITOR" ]; then
    validate_address "$PIZERO_MONITOR"
fi

if [ ! -z "$PI500_GATEWAY" ]; then
    validate_address "$PI500_GATEWAY"
fi

# Remove 0x prefix for extradata
DEVICE1_ADDR="${PI5_DEVICE1#0x}"
DEVICE2_ADDR="${PI5_DEVICE2#0x}"
DEVICE3_ADDR="${PI5_DEVICE3#0x}"

# Create extradata for Clique PoA
# Format: 32 bytes vanity + N * 20 bytes validators + 65 bytes seal
# We'll use 32 bytes of zeros as vanity, then our 3 validator addresses, then 65 bytes of zeros for seal
VANITY="0000000000000000000000000000000000000000000000000000000000000000"
SEAL="00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
EXTRADATA="0x${VANITY}${DEVICE1_ADDR}${DEVICE2_ADDR}${DEVICE3_ADDR}${SEAL}"

echo ""
log "Generating genesis block..."
echo ""
info "Network Configuration:"
echo "  Chain ID: ${CHAIN_ID}"
echo "  Network ID: ${NETWORK_ID}"
echo "  Block Period: ${BLOCK_PERIOD} seconds"
echo "  Gas Limit: ${GAS_LIMIT}"
echo ""
info "Validators (PoA Signers):"
echo "  1. ${PI5_DEVICE1}"
echo "  2. ${PI5_DEVICE2}"
echo "  3. ${PI5_DEVICE3}"
echo ""

# Create genesis.json
cat > "${GENESIS_FILE}" <<EOF
{
  "config": {
    "chainId": ${CHAIN_ID},
    "homesteadBlock": 0,
    "eip150Block": 0,
    "eip150Hash": "0x0000000000000000000000000000000000000000000000000000000000000000",
    "eip155Block": 0,
    "eip158Block": 0,
    "byzantiumBlock": 0,
    "constantinopleBlock": 0,
    "petersburgBlock": 0,
    "istanbulBlock": 0,
    "muirGlacierBlock": 0,
    "berlinBlock": 0,
    "londonBlock": 0,
    "arrowGlacierBlock": 0,
    "grayGlacierBlock": 0,
    "clique": {
      "period": ${BLOCK_PERIOD},
      "epoch": ${EPOCH}
    }
  },
  "nonce": "0x0",
  "timestamp": "0x0",
  "extraData": "${EXTRADATA}",
  "gasLimit": "0x${GAS_LIMIT}",
  "difficulty": "0x${DIFFICULTY}",
  "mixHash": "0x0000000000000000000000000000000000000000000000000000000000000000",
  "coinbase": "0x0000000000000000000000000000000000000000",
  "alloc": {
    "${PI5_DEVICE1}": {
      "balance": "0x3635C9ADC5DEA00000"
    },
    "${PI5_DEVICE2}": {
      "balance": "0x3635C9ADC5DEA00000"
    },
    "${PI5_DEVICE3}": {
      "balance": "0x3635C9ADC5DEA00000"
    }
EOF

# Add optional devices if provided
if [ ! -z "$PIZERO_MONITOR" ]; then
    cat >> "${GENESIS_FILE}" <<EOF
,
    "${PIZERO_MONITOR}": {
      "balance": "0x56BC75E2D63100000"
    }
EOF
fi

if [ ! -z "$PI500_GATEWAY" ]; then
    cat >> "${GENESIS_FILE}" <<EOF
,
    "${PI500_GATEWAY}": {
      "balance": "0x56BC75E2D63100000"
    }
EOF
fi

# Close the JSON
cat >> "${GENESIS_FILE}" <<EOF

  }
}
EOF

log "Genesis block created: ${GENESIS_FILE}"
echo ""

# Display allocation summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
info "Initial Fund Allocation:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Pi 5 Device #1 (Validator): 1000 ETH"
echo "  Address: ${PI5_DEVICE1}"
echo ""
echo "Pi 5 Device #2 (Validator): 1000 ETH"
echo "  Address: ${PI5_DEVICE2}"
echo ""
echo "Pi 5 Device #3 (Validator): 1000 ETH"
echo "  Address: ${PI5_DEVICE3}"
echo ""

if [ ! -z "$PIZERO_MONITOR" ]; then
    echo "Pi Zero 2W (Monitor): 100 ETH"
    echo "  Address: ${PIZERO_MONITOR}"
    echo ""
fi

if [ ! -z "$PI500_GATEWAY" ]; then
    echo "Pi 500 (Gateway): 100 ETH"
    echo "  Address: ${PI500_GATEWAY}"
    echo ""
fi

TOTAL_ALLOCATION=3000
if [ ! -z "$PIZERO_MONITOR" ]; then
    TOTAL_ALLOCATION=$((TOTAL_ALLOCATION + 100))
fi
if [ ! -z "$PI500_GATEWAY" ]; then
    TOTAL_ALLOCATION=$((TOTAL_ALLOCATION + 100))
fi

echo "Total Allocated: ${TOTAL_ALLOCATION} ETH"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Create human-readable summary
SUMMARY_FILE="${BLOCKCHAIN_DIR}/genesis_summary.txt"
cat > "${SUMMARY_FILE}" <<EOF
NEXUS OS Genesis Block Summary
===============================
Generated: $(date)

Network Configuration
---------------------
Chain ID: ${CHAIN_ID}
Network ID: ${NETWORK_ID}
Consensus: Proof of Authority (Clique)
Block Period: ${BLOCK_PERIOD} seconds
Gas Limit: ${GAS_LIMIT}
Difficulty: ${DIFFICULTY}

Validators (PoA Signers)
------------------------
Pi 5 Device #1: ${PI5_DEVICE1}
Pi 5 Device #2: ${PI5_DEVICE2}
Pi 5 Device #3: ${PI5_DEVICE3}

Initial Fund Allocation
-----------------------
Pi 5 Device #1: 1000 ETH (Validator)
Pi 5 Device #2: 1000 ETH (Validator)
Pi 5 Device #3: 1000 ETH (Validator)
EOF

if [ ! -z "$PIZERO_MONITOR" ]; then
    cat >> "${SUMMARY_FILE}" <<EOF
Pi Zero 2W: 100 ETH (Monitor)
  Address: ${PIZERO_MONITOR}
EOF
fi

if [ ! -z "$PI500_GATEWAY" ]; then
    cat >> "${SUMMARY_FILE}" <<EOF
Pi 500: 100 ETH (Gateway)
  Address: ${PI500_GATEWAY}
EOF
fi

cat >> "${SUMMARY_FILE}" <<EOF

Total Allocated: ${TOTAL_ALLOCATION} ETH

Technical Details
-----------------
Extradata (PoA seal): ${EXTRADATA}

Files Generated
---------------
Genesis Block: ${GENESIS_FILE}
Summary: ${SUMMARY_FILE}

Next Steps
----------
1. Copy ${GENESIS_FILE} to all nodes
2. On each node, run:
     geth init --datadir /opt/nexus/blockchain/data ${GENESIS_FILE}
3. Start Geth nodes with matching network ID (${NETWORK_ID})
4. Nodes will automatically connect and start validating

Verification
------------
After starting nodes, verify:

  1. Check block number: geth attach --exec "eth.blockNumber"
  2. Check peers: geth attach --exec "admin.peers.length"
  3. Check mining: geth attach --exec "eth.mining"
  4. Blocks should increment every ${BLOCK_PERIOD} seconds

⚠️  IMPORTANT NOTES
------------------
• This genesis block is IMMUTABLE once the blockchain starts
• Keep backups of this file and the wallet keystores
• Never expose the private keys
• This is a PRIVATE network - not connected to public Ethereum
• Total supply is fixed at ${TOTAL_ALLOCATION} ETH (no mining rewards in PoA)
EOF

log "Summary saved to: ${SUMMARY_FILE}"
echo ""

# Validate the JSON
if command -v python3 &> /dev/null; then
    info "Validating JSON syntax..."
    if python3 -c "import json; json.load(open('${GENESIS_FILE}'))" 2>/dev/null; then
        log "✅ Genesis block JSON is valid"
    else
        error "❌ Genesis block JSON is INVALID!"
        exit 1
    fi
else
    warn "Python3 not found - skipping JSON validation"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log "✅ Genesis Block Generation Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
info "Files created:"
echo "  - ${GENESIS_FILE}"
echo "  - ${SUMMARY_FILE}"
echo ""
info "Next steps:"
echo "  1. Review the genesis block: cat ${GENESIS_FILE}"
echo "  2. Distribute to all nodes"
echo "  3. Initialize blockchain on each node:"
echo "       sudo geth init --datadir /opt/nexus/blockchain/data ${GENESIS_FILE}"
echo ""
warn "⚠️  IMPORTANT: This genesis block is IMMUTABLE!"
warn "   Double-check all addresses before initializing nodes!"
echo ""
