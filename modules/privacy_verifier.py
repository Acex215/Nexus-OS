"""
NEXUS OS — Privacy Verifier

Differential privacy mechanisms for the federated learning pipeline.
Generates privacy proofs, applies calibrated Laplace noise, and
statistically verifies that claimed epsilon values match observed noise.
"""

import hashlib
import logging
import time

import numpy as np

log = logging.getLogger("nexus.privacy_verifier")


class PrivacyVerifier:
    """Differential privacy proof generation and verification."""

    def add_laplace_noise(self, vector, epsilon=0.1):
        """Apply Laplace mechanism for differential privacy.

        Adds noise drawn from Laplace(0, sensitivity/epsilon) to each
        element. Assumes sensitivity = 1.0 (L1 norm of query).

        Args:
            vector: numpy array or list of floats
            epsilon: privacy budget (smaller = more noise = more private)

        Returns:
            numpy array: noised vector
        """
        v = np.asarray(vector, dtype=np.float64)
        sensitivity = 1.0
        scale = sensitivity / epsilon
        noise = np.random.laplace(loc=0.0, scale=scale, size=v.shape)
        return v + noise

    def generate_proof(self, feature_vector, daily_salt, epsilon=0.1):
        """Generate a privacy proof for on-chain submission.

        1. Apply Laplace noise with given epsilon
        2. Compute Merkle root of the obfuscated dataset
        3. Return proof data for NetworkObscuration.submitPrivacyProof()

        Args:
            feature_vector: numpy array of raw features
            daily_salt: bytes or hex string — the day's salt
            epsilon: privacy budget

        Returns:
            dict: {
                obfuscated_vector, dataset_merkle_root, epsilon_scaled,
                salt_hash, proof_data
            }
        """
        v = np.asarray(feature_vector, dtype=np.float64)

        # Apply differential privacy
        obfuscated = self.add_laplace_noise(v, epsilon)

        # Compute Merkle root of obfuscated values
        # Each element becomes a leaf: H(index || value_bytes)
        leaves = []
        for i, val in enumerate(obfuscated.flat):
            leaf_data = f"{i}:{val:.16e}".encode()
            leaves.append(hashlib.sha256(leaf_data).digest())

        merkle_root = self._merkle_root(leaves)

        # Hash the daily salt for on-chain storage
        if isinstance(daily_salt, str):
            salt_bytes = bytes.fromhex(daily_salt.replace('0x', ''))
        else:
            salt_bytes = daily_salt
        salt_hash = hashlib.sha256(salt_bytes).digest()

        # Epsilon scaled by 1000 for on-chain integer storage
        epsilon_scaled = int(epsilon * 1000)

        proof = {
            "obfuscated_vector": obfuscated,
            "dataset_merkle_root": merkle_root,
            "dataset_merkle_root_hex": "0x" + merkle_root.hex(),
            "epsilon": epsilon,
            "epsilon_scaled": epsilon_scaled,
            "salt_hash": salt_hash,
            "salt_hash_hex": "0x" + salt_hash.hex(),
            "vector_size": v.size,
            "noise_scale": 1.0 / epsilon,
            "timestamp": int(time.time()),
        }

        log.info("Generated privacy proof: epsilon=%.3f, vector_size=%d, "
                 "merkle=%s", epsilon, v.size, proof["dataset_merkle_root_hex"][:18])

        return proof

    def verify_epsilon(self, claimed_epsilon, original_vector, obfuscated_vector,
                       confidence=0.95):
        """Statistically verify that noise matches the claimed epsilon.

        Computes the empirical noise and checks if it's consistent with
        a Laplace(0, 1/epsilon) distribution using the mean absolute
        deviation (which equals the scale parameter for Laplace).

        Args:
            claimed_epsilon: the epsilon claimed by the contributor
            original_vector: numpy array of original values
            obfuscated_vector: numpy array of noised values
            confidence: confidence level for the test (0-1)

        Returns:
            bool: True if noise is consistent with claimed epsilon
        """
        orig = np.asarray(original_vector, dtype=np.float64).flatten()
        obfs = np.asarray(obfuscated_vector, dtype=np.float64).flatten()

        if orig.size != obfs.size:
            log.warning("Vector size mismatch: %d vs %d", orig.size, obfs.size)
            return False

        noise = obfs - orig
        n = noise.size

        if n < 10:
            log.warning("Too few samples (%d) for statistical verification", n)
            return False

        # For Laplace(0, b): E[|X|] = b, Var(|X|) = b^2
        # Expected scale b = 1/epsilon
        expected_scale = 1.0 / claimed_epsilon

        # Empirical mean absolute deviation = estimated scale
        empirical_scale = float(np.mean(np.abs(noise)))

        # Standard error of the MAD estimator for Laplace
        se = expected_scale / np.sqrt(n)

        # Z-score: how many standard errors away from expected
        z = abs(empirical_scale - expected_scale) / max(se, 1e-10)

        # For 95% confidence, z should be < 1.96
        from scipy.stats import norm
        z_critical = norm.ppf((1 + confidence) / 2)

        passed = z < z_critical

        log.info("Epsilon verification: claimed=%.3f, empirical_scale=%.4f, "
                 "expected_scale=%.4f, z=%.2f (critical=%.2f) → %s",
                 claimed_epsilon, empirical_scale, expected_scale,
                 z, z_critical, "PASS" if passed else "FAIL")

        return passed

    @staticmethod
    def _merkle_root(leaves):
        """Compute Merkle root from a list of 32-byte leaf hashes."""
        if not leaves:
            return b'\x00' * 32
        layer = list(leaves)
        while len(layer) > 1:
            if len(layer) % 2 == 1:
                layer.append(layer[-1])
            next_layer = []
            for i in range(0, len(layer), 2):
                combined = layer[i] + layer[i + 1]
                next_layer.append(hashlib.sha256(combined).digest())
            layer = next_layer
        return layer[0]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    print("=== NEXUS Privacy Verifier Demo ===\n")

    pv = PrivacyVerifier()
    np.random.seed(42)

    # Generate a feature vector
    original = np.random.randn(128)
    daily_salt = hashlib.sha256(b"2026-03-24-daily-salt").digest()

    # 1. Apply Laplace noise
    print("--- Laplace Noise ---")
    noised = pv.add_laplace_noise(original, epsilon=0.1)
    noise_mag = float(np.mean(np.abs(noised - original)))
    print(f"  Epsilon: 0.1")
    print(f"  Expected scale (1/eps): 10.0")
    print(f"  Empirical MAD: {noise_mag:.4f}")
    print(f"  Vector size: {original.size}")

    # 2. Generate privacy proof
    print("\n--- Generate Proof ---")
    proof = pv.generate_proof(original, daily_salt, epsilon=0.1)
    print(f"  Merkle root: {proof['dataset_merkle_root_hex'][:32]}...")
    print(f"  Salt hash: {proof['salt_hash_hex'][:32]}...")
    print(f"  Epsilon (scaled): {proof['epsilon_scaled']}")
    print(f"  Noise scale: {proof['noise_scale']:.1f}")

    # 3. Verify epsilon
    print("\n--- Verify Epsilon ---")
    # Should pass — correct epsilon
    passed = pv.verify_epsilon(0.1, original, proof["obfuscated_vector"])
    print(f"  Correct epsilon (0.1): {'PASS' if passed else 'FAIL'}")

    # Should fail — wrong epsilon (claiming more noise than applied)
    passed_wrong = pv.verify_epsilon(0.01, original, proof["obfuscated_vector"])
    print(f"  Wrong epsilon (0.01):  {'PASS' if passed_wrong else 'FAIL'}")

    # 4. Different epsilon levels
    print("\n--- Epsilon Comparison ---")
    for eps in [0.01, 0.1, 1.0, 10.0]:
        noised_test = pv.add_laplace_noise(original, epsilon=eps)
        mad = float(np.mean(np.abs(noised_test - original)))
        print(f"  eps={eps:>5.2f}  scale={1/eps:>7.1f}  MAD={mad:>8.2f}")

    print("\n=== Done ===")
