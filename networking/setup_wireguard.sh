#!/bin/bash
# NEXUS OS WireGuard Full-Mesh Overlay Setup
# Creates encrypted overlay network over BATMAN-adv mesh (or Ethernet fallback)
#
# Usage: sudo ./setup_wireguard.sh <node_number>
#   node_number: 1=master, 2=ai, 3=storage, 4=admin
#
# Phase 1: Run with 'genkeys' on each node to generate keys
# Phase 2: Run with node_number after all keys are distributed
set -e

NODE_NUM="${1:?Usage: $0 <node_number 1-4>}"
WG_DIR="/opt/nexus/networking"
WG_CONF="/etc/wireguard/nexus-mesh.conf"
WG_IP="10.1.0.${NODE_NUM}"
WG_PORT=51820

# Node mapping: node_num -> mesh_ip (BATMAN) and eth_ip (fallback)
declare -A MESH_IPS=([1]="10.0.0.1" [2]="10.0.0.2" [3]="10.0.0.3" [4]="10.0.0.4")
declare -A ETH_IPS=([1]="10.0.20.3" [2]="10.0.20.4" [3]="10.0.20.11" [4]="10.0.10.5")

if [ "$NODE_NUM" = "genkeys" ]; then
    echo "=== Generating WireGuard keys ==="
    umask 077
    wg genkey | tee "${WG_DIR}/wg_private.key" | wg pubkey > "${WG_DIR}/wg_public.key"
    chmod 600 "${WG_DIR}/wg_private.key"
    chmod 644 "${WG_DIR}/wg_public.key"
    echo "Private key: ${WG_DIR}/wg_private.key"
    echo "Public key:  $(cat ${WG_DIR}/wg_public.key)"
    echo ""
    echo "Distribute the public key to all other nodes."
    exit 0
fi

echo "=== NEXUS OS WireGuard Setup (Node ${NODE_NUM}) ==="
echo "WireGuard IP: ${WG_IP}/24"

# Read this node's private key
if [ ! -f "${WG_DIR}/wg_private.key" ]; then
    echo "ERROR: No private key found. Run: sudo $0 genkeys"
    exit 1
fi
PRIVATE_KEY=$(cat "${WG_DIR}/wg_private.key")

# Build WireGuard config
echo "[Interface]" > "${WG_CONF}"
echo "PrivateKey = ${PRIVATE_KEY}" >> "${WG_CONF}"
echo "Address = ${WG_IP}/24" >> "${WG_CONF}"
echo "ListenPort = ${WG_PORT}" >> "${WG_CONF}"
echo "" >> "${WG_CONF}"

# Add peers (all nodes except self)
PEER_KEYS_DIR="${WG_DIR}/peer_keys"
mkdir -p "${PEER_KEYS_DIR}"

for PEER_NUM in 1 2 3 4; do
    [ "${PEER_NUM}" = "${NODE_NUM}" ] && continue

    PEER_KEY_FILE="${PEER_KEYS_DIR}/node${PEER_NUM}.pub"
    if [ ! -f "${PEER_KEY_FILE}" ]; then
        echo "WARNING: Missing public key for node ${PEER_NUM} at ${PEER_KEY_FILE}"
        echo "  Copy it from that node's ${WG_DIR}/wg_public.key"
        continue
    fi

    PEER_PUB=$(cat "${PEER_KEY_FILE}")
    # Use Ethernet IP as endpoint (more reliable than mesh for initial setup)
    PEER_ENDPOINT="${ETH_IPS[$PEER_NUM]}"

    echo "# Node ${PEER_NUM}" >> "${WG_CONF}"
    echo "[Peer]" >> "${WG_CONF}"
    echo "PublicKey = ${PEER_PUB}" >> "${WG_CONF}"
    echo "AllowedIPs = 10.1.0.${PEER_NUM}/32" >> "${WG_CONF}"
    echo "Endpoint = ${PEER_ENDPOINT}:${WG_PORT}" >> "${WG_CONF}"
    echo "PersistentKeepalive = 25" >> "${WG_CONF}"
    echo "" >> "${WG_CONF}"
done

echo "WireGuard config written to ${WG_CONF}"

# Enable and start
systemctl enable wg-quick@nexus-mesh
systemctl restart wg-quick@nexus-mesh

echo ""
echo "=== WireGuard status ==="
wg show nexus-mesh
echo ""
echo "Test connectivity: ping 10.1.0.X (where X is another node)"
