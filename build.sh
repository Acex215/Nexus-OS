#!/bin/bash
#
# NEXUS OS Build Script
# Creates a flashable SD card image for Raspberry Pi
#
# Usage:
#   ./build.sh              # Full build (requires root/sudo)
#   ./build.sh lite         # Build minimal image
#   ./build.sh docker       # Build using Docker (recommended)
#   ./build.sh clean        # Clean build artifacts
#
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/build"
PIGEN_DIR="${SCRIPT_DIR}/pi-gen"
DEPLOY_DIR="${SCRIPT_DIR}/deploy"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[NEXUS Build]${NC} $1"; }
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
    echo "  Blockchain Operating System - Image Builder"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
}

# Check prerequisites
check_prerequisites() {
    log "Checking build prerequisites..."

    local missing=()

    # Check for required tools
    command -v git >/dev/null 2>&1 || missing+=("git")
    command -v wget >/dev/null 2>&1 || missing+=("wget")
    command -v curl >/dev/null 2>&1 || missing+=("curl")

    if [ ${#missing[@]} -gt 0 ]; then
        error "Missing required tools: ${missing[*]}\nInstall with: sudo apt-get install ${missing[*]}"
    fi

    log "Prerequisites OK"
}

# Clone or update pi-gen
setup_pigen() {
    log "Setting up pi-gen..."

    if [ -d "${PIGEN_DIR}" ]; then
        info "pi-gen already exists, updating..."
        cd "${PIGEN_DIR}"
        git pull || warn "Could not update pi-gen (offline?)"
        cd "${SCRIPT_DIR}"
    else
        info "Cloning pi-gen..."
        git clone --depth 1 https://github.com/RPi-Distro/pi-gen.git "${PIGEN_DIR}"
    fi

    log "pi-gen ready"
}

# Create NEXUS OS stage
create_nexus_stage() {
    log "Creating NEXUS OS stage..."

    local STAGE_DIR="${PIGEN_DIR}/stage-nexus"

    # Remove existing stage if present
    rm -rf "${STAGE_DIR}"
    mkdir -p "${STAGE_DIR}"

    # Create stage marker files
    touch "${STAGE_DIR}/EXPORT_IMAGE"
    touch "${STAGE_DIR}/EXPORT_NOOBS"

    # 00-packages - Install required packages
    mkdir -p "${STAGE_DIR}/00-packages"
    cat > "${STAGE_DIR}/00-packages/00-packages" << 'EOF'
software-properties-common
curl
wget
jq
nmap
ufw
vlan
bridge-utils
net-tools
iptables-persistent
avahi-daemon
python3
python3-pip
python3-venv
git
htop
tmux
vim
EOF

    cat > "${STAGE_DIR}/00-packages/00-run.sh" << 'RUNEOF'
#!/bin/bash -e

# Install packages from list
on_chroot << EOF
apt-get update
apt-get install -y $(cat ${ROOTFS_DIR}/packages.txt | tr '\n' ' ')
EOF
RUNEOF
    chmod +x "${STAGE_DIR}/00-packages/00-run.sh"

    # Copy package list
    cat > "${STAGE_DIR}/00-packages/files/packages.txt" << 'EOF'
software-properties-common
curl
wget
jq
nmap
ufw
vlan
bridge-utils
net-tools
iptables-persistent
avahi-daemon
python3
python3-pip
python3-venv
git
htop
tmux
vim
EOF
    mkdir -p "${STAGE_DIR}/00-packages/files"
    mv "${STAGE_DIR}/00-packages/files/packages.txt" "${STAGE_DIR}/00-packages/files/" 2>/dev/null || true

    # 01-nexus-files - Copy NEXUS OS files
    mkdir -p "${STAGE_DIR}/01-nexus-files/files"

    cat > "${STAGE_DIR}/01-nexus-files/00-run.sh" << 'RUNEOF'
#!/bin/bash -e

# Create NEXUS OS directory structure
on_chroot << EOF
mkdir -p /opt/nexus/{blockchain,scripts,network,backup,logs,run,tmp}
mkdir -p /opt/nexus/blockchain/{data,keystore,config}
mkdir -p /var/lib/nexus
mkdir -p /etc/nexus

# Set permissions
chmod 750 /opt/nexus/blockchain
chmod 700 /opt/nexus/blockchain/keystore
chmod 755 /opt/nexus/{logs,run,tmp}
EOF

# Copy NEXUS OS files
install -m 755 -d "${ROOTFS_DIR}/opt/nexus"
install -m 755 -d "${ROOTFS_DIR}/opt/nexus/scripts/blockchain"
install -m 755 -d "${ROOTFS_DIR}/opt/nexus/setup.d"
install -m 755 -d "${ROOTFS_DIR}/opt/nexus/first-run.d"
install -m 755 -d "${ROOTFS_DIR}/opt/nexus/core"
install -m 755 -d "${ROOTFS_DIR}/opt/nexus/network"
install -m 755 -d "${ROOTFS_DIR}/opt/nexus/backup"

# Copy scripts
cp -r "${NEXUS_SRC}/scripts/blockchain/"* "${ROOTFS_DIR}/opt/nexus/scripts/blockchain/" || true
cp -r "${NEXUS_SRC}/setup.d/"* "${ROOTFS_DIR}/opt/nexus/setup.d/" || true
cp -r "${NEXUS_SRC}/first-run.d/"* "${ROOTFS_DIR}/opt/nexus/first-run.d/" || true
cp -r "${NEXUS_SRC}/core/"* "${ROOTFS_DIR}/opt/nexus/core/" || true
cp -r "${NEXUS_SRC}/network/"* "${ROOTFS_DIR}/opt/nexus/network/" || true
cp -r "${NEXUS_SRC}/backup/"* "${ROOTFS_DIR}/opt/nexus/backup/" || true

# Make scripts executable
chmod +x "${ROOTFS_DIR}/opt/nexus/scripts/blockchain/"*.sh 2>/dev/null || true
chmod +x "${ROOTFS_DIR}/opt/nexus/setup.d/"* 2>/dev/null || true
chmod +x "${ROOTFS_DIR}/opt/nexus/first-run.d/"* 2>/dev/null || true

# Install smart contracts
install -m 755 -d "${ROOTFS_DIR}/opt/nexus/contracts"
cp -r "${NEXUS_SRC}/contracts/"*.sol "${ROOTFS_DIR}/opt/nexus/contracts/" 2>/dev/null || true
cp "${NEXUS_SRC}/scripts/blockchain/deploy_contracts.py" "${ROOTFS_DIR}/opt/nexus/contracts/" 2>/dev/null || true
chmod +x "${ROOTFS_DIR}/opt/nexus/contracts/deploy_contracts.py" 2>/dev/null || true

# Install CLI tool
cp "${NEXUS_SRC}/scripts/cli/nexus-cli" "${ROOTFS_DIR}/usr/local/bin/nexus-cli" 2>/dev/null || true
chmod +x "${ROOTFS_DIR}/usr/local/bin/nexus-cli" 2>/dev/null || true
RUNEOF
    chmod +x "${STAGE_DIR}/01-nexus-files/00-run.sh"

    # 02-systemd - Setup systemd services
    mkdir -p "${STAGE_DIR}/02-systemd/files"

    # Copy systemd service files
    cp "${SCRIPT_DIR}/systemd/"*.service "${STAGE_DIR}/02-systemd/files/" 2>/dev/null || true

    cat > "${STAGE_DIR}/02-systemd/00-run.sh" << 'RUNEOF'
#!/bin/bash -e

# Install systemd services
install -m 644 files/nexus-setup.service "${ROOTFS_DIR}/etc/systemd/system/"
install -m 644 files/nexus-first-run.service "${ROOTFS_DIR}/etc/systemd/system/"

# Enable services
on_chroot << EOF
systemctl enable nexus-setup.service
systemctl enable nexus-first-run.service
systemctl enable avahi-daemon.service
systemctl enable ssh.service
EOF
RUNEOF
    chmod +x "${STAGE_DIR}/02-systemd/00-run.sh"

    # 03-geth - Install Geth (Ethereum)
    mkdir -p "${STAGE_DIR}/03-geth"

    cat > "${STAGE_DIR}/03-geth/00-run.sh" << 'RUNEOF'
#!/bin/bash -e

on_chroot << EOF
# Add Ethereum PPA (for Ubuntu-based) or install from source for Debian
if [ -f /etc/apt/sources.list.d/ethereum.list ]; then
    echo "Ethereum repository already configured"
else
    # For Debian/Raspbian, we download Geth directly
    ARCH=\$(dpkg --print-architecture)

    if [ "\${ARCH}" = "arm64" ]; then
        GETH_ARCH="linux-arm64"
    else
        GETH_ARCH="linux-arm7"
    fi

    # Download latest stable Geth for ARM
    GETH_VERSION="1.13.14"
    GETH_URL="https://gethstore.blob.core.windows.net/builds/geth-\${GETH_ARCH}-\${GETH_VERSION}-2bd6bd01.tar.gz"

    cd /tmp
    wget -q "\${GETH_URL}" -O geth.tar.gz || {
        echo "Failed to download Geth, will install from PPA if available"
        add-apt-repository -y ppa:ethereum/ethereum 2>/dev/null || true
        apt-get update
        apt-get install -y ethereum || echo "Geth installation deferred to first boot"
        exit 0
    }

    tar xzf geth.tar.gz
    cp geth-*/geth /usr/local/bin/
    chmod +x /usr/local/bin/geth
    rm -rf geth.tar.gz geth-*

    # Create symlink
    ln -sf /usr/local/bin/geth /usr/bin/geth

    echo "Geth installed successfully"
fi
EOF
RUNEOF
    chmod +x "${STAGE_DIR}/03-geth/00-run.sh"

    # 04-config - Final configuration
    mkdir -p "${STAGE_DIR}/04-config/files"

    cat > "${STAGE_DIR}/04-config/00-run.sh" << 'RUNEOF'
#!/bin/bash -e

on_chroot << EOF
# Enable 8021q VLAN module
echo "8021q" >> /etc/modules-load.d/nexus.conf

# Enable IP forwarding
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.d/99-nexus.conf

# Create default config
cat > /etc/nexus/nexus.conf << 'NEXUSCONF'
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
NEXUSCONF

# Create MOTD
cat > /etc/motd << 'MOTD'

 _   _ _______  ___   _ ____     ___  ____
| \ | | ____\ \/ / | | / ___|   / _ \/ ___|
|  \| |  _|  \  /| | | \___ \  | | | \___ \
| |\  | |___ /  \| |_| |___) | | |_| |___) |
|_| \_|_____/_/\_\___/|____/   \___/|____/

         Blockchain Operating System

  Status:   systemctl status nexus-geth
  Logs:     journalctl -u nexus-geth -f
  Console:  geth attach http://localhost:8545

  Configuration: /etc/nexus/nexus.conf
  Documentation: https://github.com/Acex215/Nexus-OS

MOTD

# Set hostname
echo "nexus-node" > /etc/hostname

# Update hosts file
echo "127.0.0.1 nexus-node" >> /etc/hosts

EOF
RUNEOF
    chmod +x "${STAGE_DIR}/04-config/00-run.sh"

    log "NEXUS OS stage created"
}

# Create systemd service files
create_systemd_services() {
    log "Creating systemd service files..."

    mkdir -p "${SCRIPT_DIR}/systemd"

    # NEXUS Setup Service (runs setup.d scripts on first boot)
    cat > "${SCRIPT_DIR}/systemd/nexus-setup.service" << 'EOF'
[Unit]
Description=NEXUS OS Initial Setup
ConditionPathExists=!/var/lib/nexus/setup-completed
After=network-online.target
Wants=network-online.target
Before=nexus-first-run.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/opt/nexus/scripts/run-setup.sh
ExecStartPost=/bin/touch /var/lib/nexus/setup-completed

[Install]
WantedBy=multi-user.target
EOF

    # NEXUS First Run Service (runs first-run.d scripts)
    cat > "${SCRIPT_DIR}/systemd/nexus-first-run.service" << 'EOF'
[Unit]
Description=NEXUS OS First Boot Configuration
ConditionPathExists=!/var/lib/nexus/first-run-completed
After=nexus-setup.service network-online.target
Wants=network-online.target
Before=nexus-geth.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/opt/nexus/scripts/run-first-boot.sh
ExecStartPost=/bin/touch /var/lib/nexus/first-run-completed

[Install]
WantedBy=multi-user.target
EOF

    log "Systemd services created"
}

# Create helper scripts
create_helper_scripts() {
    log "Creating helper scripts..."

    mkdir -p "${SCRIPT_DIR}/scripts"

    # Setup runner script
    cat > "${SCRIPT_DIR}/scripts/run-setup.sh" << 'EOF'
#!/bin/bash
# NEXUS OS - Run setup.d scripts in order
set -e

LOG_FILE="/var/log/nexus-setup.log"

log() {
    echo "[NEXUS Setup $(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "${LOG_FILE}"
}

log "Starting NEXUS OS setup..."

SETUP_DIR="/opt/nexus/setup.d"

if [ ! -d "${SETUP_DIR}" ]; then
    log "Setup directory not found: ${SETUP_DIR}"
    exit 0
fi

# Run scripts in sorted order
for script in $(find "${SETUP_DIR}" -type f -executable | sort); do
    log "Running: ${script}"
    bash "${script}" >> "${LOG_FILE}" 2>&1 || {
        log "Warning: ${script} failed with exit code $?"
    }
done

log "NEXUS OS setup completed"
EOF
    chmod +x "${SCRIPT_DIR}/scripts/run-setup.sh"

    # First boot runner script
    cat > "${SCRIPT_DIR}/scripts/run-first-boot.sh" << 'EOF'
#!/bin/bash
# NEXUS OS - Run first-run.d scripts in order
set -e

LOG_FILE="/var/log/nexus-first-run.log"

log() {
    echo "[NEXUS First-Run $(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "${LOG_FILE}"
}

log "Starting NEXUS OS first boot configuration..."

FIRSTRUN_DIR="/opt/nexus/first-run.d"

if [ ! -d "${FIRSTRUN_DIR}" ]; then
    log "First-run directory not found: ${FIRSTRUN_DIR}"
    exit 0
fi

# Run scripts in sorted order
for script in $(find "${FIRSTRUN_DIR}" -type f -executable | sort); do
    log "Running: ${script}"
    bash "${script}" >> "${LOG_FILE}" 2>&1 || {
        log "Warning: ${script} failed with exit code $?"
    }
done

log "NEXUS OS first boot configuration completed"
EOF
    chmod +x "${SCRIPT_DIR}/scripts/run-first-boot.sh"

    log "Helper scripts created"
}

# Build using pi-gen
build_image() {
    log "Starting image build..."

    cd "${PIGEN_DIR}"

    # Copy config
    cp "${BUILD_DIR}/config" "${PIGEN_DIR}/config"

    # Export NEXUS source directory for build scripts
    export NEXUS_SRC="${SCRIPT_DIR}"

    # Run pi-gen build
    if [ "$1" = "docker" ]; then
        info "Building with Docker..."
        ./build-docker.sh
    else
        info "Building natively (requires root)..."
        if [ "$EUID" -ne 0 ]; then
            error "Native build requires root. Use: sudo ./build.sh or ./build.sh docker"
        fi
        ./build.sh
    fi

    cd "${SCRIPT_DIR}"

    log "Image build complete!"
}

# Build without pi-gen (simpler approach for testing)
build_simple() {
    log "Creating simple installation package..."

    local PKG_DIR="${DEPLOY_DIR}/nexus-os-installer"
    rm -rf "${PKG_DIR}"
    mkdir -p "${PKG_DIR}"

    # Copy all necessary files
    cp -r "${SCRIPT_DIR}/scripts" "${PKG_DIR}/"
    cp -r "${SCRIPT_DIR}/setup.d" "${PKG_DIR}/"
    cp -r "${SCRIPT_DIR}/first-run.d" "${PKG_DIR}/"
    cp -r "${SCRIPT_DIR}/core" "${PKG_DIR}/"
    cp -r "${SCRIPT_DIR}/network" "${PKG_DIR}/"
    cp -r "${SCRIPT_DIR}/backup" "${PKG_DIR}/"
    cp -r "${SCRIPT_DIR}/systemd" "${PKG_DIR}/"
    cp "${SCRIPT_DIR}/scripts/run-setup.sh" "${PKG_DIR}/"
    cp "${SCRIPT_DIR}/scripts/run-first-boot.sh" "${PKG_DIR}/"

    # Create installer script
    cat > "${PKG_DIR}/install.sh" << 'INSTALLEOF'
#!/bin/bash
# NEXUS OS Installer
# Run this on a fresh Raspberry Pi OS installation
set -e

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo ./install.sh"
    exit 1
fi

echo "Installing NEXUS OS..."

# Create directory structure
mkdir -p /opt/nexus/{blockchain,scripts,network,backup,logs,run,tmp}
mkdir -p /opt/nexus/blockchain/{data,keystore,config}
mkdir -p /var/lib/nexus
mkdir -p /etc/nexus

# Copy files
cp -r scripts/* /opt/nexus/scripts/
cp -r setup.d /opt/nexus/
cp -r first-run.d /opt/nexus/
cp -r core /opt/nexus/
cp -r network /opt/nexus/
cp -r backup /opt/nexus/
cp run-setup.sh /opt/nexus/scripts/
cp run-first-boot.sh /opt/nexus/scripts/

# Make scripts executable
chmod +x /opt/nexus/scripts/*.sh
chmod +x /opt/nexus/scripts/blockchain/*.sh
chmod +x /opt/nexus/setup.d/*
chmod +x /opt/nexus/first-run.d/*

# Install systemd services
cp systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable nexus-setup.service
systemctl enable nexus-first-run.service

# Run setup immediately
echo "Running initial setup..."
/opt/nexus/scripts/run-setup.sh

echo ""
echo "NEXUS OS installed successfully!"
echo ""
echo "Next steps:"
echo "  1. Reboot to complete first-run configuration"
echo "  2. Or run: /opt/nexus/scripts/run-first-boot.sh"
echo ""
echo "After first boot:"
echo "  - Check status: systemctl status nexus-geth"
echo "  - View logs: journalctl -u nexus-geth -f"
echo ""
INSTALLEOF
    chmod +x "${PKG_DIR}/install.sh"

    # Create tarball
    cd "${DEPLOY_DIR}"
    tar -czvf nexus-os-installer.tar.gz nexus-os-installer

    log "Installation package created: ${DEPLOY_DIR}/nexus-os-installer.tar.gz"
    info "To install on a Raspberry Pi:"
    echo "  1. Copy nexus-os-installer.tar.gz to the Pi"
    echo "  2. Extract: tar xzf nexus-os-installer.tar.gz"
    echo "  3. Install: cd nexus-os-installer && sudo ./install.sh"
}

# Clean build artifacts
clean() {
    log "Cleaning build artifacts..."

    rm -rf "${PIGEN_DIR}/work" 2>/dev/null || true
    rm -rf "${DEPLOY_DIR}" 2>/dev/null || true
    rm -rf "${PIGEN_DIR}/deploy" 2>/dev/null || true

    log "Clean complete"
}

# Main entry point
main() {
    print_banner

    case "${1:-full}" in
        docker)
            check_prerequisites
            setup_pigen
            create_systemd_services
            create_helper_scripts
            create_nexus_stage
            build_image docker
            ;;
        full)
            check_prerequisites
            setup_pigen
            create_systemd_services
            create_helper_scripts
            create_nexus_stage
            build_image
            ;;
        lite|simple|package)
            check_prerequisites
            create_systemd_services
            create_helper_scripts
            mkdir -p "${DEPLOY_DIR}"
            build_simple
            ;;
        stage)
            check_prerequisites
            setup_pigen
            create_systemd_services
            create_helper_scripts
            create_nexus_stage
            log "Stage created. Run './build.sh full' or './build.sh docker' to build image."
            ;;
        clean)
            clean
            ;;
        help|--help|-h)
            echo "NEXUS OS Build Script"
            echo ""
            echo "Usage: ./build.sh [command]"
            echo ""
            echo "Commands:"
            echo "  full      Build full SD card image (requires root)"
            echo "  docker    Build using Docker (recommended)"
            echo "  lite      Create installation package only"
            echo "  simple    Same as 'lite'"
            echo "  package   Same as 'lite'"
            echo "  stage     Create pi-gen stage only (no build)"
            echo "  clean     Remove build artifacts"
            echo "  help      Show this help message"
            echo ""
            echo "Examples:"
            echo "  ./build.sh docker   # Build image using Docker"
            echo "  ./build.sh lite     # Create installer package"
            echo ""
            ;;
        *)
            error "Unknown command: $1\nRun './build.sh help' for usage."
            ;;
    esac
}

main "$@"
