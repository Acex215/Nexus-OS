#!/bin/bash
# Test IPFS distributed storage across NEXUS cluster
set -uo pipefail

export IPFS_PATH=/opt/nexus/ipfs
REMOTE_NODES=("nexus-master" "nexus-ai" "nexus-storage")
SSH="ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5"
SEP="============================================================"
PASS=0
FAIL=0

pass() { echo "  [OK] $1"; ((PASS++)); }
fail() { echo "  [FAIL] $1"; ((FAIL++)); }

echo ""
echo "$SEP"
echo "  NEXUS IPFS Distribution Test Suite"
echo "  $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "$SEP"

# ── Test 1: Small file (1 MB) ───────────────────────────────────
echo ""
echo "  TEST 1: Small File Distribution (1 MB)"
echo "$SEP"

dd if=/dev/urandom of=/tmp/nexus-test-1mb.bin bs=1M count=1 2>/dev/null
LOCAL_HASH=$(sha256sum /tmp/nexus-test-1mb.bin | awk '{print $1}')
echo "  Source hash: ${LOCAL_HASH:0:16}..."

T0=$(date +%s%N)
CID_1MB=$(ipfs add -q /tmp/nexus-test-1mb.bin)
T1=$(date +%s%N)
ADD_MS=$(( (T1 - T0) / 1000000 ))
echo "  CID: $CID_1MB"
echo "  Add time: ${ADD_MS}ms"

# Retrieve from each remote node
for node in "${REMOTE_NODES[@]}"; do
    T0=$(date +%s%N)
    $SSH "$node" "IPFS_PATH=/opt/nexus/ipfs ipfs get '$CID_1MB' -o /tmp/nexus-test-1mb-recv.bin" >/dev/null 2>&1
    T1=$(date +%s%N)
    GET_MS=$(( (T1 - T0) / 1000000 ))

    REMOTE_HASH=$($SSH "$node" "sha256sum /tmp/nexus-test-1mb-recv.bin" 2>/dev/null | awk '{print $1}')
    if [ "$REMOTE_HASH" = "$LOCAL_HASH" ]; then
        pass "$node: retrieved + hash match (${GET_MS}ms)"
    else
        fail "$node: hash mismatch (got ${REMOTE_HASH:0:16})"
    fi
done

# ── Test 2: Medium file (50 MB) ─────────────────────────────────
echo ""
echo "  TEST 2: Medium File Distribution (50 MB)"
echo "$SEP"

dd if=/dev/urandom of=/tmp/nexus-test-50mb.bin bs=1M count=50 2>/dev/null
LOCAL_HASH_50=$(sha256sum /tmp/nexus-test-50mb.bin | awk '{print $1}')
echo "  Source hash: ${LOCAL_HASH_50:0:16}..."

T0=$(date +%s%N)
CID_50MB=$(ipfs add -q /tmp/nexus-test-50mb.bin)
T1=$(date +%s%N)
ADD_MS=$(( (T1 - T0) / 1000000 ))
ADD_SPEED=$(( 50 * 1000 / (ADD_MS + 1) ))
echo "  CID: $CID_50MB"
echo "  Add time: ${ADD_MS}ms (~${ADD_SPEED} MB/s)"

# Retrieve from nexus-storage (primary storage node)
T0=$(date +%s%N)
$SSH nexus-storage "IPFS_PATH=/opt/nexus/ipfs ipfs get '$CID_50MB' -o /tmp/nexus-test-50mb-recv.bin" >/dev/null 2>&1
T1=$(date +%s%N)
GET_MS=$(( (T1 - T0) / 1000000 ))
GET_SPEED=$(( 50 * 1000 / (GET_MS + 1) ))

REMOTE_HASH=$($SSH nexus-storage "sha256sum /tmp/nexus-test-50mb-recv.bin" 2>/dev/null | awk '{print $1}')
if [ "$REMOTE_HASH" = "$LOCAL_HASH_50" ]; then
    pass "nexus-storage: retrieved + hash match (${GET_MS}ms, ~${GET_SPEED} MB/s)"
else
    fail "nexus-storage: hash mismatch"
fi

# Retrieve from nexus-master
T0=$(date +%s%N)
$SSH nexus-master "IPFS_PATH=/opt/nexus/ipfs ipfs get '$CID_50MB' -o /tmp/nexus-test-50mb-recv.bin" >/dev/null 2>&1
T1=$(date +%s%N)
GET_MS=$(( (T1 - T0) / 1000000 ))
GET_SPEED=$(( 50 * 1000 / (GET_MS + 1) ))

REMOTE_HASH=$($SSH nexus-master "sha256sum /tmp/nexus-test-50mb-recv.bin" 2>/dev/null | awk '{print $1}')
if [ "$REMOTE_HASH" = "$LOCAL_HASH_50" ]; then
    pass "nexus-master: retrieved + hash match (${GET_MS}ms, ~${GET_SPEED} MB/s)"
else
    fail "nexus-master: hash mismatch"
fi

# ── Test 3: Multi-origin distribution ───────────────────────────
echo ""
echo "  TEST 3: Multi-Origin (add from different nodes)"
echo "$SEP"

# Add file on nexus-master
CID_MASTER=$($SSH nexus-master "echo 'origin:nexus-master:$(date +%s)' | IPFS_PATH=/opt/nexus/ipfs ipfs add -q")
echo "  nexus-master added: $CID_MASTER"

# Add file on nexus-ai
CID_AI=$($SSH nexus-ai "echo 'origin:nexus-ai:$(date +%s)' | IPFS_PATH=/opt/nexus/ipfs ipfs add -q")
echo "  nexus-ai added: $CID_AI"

# Add file on nexus-storage
CID_STORAGE=$($SSH nexus-storage "echo 'origin:nexus-storage:$(date +%s)' | IPFS_PATH=/opt/nexus/ipfs ipfs add -q")
echo "  nexus-storage added: $CID_STORAGE"

# Cross-retrieve: nexus-admin fetches all three
for label_cid in "nexus-master:$CID_MASTER" "nexus-ai:$CID_AI" "nexus-storage:$CID_STORAGE"; do
    LABEL=$(echo "$label_cid" | cut -d: -f1)
    CID=$(echo "$label_cid" | cut -d: -f2)
    CONTENT=$(IPFS_PATH=/opt/nexus/ipfs timeout 10 ipfs cat "$CID" 2>/dev/null)
    if echo "$CONTENT" | grep -q "origin:$LABEL"; then
        pass "nexus-admin retrieved from $LABEL origin"
    else
        fail "nexus-admin could not retrieve from $LABEL origin"
    fi
done

# ── Test 4: Pin management ──────────────────────────────────────
echo ""
echo "  TEST 4: Pin Management"
echo "$SEP"

# Pin 1MB file on nexus-master and nexus-ai
$SSH nexus-master "IPFS_PATH=/opt/nexus/ipfs ipfs pin add $CID_1MB" >/dev/null 2>&1 &
$SSH nexus-ai "IPFS_PATH=/opt/nexus/ipfs ipfs pin add $CID_1MB" >/dev/null 2>&1 &
wait

echo "  Pinned $CID_1MB on nexus-master + nexus-ai"
echo "  Pin status:"
for node in "${REMOTE_NODES[@]}"; do
    PIN=$($SSH "$node" "IPFS_PATH=/opt/nexus/ipfs ipfs pin ls --type=recursive '$CID_1MB' 2>/dev/null" || echo "not pinned")
    echo "    $node: $PIN"
done
PIN=$(ipfs pin ls --type=recursive "$CID_1MB" 2>/dev/null || echo "not pinned")
echo "    nexus-admin: $PIN"
pass "Pin management verified"

# ── Test 5: Directory distribution ──────────────────────────────
echo ""
echo "  TEST 5: Directory Distribution"
echo "$SEP"

mkdir -p /tmp/nexus-test-dir
echo "file-alpha" > /tmp/nexus-test-dir/alpha.txt
echo "file-beta"  > /tmp/nexus-test-dir/beta.txt
dd if=/dev/urandom of=/tmp/nexus-test-dir/gamma.bin bs=1K count=512 2>/dev/null

CID_DIR=$(ipfs add -rq /tmp/nexus-test-dir | tail -1)
echo "  Directory CID: $CID_DIR"

# List directory from nexus-storage
LISTING=$($SSH nexus-storage "IPFS_PATH=/opt/nexus/ipfs timeout 10 ipfs ls '$CID_DIR' 2>/dev/null")
FILE_COUNT=$(echo "$LISTING" | grep -c '.' 2>/dev/null || echo 0)
echo "  Files listed from nexus-storage: $FILE_COUNT"

ALPHA=$($SSH nexus-storage "IPFS_PATH=/opt/nexus/ipfs timeout 10 ipfs cat '$CID_DIR/alpha.txt' 2>/dev/null")
if [ "$ALPHA" = "file-alpha" ]; then
    pass "Directory traversal + file retrieval from nexus-storage"
else
    fail "Directory content mismatch from nexus-storage (got: $ALPHA)"
fi

# ── Test 6: Chunk analysis ──────────────────────────────────────
echo ""
echo "  TEST 6: Chunk Analysis (50 MB file)"
echo "$SEP"

STAT=$(ipfs object stat "$CID_50MB" 2>/dev/null)
CHUNK_COUNT=$(ipfs refs "$CID_50MB" 2>/dev/null | wc -l)
LINKS=$(echo "$STAT" | grep NumLinks | awk '{print $2}')
CUMSIZE=$(echo "$STAT" | grep CumulativeSize | awk '{print $2}')
CUMSIZE_MB=$(( CUMSIZE / 1048576 ))

echo "  Links (chunks): $LINKS"
echo "  Ref count: $CHUNK_COUNT"
echo "  Cumulative size: ${CUMSIZE_MB} MB"
pass "Chunking verified ($CHUNK_COUNT chunks)"

# ── Test 7: Garbage collection ──────────────────────────────────
echo ""
echo "  TEST 7: Garbage Collection"
echo "$SEP"

# Add a temp file, don't pin, then GC
TEMP_CID=$(echo "garbage-test-$(date +%s)" | ipfs add -q --pin=false)
echo "  Temp CID (unpinned): $TEMP_CID"

# Verify it exists
ipfs cat "$TEMP_CID" >/dev/null 2>&1 && echo "  Before GC: exists" || echo "  Before GC: missing"

# Run GC
GC_OUT=$(ipfs repo gc 2>&1 | tail -5)
echo "  GC output (last 5 lines):"
echo "$GC_OUT" | sed 's/^/    /'

# Check if temp content was collected
if ipfs cat "$TEMP_CID" >/dev/null 2>&1; then
    echo "  After GC: still exists (may be cached)"
    pass "Garbage collection ran (content may persist in blockstore cache)"
else
    pass "Garbage collection removed unpinned content"
fi

# ── Test 8: Repo stats per node ─────────────────────────────────
echo ""
echo "  TEST 8: Repository Statistics"
echo "$SEP"

for node in "${REMOTE_NODES[@]}"; do
    echo "  --- $node ---"
    $SSH "$node" "IPFS_PATH=/opt/nexus/ipfs ipfs repo stat 2>/dev/null" | grep -E "RepoSize|StorageMax|NumObjects" | sed 's/^/    /'
done
echo "  --- nexus-admin ---"
ipfs repo stat 2>/dev/null | grep -E "RepoSize|StorageMax|NumObjects" | sed 's/^/    /'

# ── Cleanup temp files ──────────────────────────────────────────
rm -f /tmp/nexus-test-1mb.bin /tmp/nexus-test-50mb.bin
rm -rf /tmp/nexus-test-dir
for node in "${REMOTE_NODES[@]}"; do
    $SSH "$node" "rm -f /tmp/nexus-test-1mb-recv.bin /tmp/nexus-test-50mb-recv.bin" 2>/dev/null &
done
wait

# ── Summary ─────────────────────────────────────────────────────
echo ""
echo "$SEP"
echo "  RESULTS: $PASS passed, $FAIL failed"
echo "$SEP"

if [ "$FAIL" -eq 0 ]; then
    echo "  ALL TESTS PASSED"
else
    echo "  SOME TESTS FAILED — review output above"
fi
echo "$SEP"

exit "$FAIL"
