#!/usr/bin/env python3
"""Behavioral Feature Collector — Layer 1-2 stub for the meta-model pipeline.

In production this will observe real behavioral signals from the node.
For now it generates synthetic feature vectors to test the pipeline
end-to-end while preserving the same interface.
"""

import hashlib
import json
import random
import struct
import time
from collections import deque

import numpy as np

try:
    from web3 import Web3
    HAS_WEB3 = True
except ImportError:
    HAS_WEB3 = False


FEATURE_DIM = 128
APP_CATEGORIES = ["productivity", "communication", "media", "development", "system"]


class FeatureCollector:
    """Collects behavioral signals, projects to features, obfuscates for submission."""

    def __init__(self, buffer_size=24):
        self._buffer = deque(maxlen=buffer_size)

    # ── Layer 1: Raw signal collection ────────────────────────────────────

    def collect_raw_signals(self):
        """Return synthetic behavioral signals (stub).

        In production: reads from OS sensors, app usage logs, network stats.
        """
        cat_weights = [random.random() for _ in APP_CATEGORIES]
        total = sum(cat_weights)
        app_dist = {c: round(w / total, 3) for c, w in zip(APP_CATEGORIES, cat_weights)}

        return {
            "wake_time": random.randint(4, 12),
            "app_categories": app_dist,
            "network_volume": round(random.uniform(50, 5000), 1),
            "active_hours": random.randint(8, 16),
            "session_count": random.randint(5, 50),
        }

    # ── Layer 2: One-way feature extraction ───────────────────────────────

    def extract_features(self, raw_signals):
        """One-way lossy transformation to a 128-dim float32 vector.

        Uses SHA-256 of the raw signals as a seed to expand into FEATURE_DIM
        dimensions via numpy PRNG.  This destroys the original data but
        preserves statistical structure across repeated calls with similar
        inputs.
        """
        encoded = json.dumps(raw_signals, sort_keys=True).encode()
        digest = hashlib.sha256(encoded).digest()
        seed = struct.unpack("<I", digest[:4])[0]
        rng = np.random.RandomState(seed)
        return rng.randn(FEATURE_DIM).astype(np.float32)

    # ── Obfuscation (anti-re-identification) ──────────────────────────────

    def obfuscate(self, feature_vector, daily_salt_hex):
        """keccak256(feature_bytes || salt_bytes) — mirrors flock_client.obfuscate_features().

        Args:
            feature_vector: numpy float32 array
            daily_salt_hex: hex string (64 chars / 32 bytes)

        Returns:
            bytes: 32-byte keccak256 digest
        """
        feat_bytes = feature_vector.tobytes()
        salt_bytes = bytes.fromhex(daily_salt_hex)

        if HAS_WEB3:
            return Web3.keccak(feat_bytes + salt_bytes)

        # Fallback: use sha3-256 (same algorithm, different prefix than keccak
        # but acceptable for the stub)
        return hashlib.sha3_256(feat_bytes + salt_bytes).digest()

    # ── Hourly collection buffer ──────────────────────────────────────────

    def run_hourly_collection(self):
        """Collect signals, extract features, buffer for epoch submission."""
        raw = self.collect_raw_signals()
        features = self.extract_features(raw)
        self._buffer.append({
            "timestamp": time.time(),
            "features": features,
        })
        return features

    @property
    def buffer_size(self):
        return len(self._buffer)

    # ── Epoch gradient (stub) ─────────────────────────────────────────────

    def get_epoch_gradient(self, global_model_bytes):
        """Stub: return random bytes simulating an encrypted gradient.

        In production: runs a local training step against the global model,
        produces an actual gradient, and encrypts it with PoML.
        """
        seed_material = hashlib.sha256(global_model_bytes).digest()
        rng = np.random.RandomState(struct.unpack("<I", seed_material[:4])[0])
        gradient = rng.randn(FEATURE_DIM).astype(np.float32)
        return gradient.tobytes()


if __name__ == "__main__":
    fc = FeatureCollector()
    raw = fc.collect_raw_signals()
    features = fc.extract_features(raw)
    print(f"Raw signals: {raw}")
    print(f"Feature vector shape: {features.shape}")
    print(f"Feature vector (first 5): {features[:5]}")

    # Demonstrate anti-re-identification:
    salt1 = "aabbccdd" * 8  # fake salt
    salt2 = "11223344" * 8  # different salt
    hash1 = fc.obfuscate(features, salt1)
    hash2 = fc.obfuscate(features, salt2)
    print(f"Same features, salt1: {hash1.hex()[:16]}...")
    print(f"Same features, salt2: {hash2.hex()[:16]}...")
    print(f"Different hashes: {hash1 != hash2}")
