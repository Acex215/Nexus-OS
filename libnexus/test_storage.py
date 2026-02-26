#!/usr/bin/env python3
"""End-to-end test for NEXUS Storage library."""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/nexus/libnexus")
from nexus_storage import NexusStorage

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


def test_all():
    global PASS, FAIL

    print(f"\n{SEP}")
    print("  NEXUS Storage End-to-End Test")
    print(SEP)

    storage = NexusStorage()

    # ── Test 1: Upload small file ────────────────────────────────
    print(f"\n  TEST 1: Upload (1 MB random file)")
    print("-" * 55)

    test_file = Path("/tmp/nexus-e2e-test.bin")
    os.urandom(1)  # seed
    with open(test_file, "wb") as f:
        f.write(os.urandom(1 * 1024 * 1024))  # 1 MB

    original_hash = hashlib.sha256(test_file.read_bytes()).hexdigest()
    print(f"  Source SHA256: {original_hash[:16]}...")

    t0 = time.monotonic()
    result = storage.upload_file(test_file)
    upload_ms = (time.monotonic() - t0) * 1000

    if result.get("file_id") and result.get("cid"):
        ok(f"Upload succeeded ({upload_ms:.0f}ms)")
        ok(f"File ID: {result['file_id'][:16]}...")
        ok(f"CID: {result['cid']}")
        ok(f"Merkle root: {result['merkle_root'][:16]}...")
        ok(f"Block: {result['block']}")
    else:
        fail("Upload returned incomplete result")
        return

    file_id = result["file_id"]
    cid = result["cid"]

    # ── Test 2: List files ───────────────────────────────────────
    print(f"\n  TEST 2: List Files")
    print("-" * 55)

    files = storage.list_my_files()
    found = any(f["file_id"] == file_id for f in files)
    if found:
        ok(f"File found in listing ({len(files)} total files)")
    else:
        fail(f"File not found in listing")

    # ── Test 3: Download by file ID ──────────────────────────────
    print(f"\n  TEST 3: Download by File ID")
    print("-" * 55)

    dl_path = Path("/tmp/nexus-e2e-download.bin")
    dl_path.unlink(missing_ok=True)

    t0 = time.monotonic()
    dl_result = storage.download_file(file_id, dl_path)
    download_ms = (time.monotonic() - t0) * 1000

    if dl_path.exists():
        ok(f"File downloaded ({download_ms:.0f}ms)")
    else:
        fail("Downloaded file does not exist")
        return

    if dl_result.get("verified"):
        ok("Merkle integrity verified")
    else:
        fail("Merkle integrity check failed")

    dl_hash = hashlib.sha256(dl_path.read_bytes()).hexdigest()
    if dl_hash == original_hash:
        ok(f"SHA256 match: {dl_hash[:16]}...")
    else:
        fail(f"SHA256 mismatch: {dl_hash[:16]}... vs {original_hash[:16]}...")

    if dl_result.get("file_size") == 1 * 1024 * 1024:
        ok(f"File size correct: {dl_result['file_size']:,} bytes")
    else:
        fail(f"File size mismatch: {dl_result.get('file_size')}")

    # ── Test 4: Download by CID ──────────────────────────────────
    print(f"\n  TEST 4: Download by CID")
    print("-" * 55)

    dl_cid_path = Path("/tmp/nexus-e2e-download-cid.bin")
    dl_cid_path.unlink(missing_ok=True)

    cid_result = storage.download_by_cid(cid, dl_cid_path)
    cid_hash = hashlib.sha256(dl_cid_path.read_bytes()).hexdigest()
    if cid_hash == original_hash:
        ok(f"CID download SHA256 match")
    else:
        fail(f"CID download SHA256 mismatch")

    # ── Test 5: Verify file integrity ────────────────────────────
    print(f"\n  TEST 5: Verify Integrity")
    print("-" * 55)

    # Good file
    verified = storage.verify_file(file_id, dl_path)
    if verified:
        ok("verify_file() returns True for correct file")
    else:
        fail("verify_file() returned False for correct file")

    # Tampered file
    tampered = Path("/tmp/nexus-e2e-tampered.bin")
    data = dl_path.read_bytes()
    tampered.write_bytes(data[:100] + b"\xff" * 100 + data[200:])

    verified_bad = storage.verify_file(file_id, tampered)
    if not verified_bad:
        ok("verify_file() correctly detects tampered file")
    else:
        fail("verify_file() did NOT detect tampered file")

    # ── Test 6: Upload larger file (10 MB) ───────────────────────
    print(f"\n  TEST 6: Upload & Download 10 MB File")
    print("-" * 55)

    big_file = Path("/tmp/nexus-e2e-10mb.bin")
    with open(big_file, "wb") as f:
        f.write(os.urandom(10 * 1024 * 1024))
    big_hash = hashlib.sha256(big_file.read_bytes()).hexdigest()

    t0 = time.monotonic()
    big_result = storage.upload_file(big_file)
    big_upload_ms = (time.monotonic() - t0) * 1000
    ok(f"10 MB upload: {big_upload_ms:.0f}ms, {big_result['num_chunks']} chunks")

    big_dl = Path("/tmp/nexus-e2e-10mb-dl.bin")
    t0 = time.monotonic()
    big_dl_result = storage.download_file(big_result["file_id"], big_dl)
    big_download_ms = (time.monotonic() - t0) * 1000

    big_dl_hash = hashlib.sha256(big_dl.read_bytes()).hexdigest()
    if big_dl_hash == big_hash and big_dl_result["verified"]:
        ok(f"10 MB round-trip verified ({big_download_ms:.0f}ms download)")
    else:
        fail("10 MB round-trip failed")

    # ── Test 7: CID index persistence ────────────────────────────
    print(f"\n  TEST 7: CID Index Persistence")
    print("-" * 55)

    idx_path = Path("/opt/nexus/libnexus/cid_index.json")
    if idx_path.exists():
        with open(idx_path) as f:
            idx = json.load(f)
        if file_id in idx and big_result["file_id"] in idx:
            ok(f"CID index has {len(idx)} entries, both test files present")
        else:
            fail("CID index missing test file entries")
    else:
        fail("CID index file not created")

    # ── Cleanup ──────────────────────────────────────────────────
    for p in [test_file, dl_path, dl_cid_path, tampered, big_file, big_dl]:
        p.unlink(missing_ok=True)

    # ── Summary ──────────────────────────────────────────────────
    print(f"\n{SEP}")
    print(f"  Results: {PASS} passed, {FAIL} failed")
    print(SEP)
    if FAIL == 0:
        print("  ALL TESTS PASSED")
    else:
        print("  SOME TESTS FAILED")
    print(SEP)

    return FAIL == 0


if __name__ == "__main__":
    ok = test_all()
    sys.exit(0 if ok else 1)
