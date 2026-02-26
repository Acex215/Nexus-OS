#!/bin/bash
# NEXUS OS IPFS Private Network Configuration
# Run from nexus-admin after IPFS is installed on all nodes
set -euo pipefail

IPFS_PATH="/opt/nexus/ipfs"
SWARM_KEY_PATH="$IPFS_PATH/swarm.key"

MASTER_ID="12D3KooWFmWdJWuYt5RLW89qWT3MjNnBbSEw7hKQpGUuMSbXzgFx"
AI_ID="12D3KooWFj5VeXvu6Aagr9ehpL3qsmtNBxTzzwkJSaYubauhEGzX"
STORAGE_ID="12D3KooWPjmi4v4yEx8WX1Qs3z4xzJoWPqJkkQZ13Khu2q61VmsX"
ADMIN_ID="12D3KooWLfCQcQTVDcKUREMoyJzFoNvSRqsjPFMT3KE9FwixUMEk"

MASTER_ADDR="/ip4/192.168.8.228/tcp/4001/p2p/$MASTER_ID"
AI_ADDR="/ip4/192.168.8.128/tcp/4001/p2p/$AI_ID"
STORAGE_ADDR="/ip4/192.168.8.224/tcp/4001/p2p/$STORAGE_ID"
ADMIN_ADDR="/ip4/192.168.8.153/tcp/4001/p2p/$ADMIN_ID"

REMOTE_NODES=("nexus-master" "nexus-ai" "nexus-storage")

echo "=== NEXUS IPFS Private Network Setup ==="

# Generate swarm key if not exists
if [ ! -f "$SWARM_KEY_PATH" ]; then
    echo "Generating swarm key..."
    echo -e "/key/swarm/psk/1.0.0/\n/base16/\n$(tr -dc 'a-f0-9' < /dev/urandom | head -c64)" > "$SWARM_KEY_PATH"
fi

# Distribute swarm key
for node in "${REMOTE_NODES[@]}"; do
    scp -o StrictHostKeyChecking=no "$SWARM_KEY_PATH" "$node:$SWARM_KEY_PATH"
    echo "$node: swarm.key distributed"
done

# Configure local node
export IPFS_PATH
ipfs bootstrap rm --all
ipfs bootstrap add "$MASTER_ADDR"
ipfs bootstrap add "$AI_ADDR"
ipfs bootstrap add "$STORAGE_ADDR"
ipfs bootstrap add "$ADMIN_ADDR"
ipfs config --json Swarm.EnableAutoRelay false
ipfs config --json Discovery.MDNS.Enabled false
ipfs config --json Routing.Type '"dht"'
echo "nexus-admin: configured"

# Configure remote nodes
for node in "${REMOTE_NODES[@]}"; do
    ssh -o StrictHostKeyChecking=no "$node" "
        export IPFS_PATH=$IPFS_PATH
        ipfs bootstrap rm --all
        ipfs bootstrap add $MASTER_ADDR
        ipfs bootstrap add $AI_ADDR
        ipfs bootstrap add $STORAGE_ADDR
        ipfs bootstrap add $ADMIN_ADDR
        ipfs config --json Swarm.EnableAutoRelay false
        ipfs config --json Discovery.MDNS.Enabled false
        ipfs config --json Routing.Type '\"dht\"'
    " > /dev/null 2>&1
    echo "$node: configured"
done

# Restart all daemons
echo "Restarting IPFS daemons..."
for node in "${REMOTE_NODES[@]}"; do
    ssh -o StrictHostKeyChecking=no "$node" "sudo systemctl restart ipfs" &
done
sudo systemctl restart ipfs &
wait
sleep 10

echo ""
echo "=== Verification ==="
for node in "${REMOTE_NODES[@]}"; do
    UNIQUE=$(ssh -o StrictHostKeyChecking=no "$node" "IPFS_PATH=$IPFS_PATH ipfs swarm peers | grep -oP '/p2p/\K.*' | sort -u | wc -l")
    echo "$node: $UNIQUE unique peers"
done
UNIQUE=$(IPFS_PATH=$IPFS_PATH ipfs swarm peers | grep -oP '/p2p/\K.*' | sort -u | wc -l)
echo "nexus-admin: $UNIQUE unique peers"
echo ""
echo "=== Private network setup complete ==="
