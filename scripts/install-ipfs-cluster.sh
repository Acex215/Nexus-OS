#!/bin/bash
# Install IPFS (Kubo) on NEXUS OS cluster
set -euo pipefail

IPFS_VERSION="v0.32.1"
IPFS_TAR="kubo_${IPFS_VERSION}_linux-arm64.tar.gz"
IPFS_URL="https://dist.ipfs.tech/kubo/${IPFS_VERSION}/${IPFS_TAR}"
IPFS_PATH="/opt/nexus/ipfs"

echo "=== Installing IPFS ${IPFS_VERSION} on NEXUS Cluster ==="
echo ""

# Download once locally
if [ ! -f "/tmp/${IPFS_TAR}" ]; then
    echo "Downloading ${IPFS_TAR}..."
    wget -q --show-progress -O "/tmp/${IPFS_TAR}" "${IPFS_URL}"
else
    echo "Using cached /tmp/${IPFS_TAR}"
fi

install_local() {
    echo ""
    echo "=== Installing on $(hostname) (local) ==="

    cd /tmp
    tar xzf "${IPFS_TAR}"
    cd kubo
    sudo bash install.sh

    # Initialize
    export IPFS_PATH="${IPFS_PATH}"
    sudo mkdir -p "${IPFS_PATH}"
    sudo chown "$(whoami):$(whoami)" "${IPFS_PATH}"

    if [ -f "${IPFS_PATH}/config" ]; then
        echo "  IPFS already initialized at ${IPFS_PATH}"
    else
        ipfs init --profile=lowpower
    fi

    # Storage limit for nexus-admin (small disk)
    ipfs config Datastore.StorageMax "15GB"

    # Low-power Pi settings
    ipfs config --json Swarm.ConnMgr.LowWater 20
    ipfs config --json Swarm.ConnMgr.HighWater 40
    ipfs config --json Swarm.DisableBandwidthMetrics true

    # Listen on all interfaces (needed for cluster)
    ipfs config Addresses.API "/ip4/0.0.0.0/tcp/5001"
    ipfs config Addresses.Gateway "/ip4/0.0.0.0/tcp/8080"

    echo "  IPFS $(ipfs version) installed on $(hostname)"
}

install_remote() {
    local node=$1
    local storage_limit=$2

    echo ""
    echo "=== Installing on ${node} ==="

    # Copy tarball to remote
    scp -o StrictHostKeyChecking=no "/tmp/${IPFS_TAR}" "${node}:/tmp/${IPFS_TAR}"

    ssh -o StrictHostKeyChecking=no "${node}" bash -s "${IPFS_TAR}" "${IPFS_PATH}" "${storage_limit}" <<'REMOTE_SCRIPT'
        set -euo pipefail
        IPFS_TAR="$1"
        IPFS_PATH="$2"
        STORAGE_LIMIT="$3"

        cd /tmp
        tar xzf "${IPFS_TAR}"
        cd kubo
        sudo bash install.sh

        export IPFS_PATH="${IPFS_PATH}"
        sudo mkdir -p "${IPFS_PATH}"
        sudo chown "$(whoami):$(whoami)" "${IPFS_PATH}"

        if [ -f "${IPFS_PATH}/config" ]; then
            echo "  IPFS already initialized at ${IPFS_PATH}"
        else
            ipfs init --profile=lowpower
        fi

        ipfs config Datastore.StorageMax "${STORAGE_LIMIT}"
        ipfs config --json Swarm.ConnMgr.LowWater 20
        ipfs config --json Swarm.ConnMgr.HighWater 40
        ipfs config --json Swarm.DisableBandwidthMetrics true
        ipfs config Addresses.API "/ip4/0.0.0.0/tcp/5001"
        ipfs config Addresses.Gateway "/ip4/0.0.0.0/tcp/8080"

        echo "  IPFS $(ipfs version) installed on $(hostname)"
REMOTE_SCRIPT
}

# Install on remote nodes first
install_remote "nexus-master"  "200GB"
install_remote "nexus-ai"      "200GB"
install_remote "nexus-storage" "800GB"

# Install locally (nexus-admin)
install_local

echo ""
echo "=== IPFS Installation Complete ==="
