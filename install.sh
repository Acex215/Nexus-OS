#!/bin/bash
#
# NEXUS OS Installation Script
# Installs NEXUS OS on an existing Raspberry Pi OS system
#
# Usage:
#   sudo ./install.sh           # Full installation
#   sudo ./install.sh --minimal # Install without starting services
#   sudo ./install.sh --help    # Show help
#
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[NEXUS Install]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

print_banner() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  _   _ _______  ___   _ ____     ___  ____  "
    echo " | \\ | | ____\\ \\/ / | | / ___|   / _ \\/ ___| "
    echo " |  \\| |  _|  \\  /| | | \\___ \\  | | | \\___ \\ "
    echo " | |\\  | |___ /  \\| |_| |___) | | |_| |___) |"
    echo " |_| \\_|_____/_/\\_\\\\___/|____/   \\___/|____/ "
    echo ""
    echo "       Blockchain Operating System Installer"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
}

show_help() {
    echo "NEXUS OS Installation Script"
    echo ""
    echo "Usage: sudo ./install.sh [options]"
    echo ""
    echo "Options:"
    echo "  --minimal     Install files only, don't run setup or start services"
    echo "  --no-geth     Skip Geth installation (install later)"
    echo "  --help        Show this help message"
    echo ""
    echo "Requirements:"
    echo "  - Raspberry Pi 4 or 5 (8GB RAM recommended)"
    echo "  - Raspberry Pi OS Lite (64-bit) or Ubuntu Server 22.04"
    echo "  - Internet connection"
    echo "  - At least 32GB SD card or SSD"
    echo ""
    echo "After installation:"
    echo "  - Reboot to complete first-run configuration"
    echo "  - Check status: systemctl status nexus-geth"
    echo "  - View logs: journalctl -u nexus-geth -f"
    echo ""
}

# Parse arguments
MINIMAL=false
SKIP_GETH=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --minimal)
            MINIMAL=true
            shift
            ;;
        --no-geth)
            SKIP_GETH=true
            shift
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            error "Unknown option: $1\nRun './install.sh --help' for usage."
            ;;
    esac
done

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        error "Please run as root: sudo ./install.sh"
    fi
}

# Check system requirements
check_requirements() {
    log "Checking system requirements..."

    # Check architecture
    ARCH=$(uname -m)
    if [[ "${ARCH}" != "aarch64" && "${ARCH}" != "armv7l" ]]; then
        warn "This system is ${ARCH}, not ARM. NEXUS OS is designed for Raspberry Pi."
        warn "Installation will continue, but some features may not work."
    fi

    # Check available memory
    MEM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    MEM_GB=$((MEM_KB / 1024 / 1024))
    if [ "${MEM_GB}" -lt 4 ]; then
        warn "System has ${MEM_GB}GB RAM. 4GB+ recommended for blockchain operations."
    else
        info "Memory: ${MEM_GB}GB RAM"
    fi

    # Check available disk space
    DISK_FREE=$(df -BG / | tail -1 | awk '{print $4}' | tr -d 'G')
    if [ "${DISK_FREE}" -lt 20 ]; then
        warn "Only ${DISK_FREE}GB disk space available. 20GB+ recommended."
    else
        info "Disk space: ${DISK_FREE}GB available"
    fi

    log "System requirements check complete"
}

# Create directory structure
create_directories() {
    log "Creating NEXUS OS directory structure..."

    mkdir -p /opt/nexus/{blockchain,scripts,network,backup,logs,run,tmp}
    mkdir -p /opt/nexus/blockchain/{data,keystore,config}
    mkdir -p /opt/nexus/setup.d
    mkdir -p /opt/nexus/first-run.d
    mkdir -p /opt/nexus/core
    mkdir -p /var/lib/nexus
    mkdir -p /etc/nexus

    # Set permissions
    chmod 750 /opt/nexus/blockchain
    chmod 700 /opt/nexus/blockchain/keystore
    chmod 755 /opt/nexus/{logs,run,tmp}

    log "Directory structure created"
}

# Copy NEXUS OS files
copy_files() {
    log "Copying NEXUS OS files..."

    # Copy scripts
    if [ -d "${SCRIPT_DIR}/scripts" ]; then
        cp -r "${SCRIPT_DIR}/scripts/"* /opt/nexus/scripts/
        chmod +x /opt/nexus/scripts/*.sh 2>/dev/null || true
        chmod +x /opt/nexus/scripts/blockchain/*.sh 2>/dev/null || true
    fi

    # Copy setup.d
    if [ -d "${SCRIPT_DIR}/setup.d" ]; then
        cp -r "${SCRIPT_DIR}/setup.d/"* /opt/nexus/setup.d/
        chmod +x /opt/nexus/setup.d/* 2>/dev/null || true
    fi

    # Copy first-run.d
    if [ -d "${SCRIPT_DIR}/first-run.d" ]; then
        cp -r "${SCRIPT_DIR}/first-run.d/"* /opt/nexus/first-run.d/
        chmod +x /opt/nexus/first-run.d/* 2>/dev/null || true
    fi

    # Copy Python modules
    if [ -d "${SCRIPT_DIR}/core" ]; then
        cp -r "${SCRIPT_DIR}/core/"* /opt/nexus/core/
    fi

    if [ -d "${SCRIPT_DIR}/network" ]; then
        cp -r "${SCRIPT_DIR}/network/"* /opt/nexus/network/
    fi

    if [ -d "${SCRIPT_DIR}/backup" ]; then
        cp -r "${SCRIPT_DIR}/backup/"* /opt/nexus/backup/
    fi

    log "Files copied"
}

# Install systemd services
install_services() {
    log "Installing systemd services..."

    # Copy service files
    if [ -d "${SCRIPT_DIR}/systemd" ]; then
        cp "${SCRIPT_DIR}/systemd/"*.service /etc/systemd/system/
    fi

    # Reload systemd
    systemctl daemon-reload

    # Enable services
    systemctl enable nexus-setup.service 2>/dev/null || true
    systemctl enable nexus-first-run.service 2>/dev/null || true

    log "Systemd services installed"
}

# Create default configuration
create_config() {
    log "Creating default configuration..."

    cat > /etc/nexus/nexus.conf << 'EOF'
# NEXUS OS Configuration
# Edit this file to customize your node

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

# Mining Configuration
NEXUS_MINER_THREADS=2
NEXUS_MAX_PEERS=25
EOF

    log "Configuration created at /etc/nexus/nexus.conf"
}

# Install Geth
install_geth() {
    if [ "${SKIP_GETH}" = true ]; then
        warn "Skipping Geth installation (--no-geth flag)"
        return 0
    fi

    if command -v geth &> /dev/null; then
        log "Geth already installed: $(geth version | head -n1)"
        return 0
    fi

    log "Installing Geth (Go Ethereum)..."

    # Determine architecture
    ARCH=$(dpkg --print-architecture 2>/dev/null || uname -m)

    # Try to install from Ethereum PPA first (Ubuntu/Debian)
    if command -v add-apt-repository &> /dev/null; then
        info "Adding Ethereum PPA..."
        add-apt-repository -y ppa:ethereum/ethereum 2>/dev/null || true
        apt-get update
        if apt-get install -y ethereum; then
            log "Geth installed from PPA"
            return 0
        fi
    fi

    # Fallback: Download pre-built binary
    info "Downloading pre-built Geth binary..."

    if [[ "${ARCH}" == "arm64" || "${ARCH}" == "aarch64" ]]; then
        GETH_ARCH="linux-arm64"
    else
        GETH_ARCH="linux-arm7"
    fi

    GETH_VERSION="1.13.14"
    GETH_URL="https://gethstore.blob.core.windows.net/builds/geth-${GETH_ARCH}-${GETH_VERSION}-2bd6bd01.tar.gz"

    cd /tmp
    if wget -q "${GETH_URL}" -O geth.tar.gz; then
        tar xzf geth.tar.gz
        cp geth-*/geth /usr/local/bin/
        chmod +x /usr/local/bin/geth
        ln -sf /usr/local/bin/geth /usr/bin/geth
        rm -rf geth.tar.gz geth-*
        log "Geth installed: $(geth version | head -n1)"
    else
        warn "Could not download Geth. Install manually before starting services."
    fi

    cd "${SCRIPT_DIR}"
}

# Run setup scripts
run_setup() {
    if [ "${MINIMAL}" = true ]; then
        info "Skipping setup (--minimal flag)"
        return 0
    fi

    log "Running initial setup..."

    if [ -x "/opt/nexus/scripts/run-setup.sh" ]; then
        /opt/nexus/scripts/run-setup.sh
    else
        warn "Setup script not found or not executable"
    fi

    log "Initial setup complete"
}

# Print summary
print_summary() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log "NEXUS OS Installation Complete!"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    info "Installation directory: /opt/nexus"
    info "Configuration file: /etc/nexus/nexus.conf"
    info "Logs directory: /var/log/nexus-*.log"
    echo ""
    echo "Next steps:"
    echo ""
    echo "  1. REBOOT to complete first-run configuration:"
    echo "     sudo reboot"
    echo ""
    echo "  2. Or run first-run manually (no reboot):"
    echo "     sudo /opt/nexus/scripts/run-first-boot.sh"
    echo ""
    echo "After first boot:"
    echo ""
    echo "  Check status:    sudo systemctl status nexus-geth"
    echo "  View logs:       sudo journalctl -u nexus-geth -f"
    echo "  Geth console:    geth attach http://localhost:8545"
    echo ""
    echo "For multi-node setup:"
    echo ""
    echo "  1. Run this installer on all Pi devices"
    echo "  2. Generate wallets on each: /opt/nexus/scripts/blockchain/generate_device_wallets.sh"
    echo "  3. Create shared genesis block: /opt/nexus/scripts/blockchain/create_genesis_block.sh"
    echo "  4. Copy genesis.json to all nodes"
    echo "  5. Reboot all nodes"
    echo ""
    echo "Documentation: https://github.com/Acex215/Nexus-OS"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
}

# Main installation
main() {
    print_banner

    check_root
    check_requirements

    log "Starting NEXUS OS installation..."
    echo ""

    create_directories
    copy_files
    install_services
    create_config
    install_geth
    run_setup

    print_summary
}

main "$@"
