#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# NEXUS OS — NFS Unified Mount Setup
#
# Sets up /mnt/cluster-storage on all cluster nodes, backed by the
# 1.8TB HDD on nexus-storage (10.0.20.11:/mnt/nexus-nas).
#
# Run from nexus-admin (10.0.10.5). This machine cannot SSH to
# itself, so the local setup runs directly.
#
# Current state (as of script creation):
#   - NFS server already running on nexus-storage, exports exist
#   - nexus-master and nexus-ai have STALE fstab entries using
#     old IP 192.168.8.224 (pre-VLAN migration) — this script fixes them
#   - nexus-admin has a working fstab entry to /mnt/nexus-nas
#
# This script:
#   1. Creates /mnt/nexus-nas/shared on the NFS server
#   2. Adds the shared export if not present
#   3. Fixes stale fstab entries on all client nodes
#   4. Creates /mnt/cluster-storage mount pointing to the shared dir
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

NFS_SERVER="10.0.20.11"
NFS_EXPORT="/mnt/nexus-nas/shared"
MOUNT_POINT="/mnt/cluster-storage"
STALE_IP="192.168.8.224"
SSH_USER="mhuraibi"

# Remote nodes (SSH via VLAN IPs)
# nexus-admin is THIS machine — handled separately (no SSH)
REMOTE_NODES=(
    "nexus-master:10.0.20.3"
    "nexus-ai:10.0.20.4"
)

echo "=== NEXUS NFS Unified Mount Setup ==="
echo "  NFS server:  nexus-storage (${NFS_SERVER})"
echo "  Export:       ${NFS_EXPORT}"
echo "  Mount point:  ${MOUNT_POINT}"
echo ""

# ── Step 1: NFS Server Setup (nexus-storage) ───────────────────────
echo "--- Step 1: NFS server setup (nexus-storage) ---"
ssh ${SSH_USER}@${NFS_SERVER} bash -s "${NFS_EXPORT}" << 'SERVEREOF'
    EXPORT_PATH="$1"

    # nfs-kernel-server is already installed and active, but verify
    if ! systemctl is-active --quiet nfs-kernel-server; then
        sudo apt-get install -y nfs-kernel-server
        sudo systemctl enable nfs-kernel-server
    fi
    echo "  NFS server: active"

    # Create shared directory
    sudo mkdir -p "${EXPORT_PATH}"
    sudo chown mhuraibi:mhuraibi "${EXPORT_PATH}"
    echo "  Created: ${EXPORT_PATH}"

    # Add export for the shared subdirectory if not already present
    if ! grep -q "${EXPORT_PATH}" /etc/exports 2>/dev/null; then
        echo "${EXPORT_PATH} 10.0.20.0/24(rw,sync,no_subtree_check,no_root_squash)" | sudo tee -a /etc/exports
        echo "${EXPORT_PATH} 10.0.10.0/24(rw,sync,no_subtree_check,no_root_squash)" | sudo tee -a /etc/exports
        echo "  Added exports for both VLANs"
    else
        echo "  Export already exists"
    fi

    sudo exportfs -ra
    echo "  Exports refreshed"

    # Verify
    echo "  Current exports:"
    sudo exportfs -v | grep shared | sed 's/^/    /'
SERVEREOF
echo ""

# ── Step 2: Client setup on remote nodes ───────────────────────────
echo "--- Step 2: NFS client setup (remote nodes) ---"
for entry in "${REMOTE_NODES[@]}"; do
    node_name="${entry%%:*}"
    node_ip="${entry##*:}"

    echo ""
    echo "  Setting up ${node_name} (${node_ip})..."

    ssh ${SSH_USER}@${node_ip} bash -s "${NFS_SERVER}" "${NFS_EXPORT}" "${MOUNT_POINT}" "${STALE_IP}" << 'CLIENTEOF'
        NFS_SERVER="$1"
        NFS_EXPORT="$2"
        MOUNT_POINT="$3"
        STALE_IP="$4"

        # Ensure nfs-common is installed
        dpkg -l nfs-common >/dev/null 2>&1 || sudo apt-get install -y nfs-common

        # Fix stale fstab entries using old pre-VLAN IP
        if grep -q "${STALE_IP}" /etc/fstab 2>/dev/null; then
            echo "    Fixing stale fstab entry (${STALE_IP} → ${NFS_SERVER})..."
            sudo sed -i "s|${STALE_IP}|${NFS_SERVER}|g" /etc/fstab
        fi

        # Unmount old broken mounts
        if mountpoint -q /mnt/nexus-nas 2>/dev/null; then
            sudo umount /mnt/nexus-nas 2>/dev/null || true
        fi

        # Create mount point
        sudo mkdir -p "${MOUNT_POINT}"

        # Add fstab entry for cluster-storage if not present
        if ! grep -q "${MOUNT_POINT}" /etc/fstab 2>/dev/null; then
            echo "${NFS_SERVER}:${NFS_EXPORT} ${MOUNT_POINT} nfs defaults,_netdev,soft,timeo=150,retrans=3 0 0" | sudo tee -a /etc/fstab
            echo "    Added fstab entry"
        else
            echo "    fstab entry already exists"
        fi

        # Mount
        if mountpoint -q "${MOUNT_POINT}" 2>/dev/null; then
            echo "    Already mounted"
        else
            if sudo mount "${MOUNT_POINT}"; then
                echo "    Mounted OK"
            else
                echo "    WARNING: Mount failed — check NFS server connectivity"
            fi
        fi
CLIENTEOF
done
echo ""

# ── Step 3: Local setup (nexus-admin — this machine) ───────────────
echo "--- Step 3: NFS client setup (nexus-admin — local) ---"

# Ensure nfs-common is installed
dpkg -l nfs-common >/dev/null 2>&1 || sudo apt-get install -y nfs-common

# Fix stale fstab entries
if grep -q "${STALE_IP}" /etc/fstab 2>/dev/null; then
    echo "  Fixing stale fstab entry (${STALE_IP} → ${NFS_SERVER})..."
    sudo sed -i "s|${STALE_IP}|${NFS_SERVER}|g" /etc/fstab
fi

# Create mount point
sudo mkdir -p "${MOUNT_POINT}"

# Add fstab entry for cluster-storage if not present
if ! grep -q "${MOUNT_POINT}" /etc/fstab 2>/dev/null; then
    echo "${NFS_SERVER}:${NFS_EXPORT} ${MOUNT_POINT} nfs defaults,_netdev,soft,timeo=150,retrans=3 0 0" | sudo tee -a /etc/fstab
    echo "  Added fstab entry"
else
    echo "  fstab entry already exists"
fi

# Mount
if mountpoint -q "${MOUNT_POINT}" 2>/dev/null; then
    echo "  Already mounted"
else
    if sudo mount "${MOUNT_POINT}"; then
        echo "  Mounted OK"
    else
        echo "  WARNING: Mount failed — check NFS server connectivity"
    fi
fi
echo ""

# ── Step 4: Verification ──────────────────────────────────────────
echo "--- Step 4: Verification ---"
echo ""

# Write a test file to verify read/write access
TEST_FILE="${MOUNT_POINT}/.nfs_test_$(hostname)"
if touch "${TEST_FILE}" 2>/dev/null; then
    echo "  nexus-admin: write OK"
    rm -f "${TEST_FILE}"
else
    echo "  nexus-admin: write FAILED"
fi

echo ""
echo "  Mount status:"
# Local
echo -n "    nexus-admin:   "
df -h "${MOUNT_POINT}" 2>/dev/null | tail -1 || echo "NOT MOUNTED"

# Remote nodes
for entry in "${REMOTE_NODES[@]}"; do
    node_name="${entry%%:*}"
    node_ip="${entry##*:}"
    echo -n "    ${node_name}: "
    ssh ${SSH_USER}@${node_ip} "df -h ${MOUNT_POINT} 2>/dev/null | tail -1 || echo 'NOT MOUNTED'"
done

# nexus-storage (server — mount is local)
echo -n "    nexus-storage:  "
ssh ${SSH_USER}@${NFS_SERVER} "df -h /mnt/nexus-nas 2>/dev/null | tail -1 || echo 'NOT MOUNTED'"

echo ""
echo "=== NFS setup complete ==="
echo ""
echo "  All nodes should now have ${MOUNT_POINT} available."
echo "  Backed by 1.8TB HDD on nexus-storage (/mnt/nexus-nas/shared)."
echo ""
echo "  To verify on any node:  ls ${MOUNT_POINT}/"
echo "  To check mounts:        mount | grep cluster-storage"
