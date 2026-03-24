#!/usr/bin/env python3
"""Simulate a full federated learning gradient submission cycle.

Demonstrates:
  1. Epoch & daily salt retrieval
  2. Feature obfuscation (Numerai-style anti-re-identification)
  3. Gradient hashing & submission
  4. Proof that same features + different salts = different hashes

Usage: cd /opt/nexus && python3 scripts/simulate_gradient_submission.py
"""
import sys
import struct
import os

sys.path.insert(0, '/opt/nexus')

from web3 import Web3
from libnexus.flock_client import FlockClient

DEPLOYER = '0x817B0842B208B76A7665948F8D1A0592F9b1e958'


def random_feature_vector(dims=128):
    """Generate a fake 128-dim float feature vector as raw bytes."""
    raw = os.urandom(dims * 4)
    floats = struct.unpack(f'{dims}f', raw)
    return struct.pack(f'{dims}f', *floats)


def main():
    fc = FlockClient(wallet=DEPLOYER)

    # 1. Get current epoch and daily salt
    epoch = fc.get_current_epoch()
    print(f"Current epoch: {epoch['epochId']}")
    print(f"  dailySalt:       {epoch['dailySalt']}")
    print(f"  startBlock:      {epoch['startBlock']}")
    print(f"  submissionCount: {epoch['submissionCount']}")
    print(f"  finalized:       {epoch['finalized']}")

    if epoch['finalized']:
        print("\nEpoch is finalized. Start a new epoch first.")
        return

    salt_hex = epoch['dailySalt']
    salt_bytes = bytes.fromhex(salt_hex[2:])

    # 2. Generate fake feature vector (128-dim floats)
    features = random_feature_vector(128)
    print(f"\nFeature vector: {len(features)} bytes ({len(features)//4} floats)")

    # 3. Obfuscate features using daily salt
    obfuscated = FlockClient.obfuscate_features(features, salt_bytes)
    print(f"Obfuscated hash: 0x{obfuscated.hex()}")

    # 4. Generate fake encrypted gradient and hash it
    fake_gradient = os.urandom(1024)  # simulates encrypted gradient payload
    gradient_hash = FlockClient.generate_gradient_hash(fake_gradient)
    print(f"Gradient hash:   0x{gradient_hash.hex()}")

    # 5. Submit to FlockCoordinator
    quality_score = 8750  # 87.50% local validation accuracy
    print(f"\nSubmitting gradient (quality={quality_score/100:.2f}%)...")
    result = fc.submit_gradient(gradient_hash, quality_score)
    print(f"  tx_hash:  {result['tx_hash']}")
    print(f"  block:    {result['block']}")
    print(f"  gas_used: {result['gas_used']}")

    # 6. Verify submission
    count = fc.get_submission_count(epoch['epochId'])
    print(f"\nEpoch {epoch['epochId']} now has {count} submission(s)")

    subs = fc.get_epoch_submissions(epoch['epochId'])
    latest = subs[-1]
    print(f"  contributor:   {latest['contributor']}")
    print(f"  gradientHash:  {latest['gradientHash']}")
    print(f"  qualityScore:  {latest['qualityScore']}")
    print(f"  timestamp:     {latest['timestamp']}")

    # 7. Anti-re-identification demonstration
    print("\n=== Anti-Re-Identification Demo ===")
    print("Same feature vector with different daily salts:\n")

    salt_a = os.urandom(32)
    salt_b = os.urandom(32)

    hash_a = FlockClient.obfuscate_features(features, salt_a)
    hash_b = FlockClient.obfuscate_features(features, salt_b)

    print(f"  Salt A:   0x{salt_a.hex()[:32]}...")
    print(f"  Hash A:   0x{hash_a.hex()}")
    print(f"  Salt B:   0x{salt_b.hex()[:32]}...")
    print(f"  Hash B:   0x{hash_b.hex()}")
    print(f"  Match:    {hash_a == hash_b}")
    print()

    if hash_a != hash_b:
        print("PASS: Different salts produce different hashes.")
        print("An attacker cannot link submissions across epochs.")
    else:
        print("FAIL: Hashes should not match with different salts!")


if __name__ == "__main__":
    main()
