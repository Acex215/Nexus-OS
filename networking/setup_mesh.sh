#!/bin/bash
# NEXUS OS BATMAN-adv Mesh Setup
# Configures WiFi ad-hoc (IBSS) + BATMAN-adv mesh networking
# Run on each Pi 5 node (all use Ethernet primary, WiFi for mesh backup)
#
# Usage: sudo ./setup_mesh.sh <node_number>
#   node_number: 1=master, 2=ai, 3=storage, 4=admin
set -e

NODE_NUM="${1:?Usage: $0 <node_number 1-4>}"
MESH_SSID="NexusMesh"
MESH_FREQ=2412  # Channel 1, 2.4GHz
MESH_IP="10.0.0.${NODE_NUM}"
MESH_MASK="/24"

echo "=== NEXUS OS Mesh Setup (Node ${NODE_NUM}) ==="
echo "Mesh IP: ${MESH_IP}${MESH_MASK}"

# 1. Load batman-adv kernel module
echo "[1/6] Loading batman-adv module..."
modprobe batman-adv
if ! grep -q "^batman-adv$" /etc/modules 2>/dev/null; then
    echo "batman-adv" >> /etc/modules
    echo "  Added batman-adv to /etc/modules"
fi

# 2. Unblock WiFi and stop any services using wlan0
echo "[2/6] Preparing wlan0..."
rfkill unblock wifi 2>/dev/null || true
if systemctl is-active --quiet wpa_supplicant 2>/dev/null; then
    systemctl stop wpa_supplicant
fi
if systemctl is-active --quiet NetworkManager 2>/dev/null; then
    nmcli device set wlan0 managed no 2>/dev/null || true
fi

# 3. Configure wlan0 for IBSS (ad-hoc) mode
echo "[3/6] Setting wlan0 to IBSS mode..."
ip link set wlan0 down
iw dev wlan0 set type ibss
ip link set wlan0 up

# 4. Join the mesh IBSS network
echo "[4/6] Joining ${MESH_SSID} on frequency ${MESH_FREQ}..."
iw dev wlan0 ibss join "${MESH_SSID}" "${MESH_FREQ}"

# 5. Add wlan0 to BATMAN-adv and bring up bat0
echo "[5/6] Configuring BATMAN-adv..."
batctl if add wlan0 2>/dev/null || true
ip link set bat0 up
ip addr flush dev bat0
ip addr add "${MESH_IP}${MESH_MASK}" dev bat0

# 6. Verify
echo "[6/6] Verifying mesh..."
echo "  bat0 interface:"
ip addr show bat0 | grep inet
echo "  BATMAN interfaces:"
batctl if
echo "  Originator table (peers):"
batctl o 2>/dev/null || echo "  (no peers yet — run on another node)"
echo ""
echo "=== Mesh setup complete for node ${NODE_NUM} ==="
echo "Mesh IP: ${MESH_IP}"
echo "To check peers: sudo batctl o"
echo "To check neighbors: sudo batctl n"
