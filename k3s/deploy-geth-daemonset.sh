#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# NEXUS OS — Deploy Geth Validator DaemonSet to K3s
#
# MIGRATION from systemd to K3s-managed Geth.
# Run from nexus-admin (10.0.10.5) which has kubectl access.
#
# IMPORTANT: Test on ONE node first before cluster-wide deployment.
# See the rollback section at the bottom of this script.
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DAEMONSET_YAML="${SCRIPT_DIR}/geth-daemonset.yaml"

VALIDATORS=(nexus-master nexus-ai nexus-storage)
VALIDATOR_IPS=(10.0.20.3 10.0.20.4 10.0.20.11)

echo "=== NEXUS Geth DaemonSet Deployment ==="
echo ""

# ── Pre-flight checks ──────────────────────────────────────────────
echo "--- Pre-flight checks ---"

if ! kubectl cluster-info >/dev/null 2>&1; then
    echo "ERROR: kubectl cannot reach the cluster. Is K3s running?"
    exit 1
fi
echo "  Cluster reachable: OK"

if [ ! -f "$DAEMONSET_YAML" ]; then
    echo "ERROR: DaemonSet manifest not found: $DAEMONSET_YAML"
    exit 1
fi
echo "  Manifest found: OK"

# Check that all validator nodes are registered in K3s
for node in "${VALIDATORS[@]}"; do
    if ! kubectl get node "$node" >/dev/null 2>&1; then
        echo "  WARNING: node $node not found in K3s — will be skipped"
    else
        echo "  Node $node: registered"
    fi
done

echo ""

# ── Step 1: Create namespace ───────────────────────────────────────
echo "--- Step 1: Create nexus namespace ---"
kubectl create namespace nexus --dry-run=client -o yaml | kubectl apply -f -
echo ""

# ── Step 2: Label validator nodes ──────────────────────────────────
echo "--- Step 2: Label validator nodes ---"
for node in "${VALIDATORS[@]}"; do
    if kubectl get node "$node" >/dev/null 2>&1; then
        kubectl label nodes "$node" nexus-role=validator --overwrite
        echo "  Labeled $node: nexus-role=validator"
    fi
done
echo ""

# ── Step 3: Stop systemd Geth services ────────────────────────────
echo "--- Step 3: Stop systemd services on validators ---"
echo ""
echo "  *** MANUAL STEP REQUIRED ***"
echo "  Before applying the DaemonSet, stop systemd services:"
echo ""
for i in "${!VALIDATORS[@]}"; do
    node="${VALIDATORS[$i]}"
    ip="${VALIDATOR_IPS[$i]}"
    echo "    ssh mhuraibi@${ip} 'sudo systemctl stop nexus-geth clef && sudo systemctl disable nexus-geth clef'"
done
echo ""
echo "  For single-node testing, stop only the test node."
echo ""
read -p "  Have you stopped the systemd services? [y/N] " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "  Aborting. Stop systemd services first, then re-run."
    exit 1
fi
echo ""

# ── Step 4: Deploy DaemonSet ──────────────────────────────────────
echo "--- Step 4: Apply DaemonSet ---"
kubectl apply -f "$DAEMONSET_YAML"
echo ""

# ── Step 5: Wait for pods ─────────────────────────────────────────
echo "--- Step 5: Waiting for pods (timeout 120s) ---"
kubectl rollout status daemonset/nexus-geth -n nexus --timeout=120s || true
echo ""

# ── Step 6: Verify ────────────────────────────────────────────────
echo "--- Step 6: Verification ---"
echo ""
echo "Pods:"
kubectl get pods -n nexus -l app=nexus-geth -o wide
echo ""
echo "DaemonSet:"
kubectl get daemonset nexus-geth -n nexus
echo ""

# Check peer count on each running pod
echo "Peer connectivity:"
for pod in $(kubectl get pods -n nexus -l app=nexus-geth -o jsonpath='{.items[*].metadata.name}'); do
    node=$(kubectl get pod "$pod" -n nexus -o jsonpath='{.spec.nodeName}')
    # period=0 chain: no blocks produced without pending txs, so just check peer count
    peers=$(kubectl exec -n nexus "$pod" -c geth -- \
        wget -qO- http://127.0.0.1:8545 \
        --post-data='{"jsonrpc":"2.0","method":"net_peerCount","params":[],"id":1}' 2>/dev/null \
        | grep -o '"result":"[^"]*"' | cut -d'"' -f4) || peers="N/A"
    echo "  $pod ($node): peers=$peers"
done

echo ""
echo "=== Deployment complete ==="
echo ""
echo "Monitor logs:  kubectl logs -n nexus -l app=nexus-geth -c geth --tail=50 -f"
echo "Check health:  kubectl get pods -n nexus -l app=nexus-geth"
echo ""
echo "=== ROLLBACK ==="
echo "  kubectl delete -f ${DAEMONSET_YAML}"
echo "  Then re-enable systemd on each validator:"
for i in "${!VALIDATORS[@]}"; do
    ip="${VALIDATOR_IPS[$i]}"
    echo "    ssh mhuraibi@${ip} 'sudo systemctl enable --now clef nexus-geth'"
done
