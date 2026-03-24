#!/bin/bash
# pi-gen stage: Install NEXUS OS base dependencies
# This runs inside the chroot during image build

apt-get update
apt-get install -y python3-pip git curl

# Geth
# (add Geth install commands for ARM64)

# IPFS
# (add IPFS install commands for ARM64)

# Python dependencies
pip3 install --break-system-packages web3 aiohttp websockets psutil chromadb

# K3s (installed at first boot, not in image)
curl -sfL https://get.k3s.io -o /opt/nexus/install-k3s.sh
chmod +x /opt/nexus/install-k3s.sh
