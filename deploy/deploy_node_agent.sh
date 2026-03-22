#!/bin/bash
# Deploy node_agent.py to all cluster nodes and start the service.
# Usage: ./deploy_node_agent.sh [--no-blockchain]
#
# Run from nexus-admin (10.0.10.5), which hosts the Gateway.
# nexus-admin is listed last and is OPTIONAL — it can also run a node agent
# to register itself with the Gateway, but it is not required.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTS_DIR="/opt/nexus/agents"
SERVICE_NAME="node-agent"
SERVICE_FILE="node-agent.service"

# Files to copy to each node's /opt/nexus/agents/
AGENT_FILES=(
    "node_agent.py"
    "token_hooks.py"
    "gateway_protocol.py"
)

# Cluster nodes (VLAN 20). nexus-admin is optional — uncomment to register it too.
NODES=(
    "nexus-master"
    "nexus-ai"
    "nexus-ai2"
    "nexus-storage"
    # "nexus-admin"   # optional: register the gateway host as a node
)

# Pass --no-blockchain to skip on-chain registration (useful before contracts are deployed)
EXTRA_ARGS="${1:-}"

# ── Colours ────────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC}  $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }
info() { echo -e "${YELLOW}[INFO]${NC} $*"; }

# ── SSH connectivity pre-check ─────────────────────────────────────────────────
echo ""
info "Verifying SSH access to all nodes..."
ALL_REACHABLE=true
for node in "${NODES[@]}"; do
    if ssh -o ConnectTimeout=5 -o BatchMode=yes "$node" "echo OK" &>/dev/null; then
        ok "$node reachable"
    else
        fail "$node unreachable — skipping"
        ALL_REACHABLE=false
    fi
done

if [[ "$ALL_REACHABLE" == false ]]; then
    echo ""
    info "Some nodes unreachable. Proceeding with reachable nodes only."
fi

# ── Deploy to each node ────────────────────────────────────────────────────────
echo ""
info "Starting deployment..."
PASS=0
FAIL=0

for node in "${NODES[@]}"; do
    echo ""
    echo "── $node ────────────────────────────────────────────"

    # Skip if unreachable
    if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$node" "echo OK" &>/dev/null; then
        fail "$node: unreachable, skipping"
        (( FAIL++ )) || true
        continue
    fi

    # a. Ensure target directory exists on remote
    if ! ssh "$node" "mkdir -p ${AGENTS_DIR}"; then
        fail "$node: could not create ${AGENTS_DIR}"
        (( FAIL++ )) || true
        continue
    fi

    # b. Copy agent files
    info "Copying agent files..."
    COPY_FAILED=false
    for f in "${AGENT_FILES[@]}"; do
        if [[ ! -f "${AGENTS_DIR}/${f}" ]]; then
            fail "$node: source file not found: ${AGENTS_DIR}/${f}"
            COPY_FAILED=true
            break
        fi
        if ! scp -q "${AGENTS_DIR}/${f}" "${node}:${AGENTS_DIR}/${f}"; then
            fail "$node: scp failed for $f"
            COPY_FAILED=true
            break
        fi
    done
    [[ "$COPY_FAILED" == true ]] && { (( FAIL++ )) || true; continue; }
    ok "$node: agent files copied"

    # c. Copy .env (contains GATEWAY_AUTH_TOKEN and other secrets)
    if [[ -f "${AGENTS_DIR}/.env" ]]; then
        if ! scp -q "${AGENTS_DIR}/.env" "${node}:${AGENTS_DIR}/.env"; then
            fail "$node: scp failed for .env"
            (( FAIL++ )) || true
            continue
        fi
        ok "$node: .env copied"
    else
        info "$node: no .env found at ${AGENTS_DIR}/.env — skipping"
    fi

    # d. Install systemd service
    info "Installing systemd service..."
    SERVICE_SRC="${SCRIPT_DIR}/${SERVICE_FILE}"
    if [[ ! -f "$SERVICE_SRC" ]]; then
        fail "$node: service file not found: ${SERVICE_SRC}"
        (( FAIL++ )) || true
        continue
    fi

    # Always inject --hostname <dns-name> so Gateway identifies nodes by their
    # DNS/deploy name rather than the system hostname (which may differ, e.g. "AI" vs "nexus-ai").
    EXEC_LINE="ExecStart=/usr/bin/python3 ${AGENTS_DIR}/node_agent.py --hostname ${node}${EXTRA_ARGS:+ ${EXTRA_ARGS}}"
    MODIFIED_SERVICE=$(sed "s|^ExecStart=.*|${EXEC_LINE}|" "$SERVICE_SRC")
    echo "$MODIFIED_SERVICE" | ssh "$node" "cat > /tmp/${SERVICE_FILE}"

    if ! ssh "$node" "sudo mv /tmp/${SERVICE_FILE} /etc/systemd/system/${SERVICE_FILE}"; then
        fail "$node: could not install service file"
        (( FAIL++ )) || true
        continue
    fi
    ok "$node: service file installed"

    # e. Reload, enable, (re)start
    info "Enabling and starting ${SERVICE_NAME}..."
    if ! ssh "$node" "sudo systemctl daemon-reload && \
                      sudo systemctl enable ${SERVICE_NAME} && \
                      sudo systemctl restart ${SERVICE_NAME}"; then
        fail "$node: systemctl enable/start failed"
        (( FAIL++ )) || true
        continue
    fi

    # f. Verify: show first 5 lines of status
    echo ""
    ssh "$node" "systemctl status ${SERVICE_NAME} --no-pager | head -5" || true
    echo ""

    ok "$node: deployment successful"
    (( PASS++ )) || true
done

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════"
echo "  Deployment complete"
echo "  Passed : ${PASS}"
echo "  Failed : ${FAIL}"
echo "════════════════════════════════════════"

[[ "$FAIL" -eq 0 ]]
