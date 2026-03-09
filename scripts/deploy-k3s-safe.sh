#!/bin/bash
set -e

echo "=== NEXUS OS K3s Cluster Deployment (Safe Mode) ==="
echo "This script preserves existing Geth blockchain on nexus-master"
echo ""

# Step 1: Create directories on all nodes (preserve existing blockchain)
echo "--- Creating /opt/nexus directories ---"
for node in nexus-master nexus-ai nexus-storage; do
  echo "Setting up $node..."
  ssh mhuraibi@$node 'sudo mkdir -p /opt/nexus/{scripts,configs,agents} && sudo chown -R mhuraibi:mhuraibi /opt/nexus'
done
echo "Local admin..."
sudo mkdir -p /opt/nexus/{scripts,configs,agents}
sudo chown -R mhuraibi:mhuraibi /opt/nexus
echo ""

# Step 2: Check if K3s needs installation on master
echo "--- Checking K3s status on nexus-master ---"
if ssh mhuraibi@nexus-master 'sudo systemctl is-active k3s' > /dev/null 2>&1; then
  echo "K3s master is already running, skipping installation"
  echo "Getting existing join token..."
else
  echo "K3s master not running, reinstalling..."
  ssh mhuraibi@nexus-master 'curl -sfL https://get.k3s.io | sh -s - server --node-name nexus-master --write-kubeconfig-mode 644 --disable traefik'
  echo "Waiting for master to initialize (60 seconds)..."
  sleep 60
fi

# Step 3: Get join token
echo "--- Getting join token from master ---"
K3S_TOKEN=$(ssh mhuraibi@nexus-master 'sudo cat /var/lib/rancher/k3s/server/node-token')
echo "Token retrieved: ${K3S_TOKEN:0:20}..."
echo ""

# Step 4: Join workers (or rejoin if already installed)
echo "--- Joining worker nodes ---"
for node in nexus-ai nexus-storage nexus-admin; do
  echo "Joining $node..."
  ssh mhuraibi@$node "curl -sfL https://get.k3s.io | K3S_URL=https://10.0.20.3:6443 K3S_TOKEN='$K3S_TOKEN' sh -s - agent --node-name $node"
done

# Wait for workers to join
echo "Waiting for workers to join (30 seconds)..."
sleep 30

# Step 5: Label nodes
echo "--- Labeling nodes by role ---"
ssh mhuraibi@nexus-master 'sudo kubectl label node nexus-master role=blockchain --overwrite'
ssh mhuraibi@nexus-master 'sudo kubectl label node nexus-ai role=ai-inference --overwrite'
ssh mhuraibi@nexus-master 'sudo kubectl label node nexus-storage role=storage --overwrite'
ssh mhuraibi@nexus-master 'sudo kubectl label node nexus-admin role=admin --overwrite'

# Step 6: Verify cluster
echo ""
echo "=== K3s Cluster Status ==="
ssh mhuraibi@nexus-master 'sudo kubectl get nodes -o wide'
echo ""

# Step 7: Verify Geth is still running
echo "=== Geth Blockchain Status ==="
ssh mhuraibi@nexus-master 'sudo systemctl status nexus-geth --no-pager | head -10'
echo ""
echo "=== Deployment Complete ==="
