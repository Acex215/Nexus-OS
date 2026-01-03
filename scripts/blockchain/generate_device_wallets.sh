#!/bin/bash
#
# NEXUS OS - Generate Device Wallets for Genesis Block
# Run this on each device to generate its wallet
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[Wallet Gen]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

# Check if geth is installed
if ! command -v geth &> /dev/null; then
    warn "Geth not installed. Installing..."
    sudo apt-get update
    sudo apt-get install -y software-properties-common
    sudo add-apt-repository -y ppa:ethereum/ethereum
    sudo apt-get update
    sudo apt-get install -y ethereum
fi

# Get device identifier
DEVICE_ID=$(hostname)
log "Device: ${DEVICE_ID}"

# Create directories
KEYSTORE_DIR="/tmp/nexus_keystore_${DEVICE_ID}"
mkdir -p "${KEYSTORE_DIR}"

# Get password from user
echo ""
info "Choose a password for this device's wallet"
info "IMPORTANT: Remember this password! You'll need it later."
echo ""
read -s -p "Enter password: " PASSWORD
echo ""
read -s -p "Confirm password: " PASSWORD_CONFIRM
echo ""

if [ "$PASSWORD" != "$PASSWORD_CONFIRM" ]; then
    warn "Passwords don't match!"
    exit 1
fi

# Save password to temporary file
PASSWORD_FILE="${KEYSTORE_DIR}/password.txt"
echo "$PASSWORD" > "$PASSWORD_FILE"
chmod 600 "$PASSWORD_FILE"

# Generate account
log "Generating Ethereum wallet..."
geth account new \
    --keystore "${KEYSTORE_DIR}" \
    --password "${PASSWORD_FILE}" \
    > /dev/null 2>&1

# Extract address
WALLET_ADDRESS=$(geth account list --keystore "${KEYSTORE_DIR}" 2>/dev/null | grep -oP '(?<={)[^}]+' | head -1)

if [ -z "$WALLET_ADDRESS" ]; then
    warn "Failed to generate wallet!"
    exit 1
fi

# Display results
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log "✅ Wallet generated successfully!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
info "Device: ${DEVICE_ID}"
info "Wallet Address: 0x${WALLET_ADDRESS}"
echo ""
info "Keystore file:"
ls -1 "${KEYSTORE_DIR}"/UTC--*
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
warn "SAVE THIS INFORMATION!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Copy the following to your genesis block configuration:"
echo ""
echo "  Device: ${DEVICE_ID}"
echo "  Address: 0x${WALLET_ADDRESS}"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Save to file for easy reference
OUTPUT_FILE="${KEYSTORE_DIR}/wallet_info.txt"
cat > "$OUTPUT_FILE" <<EOF
NEXUS OS Device Wallet Information
===================================

Device ID: ${DEVICE_ID}
Wallet Address: 0x${WALLET_ADDRESS}
Generated: $(date)

Keystore Location: ${KEYSTORE_DIR}
Password Location: ${PASSWORD_FILE}

⚠️  IMPORTANT SECURITY NOTES:

   1. Keep this password safe! You cannot recover your wallet without it.
   2. Back up the keystore file to a secure location.
   3. Never share your password or private key.
   4. This wallet will have 1000 ETH pre-allocated in the NEXUS OS network.

Next Steps:

   1. Add this address to the genesis.json file
   2. Copy the keystore file to /opt/nexus/blockchain/keystore/
   3. Create /opt/nexus/device_wallet.txt with this address
   4. Delete this temporary directory after setup is complete
EOF

log "Wallet information saved to: ${OUTPUT_FILE}"
echo ""

# Offer to display private key (for backup purposes)
echo ""
read -p "Do you want to view the private key for backup? (yes/no): " VIEW_KEY

if [ "$VIEW_KEY" = "yes" ]; then
    warn "⚠️  PRIVATE KEY - KEEP THIS SECRET! ⚠️"
    echo ""

    KEYFILE=$(ls -1 "${KEYSTORE_DIR}"/UTC--* | head -1)

    # Create a simple Python script to extract private key
    python3 -c "
import json
import getpass
from eth_account import Account

# Read keystore file
with open('${KEYFILE}', 'r') as f:
    keystore = json.load(f)

# Decrypt with password
password = '${PASSWORD}'
private_key = Account.decrypt(keystore, password)

print('Private Key (hex):', private_key.hex())
print('')
print('⚠️  NEVER SHARE THIS KEY WITH ANYONE!')
print('⚠️  Anyone with this key has full access to your wallet!')
" 2>/dev/null || {
        warn "Python3 or eth-account not available for key extraction"
        warn "Install with: pip3 install eth-account"
    }

    echo ""
fi

echo ""
log "Generation complete!"
log "Temporary files in: ${KEYSTORE_DIR}"
info "Keep this directory safe until genesis block is created"
echo ""
