#!/usr/bin/env bash
# =============================================================================
# NEXUS OS - Phase 1 Infrastructure Validation
# Run from: nexus-admin (10.0.10.5)
# =============================================================================

set -euo pipefail

PASS="✅"
FAIL="❌"
WARN="⚠️"
TOTAL=0
PASSED=0
FAILED=0

# Node definitions
declare -A NODES=(
    [nexus-master]="10.0.20.3"
    [nexus-ai]="10.0.20.4"
    [nexus-storage]="10.0.20.11"
    [nexus-admin]="10.0.10.5"
)

REMOTE_NODES=(nexus-master nexus-ai nexus-storage)
ALL_NODES=(nexus-master nexus-ai nexus-storage nexus-admin)

REQUIRED_PKGS=(git curl wget htop nmap net-tools iperf3 python3 python3-pip python3-venv jq unzip)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
check() {
    TOTAL=$((TOTAL + 1))
    if eval "$2" &>/dev/null; then
        echo "  $PASS $1"
        PASSED=$((PASSED + 1))
    else
        echo "  $FAIL $1"
        FAILED=$((FAILED + 1))
    fi
}

check_output() {
    TOTAL=$((TOTAL + 1))
    local output
    if output=$(eval "$2" 2>&1); then
        echo "  $PASS $1"
        [ -n "${3:-}" ] && echo "       $output"
        PASSED=$((PASSED + 1))
    else
        echo "  $FAIL $1"
        [ -n "${3:-}" ] && echo "       $output"
        FAILED=$((FAILED + 1))
    fi
}

run_remote() {
    local node="$1"; shift
    if [ "$node" = "nexus-admin" ]; then
        bash -c "$*" 2>&1
    else
        ssh -o BatchMode=yes -o ConnectTimeout=10 "mhuraibi@$node" "$*" 2>&1
    fi
}

header() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  $1"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# =============================================================================
echo ""
echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║           NEXUS OS — Phase 1 Infrastructure Validation             ║"
echo "║           $(date '+%Y-%m-%d %H:%M:%S')                                       ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"

# =============================================================================
# 1. NETWORK CONNECTIVITY
# =============================================================================
header "1. NETWORK CONNECTIVITY"

for node in "${ALL_NODES[@]}"; do
    ip="${NODES[$node]}"
    check "Ping $node ($ip)" "ping -c 1 -W 3 $ip"
done

# =============================================================================
# 2. SSH PASSWORDLESS ACCESS
# =============================================================================
header "2. SSH PASSWORDLESS ACCESS"

echo "  From nexus-admin:"
for node in "${REMOTE_NODES[@]}"; do
    check "  → $node" "ssh -o BatchMode=yes -o ConnectTimeout=5 mhuraibi@$node 'true'"
done

echo "  From nexus-master:"
for node in nexus-ai nexus-storage nexus-admin; do
    check "  → $node" "ssh -o BatchMode=yes -o ConnectTimeout=5 mhuraibi@nexus-master 'ssh -o BatchMode=yes -o ConnectTimeout=5 mhuraibi@$node true'"
done

# =============================================================================
# 3. STATIC IP VERIFICATION
# =============================================================================
header "3. STATIC IP ADDRESSES"

for node in "${ALL_NODES[@]}"; do
    expected="${NODES[$node]}"
    actual=$(run_remote "$node" "hostname -I | awk '{print \$1}'" 2>/dev/null || echo "UNREACHABLE")
    TOTAL=$((TOTAL + 1))
    if [ "$actual" = "$expected" ]; then
        echo "  $PASS $node: $actual (correct)"
        PASSED=$((PASSED + 1))
    else
        echo "  $FAIL $node: got $actual, expected $expected"
        FAILED=$((FAILED + 1))
    fi
done

# =============================================================================
# 4. /etc/hosts VERIFICATION
# =============================================================================
header "4. /etc/hosts ENTRIES"

for node in "${ALL_NODES[@]}"; do
    missing=""
    for target in "${ALL_NODES[@]}"; do
        if ! run_remote "$node" "grep -q '${NODES[$target]}.*$target' /etc/hosts" 2>/dev/null; then
            missing="$missing $target"
        fi
    done
    TOTAL=$((TOTAL + 1))
    if [ -z "$missing" ]; then
        echo "  $PASS $node: all entries present"
        PASSED=$((PASSED + 1))
    else
        echo "  $FAIL $node: missing entries for:$missing"
        FAILED=$((FAILED + 1))
    fi
done

# =============================================================================
# 5. K3s CLUSTER STATUS
# =============================================================================
header "5. K3s CLUSTER"

k3s_installed=false
if run_remote "nexus-master" "which kubectl" &>/dev/null || run_remote "nexus-admin" "which kubectl" &>/dev/null; then
    k3s_installed=true
fi

if $k3s_installed; then
    for node in "${ALL_NODES[@]}"; do
        status=$(run_remote "nexus-master" "kubectl get node $node -o jsonpath='{.status.conditions[-1].type}' 2>/dev/null" || echo "NotFound")
        TOTAL=$((TOTAL + 1))
        if [ "$status" = "Ready" ]; then
            echo "  $PASS $node: Ready"
            PASSED=$((PASSED + 1))
        else
            echo "  $FAIL $node: $status"
            FAILED=$((FAILED + 1))
        fi
    done
else
    echo "  $WARN K3s not yet installed (Phase 2)"
    echo "       Skipping cluster checks"
fi

# =============================================================================
# 6. ESSENTIAL PACKAGES
# =============================================================================
header "6. ESSENTIAL PACKAGES"

for node in "${ALL_NODES[@]}"; do
    missing=""
    for pkg in "${REQUIRED_PKGS[@]}"; do
        if ! run_remote "$node" "dpkg -s $pkg" &>/dev/null; then
            missing="$missing $pkg"
        fi
    done
    TOTAL=$((TOTAL + 1))
    if [ -z "$missing" ]; then
        echo "  $PASS $node: all ${#REQUIRED_PKGS[@]} packages installed"
        PASSED=$((PASSED + 1))
    else
        echo "  $FAIL $node: missing:$missing"
        FAILED=$((FAILED + 1))
    fi
done

# Versions from one node
echo ""
echo "  Package versions (nexus-admin):"
echo "    git:     $(git --version 2>/dev/null | awk '{print $3}')"
echo "    curl:    $(curl --version 2>/dev/null | head -1 | awk '{print $2}')"
echo "    python3: $(python3 --version 2>/dev/null | awk '{print $2}')"

# =============================================================================
# 7. AI HAT+ (Hailo) ON nexus-ai
# =============================================================================
header "7. AI HAT+ (HAILO) — nexus-ai"

hailo_info=$(run_remote "nexus-ai" "hailortcli fw-control identify 2>&1" || echo "NOT_DETECTED")

TOTAL=$((TOTAL + 1))
if echo "$hailo_info" | grep -qi "hailo"; then
    board=$(echo "$hailo_info" | grep "Board Name" | awk -F: '{print $2}' | xargs)
    arch=$(echo "$hailo_info" | grep "Device Architecture" | awk -F: '{print $2}' | xargs)
    fw=$(echo "$hailo_info" | grep "Firmware Version" | awk -F: '{print $2}' | awk '{print $1}')
    echo "  $PASS Hailo device detected"
    echo "       Board: $board | Arch: $arch | FW: $fw"
    PASSED=$((PASSED + 1))
else
    echo "  $FAIL Hailo device NOT detected"
    FAILED=$((FAILED + 1))
fi

TOTAL=$((TOTAL + 1))
pcie_speed=$(run_remote "nexus-ai" "sudo lspci -vv -s 0001:01:00.0 2>&1 | grep 'LnkSta:'" || echo "UNKNOWN")
if echo "$pcie_speed" | grep -q "8GT/s"; then
    echo "  $PASS PCIe Gen 3 active (8GT/s)"
    PASSED=$((PASSED + 1))
else
    echo "  $FAIL PCIe not at Gen 3 speed"
    echo "       $pcie_speed"
    FAILED=$((FAILED + 1))
fi

TOTAL=$((TOTAL + 1))
if run_remote "nexus-ai" "lspci | grep -qi hailo"; then
    lspci_line=$(run_remote "nexus-ai" "lspci | grep -i hailo")
    echo "  $PASS lspci: $lspci_line"
    PASSED=$((PASSED + 1))
else
    echo "  $FAIL Hailo not visible in lspci"
    FAILED=$((FAILED + 1))
fi

# =============================================================================
# 8. NAS STORAGE (NFS)
# =============================================================================
header "8. NAS STORAGE (NFS MOUNTS)"

# Check NFS server
TOTAL=$((TOTAL + 1))
if run_remote "nexus-storage" "sudo systemctl is-active nfs-kernel-server" | grep -q "active"; then
    echo "  $PASS NFS server running on nexus-storage"
    PASSED=$((PASSED + 1))
else
    echo "  $FAIL NFS server not running on nexus-storage"
    FAILED=$((FAILED + 1))
fi

# Check mount on each node
for node in "${ALL_NODES[@]}"; do
    TOTAL=$((TOTAL + 1))
    if run_remote "$node" "mountpoint -q /mnt/nexus-nas" 2>/dev/null; then
        size=$(run_remote "$node" "df -h /mnt/nexus-nas | tail -1 | awk '{print \$2}'")
        avail=$(run_remote "$node" "df -h /mnt/nexus-nas | tail -1 | awk '{print \$4}'")
        echo "  $PASS $node: /mnt/nexus-nas mounted (${size} total, ${avail} free)"
        PASSED=$((PASSED + 1))
    else
        echo "  $FAIL $node: /mnt/nexus-nas NOT mounted"
        FAILED=$((FAILED + 1))
    fi
done

# Check write permissions
TOTAL=$((TOTAL + 1))
testfile="/mnt/nexus-nas/.validate-test-$$"
if touch "$testfile" 2>/dev/null && rm -f "$testfile" 2>/dev/null; then
    echo "  $PASS Write permissions OK on NAS"
    PASSED=$((PASSED + 1))
else
    echo "  $FAIL Cannot write to /mnt/nexus-nas"
    FAILED=$((FAILED + 1))
fi

# Check subdirectories
TOTAL=$((TOTAL + 1))
expected_dirs="agents backups blockchain shared"
missing_dirs=""
for d in $expected_dirs; do
    if ! run_remote "nexus-storage" "test -d /mnt/nexus-nas/$d"; then
        missing_dirs="$missing_dirs $d"
    fi
done
if [ -z "$missing_dirs" ]; then
    echo "  $PASS NAS subdirectories present: $expected_dirs"
    PASSED=$((PASSED + 1))
else
    echo "  $FAIL Missing NAS subdirectories:$missing_dirs"
    FAILED=$((FAILED + 1))
fi

# =============================================================================
# 9. GETH BLOCKCHAIN — nexus-master
# =============================================================================
header "9. GETH BLOCKCHAIN — nexus-master"

TOTAL=$((TOTAL + 1))
geth_status=$(run_remote "nexus-master" "sudo systemctl is-active nexus-geth" 2>/dev/null || echo "inactive")
if [ "$geth_status" = "active" ]; then
    uptime_info=$(run_remote "nexus-master" "sudo systemctl show nexus-geth --property=ActiveEnterTimestamp" | cut -d= -f2)
    echo "  $PASS Geth service active (since $uptime_info)"
    PASSED=$((PASSED + 1))
else
    echo "  $FAIL Geth service: $geth_status"
    FAILED=$((FAILED + 1))
fi

TOTAL=$((TOTAL + 1))
block_hex=$(run_remote "nexus-master" 'curl -s -X POST -H "Content-Type: application/json" --data "{\"jsonrpc\":\"2.0\",\"method\":\"eth_blockNumber\",\"params\":[],\"id\":1}" http://localhost:8545 2>/dev/null | jq -r ".result"' || echo "0x0")
if [ -n "$block_hex" ] && [ "$block_hex" != "null" ] && [ "$block_hex" != "0x0" ]; then
    block_dec=$((block_hex))
    echo "  $PASS Block height: $block_dec (${block_hex})"
    PASSED=$((PASSED + 1))
else
    echo "  $FAIL Cannot query block height (RPC may be down)"
    FAILED=$((FAILED + 1))
fi

TOTAL=$((TOTAL + 1))
chain_size=$(run_remote "nexus-master" "du -sh /opt/nexus/blockchain/ | awk '{print \$1}'" 2>/dev/null || echo "UNKNOWN")
if run_remote "nexus-master" "test -d /opt/nexus/blockchain/data"; then
    echo "  $PASS Blockchain data directory intact ($chain_size)"
    PASSED=$((PASSED + 1))
else
    echo "  $FAIL Blockchain data directory missing"
    FAILED=$((FAILED + 1))
fi

TOTAL=$((TOTAL + 1))
wallet=$(run_remote "nexus-master" "cat /opt/nexus/blockchain/wallet-address.txt 2>/dev/null" || echo "NOT_FOUND")
if [ "$wallet" != "NOT_FOUND" ] && [ -n "$wallet" ]; then
    echo "  $PASS Wallet: $wallet"
    PASSED=$((PASSED + 1))
else
    echo "  $FAIL Wallet address file not found"
    FAILED=$((FAILED + 1))
fi

# =============================================================================
# 10. NVMe DRIVES
# =============================================================================
header "10. NVMe / STORAGE DRIVES"

# nexus-master NVMe
TOTAL=$((TOTAL + 1))
if run_remote "nexus-master" "test -b /dev/nvme0n1"; then
    nvme_info=$(run_remote "nexus-master" "lsblk /dev/nvme0n1 -o NAME,SIZE,MOUNTPOINT -n | head -3")
    root_usage=$(run_remote "nexus-master" "df -h / | tail -1 | awk '{print \$3\"/\"\$2\" (\"\$5\" used)\"}'")
    echo "  $PASS nexus-master NVMe detected"
    echo "       Root usage: $root_usage"
    PASSED=$((PASSED + 1))
else
    echo "  $FAIL nexus-master NVMe not detected"
    FAILED=$((FAILED + 1))
fi

# nexus-storage drive
TOTAL=$((TOTAL + 1))
if run_remote "nexus-storage" "test -b /dev/sda1"; then
    stor_usage=$(run_remote "nexus-storage" "df -h /mnt/nexus-nas | tail -1 | awk '{print \$3\"/\"\$2\" (\"\$5\" used)\"}'")
    echo "  $PASS nexus-storage 2TB drive detected"
    echo "       NAS usage: $stor_usage"
    PASSED=$((PASSED + 1))
else
    echo "  $FAIL nexus-storage drive not detected"
    FAILED=$((FAILED + 1))
fi

# =============================================================================
# SUMMARY
# =============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
if [ "$FAILED" -eq 0 ]; then
    echo "  $PASS ALL CHECKS PASSED: $PASSED/$TOTAL"
else
    echo "  RESULTS: $PASSED passed, $FAILED failed out of $TOTAL checks"
fi
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
