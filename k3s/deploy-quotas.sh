#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# NEXUS OS — Deploy Agent Tier Resource Quotas
#
# Creates per-tier namespaces and applies resource quotas.
# Run from nexus-admin (10.0.10.5) which has kubectl access.
#
# NOTE: These quotas are for FUTURE use when agents are containerized.
# The agent hierarchy currently runs as hierarchy_manager.py.
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUOTAS_YAML="${SCRIPT_DIR}/resource-quotas.yaml"

echo "=== NEXUS Agent Tier Resource Quotas ==="
echo ""

# Pre-flight
if ! kubectl cluster-info >/dev/null 2>&1; then
    echo "ERROR: kubectl cannot reach the cluster."
    exit 1
fi

if [ ! -f "$QUOTAS_YAML" ]; then
    echo "ERROR: Quotas manifest not found: $QUOTAS_YAML"
    exit 1
fi

# Create namespaces
echo "--- Creating namespaces ---"
for ns in nexus-csuite nexus-directors nexus-workers; do
    kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f -
    echo "  $ns: OK"
done
echo ""

# Apply quotas
echo "--- Applying resource quotas ---"
kubectl apply -f "$QUOTAS_YAML"
echo ""

# Verify
echo "--- Verification ---"
for ns in nexus-csuite nexus-directors nexus-workers; do
    echo ""
    echo "  Namespace: $ns"
    kubectl get resourcequota -n "$ns" -o custom-columns=\
NAME:.metadata.name,\
REQ_CPU:.spec.hard.requests\\.cpu,\
LIM_CPU:.spec.hard.limits\\.cpu,\
REQ_MEM:.spec.hard.requests\\.memory,\
LIM_MEM:.spec.hard.limits\\.memory,\
PODS:.spec.hard.pods
done

echo ""
echo "=== Done ==="
echo ""
echo "To check current usage against quotas:"
echo "  kubectl describe resourcequota -n nexus-csuite"
echo "  kubectl describe resourcequota -n nexus-directors"
echo "  kubectl describe resourcequota -n nexus-workers"
