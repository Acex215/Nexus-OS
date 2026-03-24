#!/bin/bash -e
# Stage 5, Step 00: Install NEXUS OS dependencies
# This runs in a chroot of the target filesystem

on_chroot << 'CHEOF'

# System dependencies
apt-get update
apt-get install -y \
  python3-pip python3-venv python3-dev \
  git curl wget jq \
  nfs-common \
  net-tools iproute2 \
  build-essential

# Python packages (NEXUS core)
pip3 install --break-system-packages \
  web3 aiohttp websockets psutil chromadb \
  fastapi uvicorn httpx \
  discord.py pyyaml jsonlines \
  scikit-learn numpy scipy \
  reedsolo pycryptodome \
  zeroconf

# Node.js (for dashboard)
curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
apt-get install -y nodejs

# Geth (Go Ethereum) for ARM64
GETH_VERSION="1.13.15"
wget -q "https://gethstore.blob.core.windows.net/builds/geth-linux-arm64-${GETH_VERSION}-unknown.tar.gz" \
  -O /tmp/geth.tar.gz
tar -xzf /tmp/geth.tar.gz -C /tmp
cp /tmp/geth-linux-arm64-*/geth /usr/local/bin/
chmod +x /usr/local/bin/geth
rm -rf /tmp/geth*

# IPFS
IPFS_VERSION="0.24.0"
wget -q "https://dist.ipfs.tech/kubo/v${IPFS_VERSION}/kubo_v${IPFS_VERSION}_linux-arm64.tar.gz" \
  -O /tmp/ipfs.tar.gz
tar -xzf /tmp/ipfs.tar.gz -C /tmp
cp /tmp/kubo/ipfs /usr/local/bin/
chmod +x /usr/local/bin/ipfs
rm -rf /tmp/kubo /tmp/ipfs.tar.gz

CHEOF
