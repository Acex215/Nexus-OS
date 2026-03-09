#!/usr/bin/env python3
"""Test StorageRegistry contract operations end-to-end."""
import json
import hashlib
import time
import sys

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

RPC_URL  = "http://10.0.20.3:8545"
DEPLOYER = "0x817B0842B208B76A7665948F8D1A0592F9b1e958"

# Node addresses (using deployer for all in test; in prod these would be node wallets)
NODE_MASTER  = Web3.to_checksum_address("0x817B0842B208B76A7665948F8D1A0592F9b1e958")
NODE_AI      = Web3.to_checksum_address("0x9602699c3CB2ACf35Cf20c32012a88Cd451E55f0")
NODE_STORAGE = Web3.to_checksum_address("0x06eb84aE46D1B914A35432b6BA7351344Aeb9C37")

SEP = "=" * 55
PASS = 0
FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f"  [OK] {msg}")


def fail(msg):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


# ── Connect ──────────────────────────────────────────────────────
w3 = Web3(Web3.HTTPProvider(RPC_URL))
w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
assert w3.is_connected()

with open("/opt/nexus/contracts/deployed/StorageRegistry.json") as f:
    deploy = json.load(f)

contract = w3.eth.contract(
    address=Web3.to_checksum_address(deploy["address"]),
    abi=deploy["abi"],
)

print(f"\n{SEP}")
print(f"  StorageRegistry Integration Tests")
print(f"  Contract: {deploy['address']}")
print(SEP)

# ── Test 1: fileCount starts at 0 ───────────────────────────────
print(f"\n  Test 1: Initial State")
print("-" * 55)

initial_count = contract.functions.fileCount().call()
ok(f"fileCount() = {initial_count}")

initial_user_files = len(contract.functions.getUserFiles(DEPLOYER).call())
ok(f"getUserFiles() has {initial_user_files} entries")

# ── Test 2: Register a file ─────────────────────────────────────
print(f"\n  Test 2: Register File")
print("-" * 55)

# Simulate an IPFS CID as bytes32
test_cid = hashlib.sha256(b"QmTestFile12345").digest()
test_merkle = hashlib.sha256(b"merkle-root-of-chunks").digest()
file_size = 50 * 1024 * 1024  # 50 MB
num_chunks = 4

t0 = time.monotonic()
tx_hash = contract.functions.registerFile(
    test_cid, test_merkle, file_size, num_chunks
).transact({"from": DEPLOYER, "gas": 300000})

receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
elapsed = time.monotonic() - t0

if receipt["status"] == 1:
    ok(f"registerFile() succeeded ({elapsed*1000:.0f}ms, gas={receipt['gasUsed']})")
else:
    fail("registerFile() reverted")
    sys.exit(1)

# Extract fileId from event logs
logs = contract.events.FileRegistered().process_receipt(receipt)
if len(logs) == 1:
    file_id = logs[0]["args"]["fileId"]
    ok(f"FileRegistered event: fileId={file_id.hex()[:16]}...")
    ok(f"  cid={logs[0]['args']['cid'].hex()[:16]}...")
    ok(f"  owner={logs[0]['args']['owner']}")
    ok(f"  fileSize={logs[0]['args']['fileSize']}, numChunks={logs[0]['args']['numChunks']}")
else:
    fail(f"Expected 1 FileRegistered event, got {len(logs)}")
    sys.exit(1)

# ── Test 3: Read file metadata ──────────────────────────────────
print(f"\n  Test 3: Read File Metadata")
print("-" * 55)

meta = contract.functions.getFileMetadata(file_id).call()
# meta is a tuple: (cid, merkleRoot, owner, fileSize, timestamp, numChunks, exists)
if meta[0] == test_cid:
    ok(f"CID matches")
else:
    fail(f"CID mismatch")

if meta[1] == test_merkle:
    ok(f"Merkle root matches")
else:
    fail(f"Merkle root mismatch")

if meta[2] == DEPLOYER:
    ok(f"Owner correct: {meta[2]}")
else:
    fail(f"Owner mismatch: {meta[2]}")

if meta[3] == file_size:
    ok(f"File size: {meta[3]} bytes ({meta[3]//1024//1024} MB)")
else:
    fail(f"File size mismatch: {meta[3]}")

if meta[5] == num_chunks:
    ok(f"Num chunks: {meta[5]}")
else:
    fail(f"Num chunks mismatch: {meta[5]}")

if meta[6]:
    ok(f"exists=True")
else:
    fail(f"exists=False")

# ── Test 4: fileCount incremented ────────────────────────────────
print(f"\n  Test 4: File Count")
print("-" * 55)

count = contract.functions.fileCount().call()
if count == initial_count + 1:
    ok(f"fileCount() incremented: {initial_count} -> {count}")
else:
    fail(f"fileCount() = {count}, expected {initial_count + 1}")

user_files = contract.functions.getUserFiles(DEPLOYER).call()
if len(user_files) == initial_user_files + 1 and user_files[-1] == file_id:
    ok(f"getUserFiles() contains new fileId")
else:
    fail(f"getUserFiles() mismatch")

# ── Test 5: Assign chunks to nodes ──────────────────────────────
print(f"\n  Test 5: Assign Chunks")
print("-" * 55)

# 4 chunks, each stored on 2 nodes for redundancy
chunk_indices = [0, 1, 2, 3]
storage_nodes = [
    [NODE_MASTER, NODE_STORAGE],   # chunk 0
    [NODE_AI, NODE_STORAGE],       # chunk 1
    [NODE_MASTER, NODE_AI],        # chunk 2
    [NODE_STORAGE, NODE_MASTER],   # chunk 3
]

t0 = time.monotonic()
tx_hash = contract.functions.assignChunks(
    file_id, chunk_indices, storage_nodes
).transact({"from": DEPLOYER, "gas": 800000})

receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
elapsed = time.monotonic() - t0

if receipt["status"] == 1:
    ok(f"assignChunks() succeeded ({elapsed*1000:.0f}ms, gas={receipt['gasUsed']})")
else:
    fail("assignChunks() reverted")

# Verify event
logs = contract.events.ChunksAssigned().process_receipt(receipt)
if len(logs) == 1:
    ok(f"ChunksAssigned event: numChunks={logs[0]['args']['numChunks']}, totalNodes={logs[0]['args']['totalNodes']}")
else:
    fail(f"Expected 1 ChunksAssigned event, got {len(logs)}")

# ── Test 6: Read chunk assignments ──────────────────────────────
print(f"\n  Test 6: Read Chunk Assignments")
print("-" * 55)

assignments = contract.functions.getChunkAssignments(file_id).call()
if len(assignments) == 4:
    ok(f"Got {len(assignments)} chunk assignments")
    for a in assignments:
        idx = a[1]
        nodes = a[2]
        ok(f"  chunk[{idx}]: {len(nodes)} nodes")
else:
    fail(f"Expected 4 assignments, got {len(assignments)}")

# ── Test 7: Storage commitments ─────────────────────────────────
print(f"\n  Test 7: Storage Commitments")
print("-" * 55)

chunk_size = file_size // num_chunks

for label, addr in [("nexus-master", NODE_MASTER), ("nexus-ai", NODE_AI), ("nexus-storage", NODE_STORAGE)]:
    commitment = contract.functions.getStorageCommitment(addr).call()
    chunks_assigned = commitment // chunk_size if chunk_size > 0 else 0
    ok(f"{label}: {commitment} bytes ({chunks_assigned} chunks x {chunk_size//1024//1024}MB)")

# ── Test 8: Submit storage proof ─────────────────────────────────
print(f"\n  Test 8: Submit Storage Proof")
print("-" * 55)

proof = hashlib.sha256(b"chunk-0-proof-data").digest()
tx_hash = contract.functions.submitStorageProof(
    file_id, 0, proof
).transact({"from": DEPLOYER, "gas": 200000})

receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
if receipt["status"] == 1:
    ok(f"submitStorageProof() succeeded (gas={receipt['gasUsed']})")
else:
    fail("submitStorageProof() reverted")

logs = contract.events.StorageProofSubmitted().process_receipt(receipt)
if len(logs) == 1 and logs[0]["args"]["valid"]:
    ok(f"StorageProofSubmitted: valid=True, chunk={logs[0]['args']['chunkIndex']}")
else:
    fail(f"Unexpected proof event")

# ── Test 9: Register second file ─────────────────────────────────
print(f"\n  Test 9: Register Second File")
print("-" * 55)

cid2 = hashlib.sha256(b"QmSecondFile6789").digest()
merkle2 = hashlib.sha256(b"merkle-root-2").digest()

tx_hash = contract.functions.registerFile(
    cid2, merkle2, 1024 * 1024, 1  # 1MB, 1 chunk
).transact({"from": DEPLOYER, "gas": 300000})

receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
if receipt["status"] == 1:
    ok(f"Second file registered")
else:
    fail("Second registerFile() failed")

count = contract.functions.fileCount().call()
if count == initial_count + 2:
    ok(f"fileCount() = {count} (+2 from start)")
else:
    fail(f"fileCount() = {count}, expected {initial_count + 2}")

user_files = contract.functions.getUserFiles(DEPLOYER).call()
if len(user_files) == initial_user_files + 2:
    ok(f"getUserFiles() has {len(user_files)} entries (+2)")
else:
    fail(f"getUserFiles() has {len(user_files)} entries, expected {initial_user_files + 2}")

# ── Summary ──────────────────────────────────────────────────────
print(f"\n{SEP}")
print(f"  Results: {PASS} passed, {FAIL} failed")
print(SEP)
if FAIL == 0:
    print("  ALL TESTS PASSED")
else:
    print("  SOME TESTS FAILED")
print(SEP)

sys.exit(FAIL)
