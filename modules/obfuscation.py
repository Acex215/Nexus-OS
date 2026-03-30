"""Behavioral obfuscation via salt-rotated orthogonal projection.

Applies Numerai-style obfuscation to the 288-dim feature vector:
1. Laplace noise (differential privacy, ε=1.0/day default)
2. Daily salt rotation matrix (orthogonal, from QR decomposition)
3. Output: obfuscated 288-dim vector

The rotation preserves relative distances (ML can still learn) but
prevents cross-epoch correlation (can't compare vectors across days).
"""

import hashlib
import os
import sys
import time

import numpy as np

sys.path.insert(0, '/opt/nexus')
from modules.privacy_verifier import PrivacyVerifier

try:
    from libnexus.flock_client import FlockClient
    HAS_FLOCK = True
except Exception:
    HAS_FLOCK = False


class BehavioralObfuscator:
    """Apply noise + rotation obfuscation to feature vectors."""

    def __init__(self, flock_client=None):
        self.privacy = PrivacyVerifier()
        self.flock_client = flock_client
        self._flock_available = False

        if self.flock_client is None and HAS_FLOCK:
            try:
                self.flock_client = FlockClient()
                self._flock_available = True
            except Exception:
                pass

        # Device-specific secret for local salt derivation
        self._device_secret = self._load_device_secret()

    def get_daily_salt(self) -> bytes:
        """Get the daily salt for rotation matrix generation.

        Tries FlockCoordinator contract first, falls back to local
        date-based derivation using device secret.
        """
        # Try on-chain salt
        if self._flock_available and self.flock_client is not None:
            try:
                salt = self.flock_client.contract.functions.getCurrentSalt().call()
                if isinstance(salt, bytes) and len(salt) >= 32:
                    return salt[:32]
                if isinstance(salt, int):
                    return salt.to_bytes(32, 'big')
            except Exception:
                pass

        # Local fallback: HMAC(device_secret, date_string)
        date_str = time.strftime('%Y-%m-%d', time.gmtime())
        h = hashlib.sha256()
        h.update(self._device_secret)
        h.update(date_str.encode())
        return h.digest()

    def generate_rotation_matrix(self, salt: bytes, dim: int = 288) -> np.ndarray:
        """Generate a deterministic orthogonal rotation matrix from salt.

        Uses QR decomposition of a seeded random matrix.
        The matrix is orthogonal (Q @ Q.T ≈ I) with det ≈ ±1.

        Args:
            salt: 32 bytes used to seed the RNG.
            dim: matrix dimension (288 for feature vectors).

        Returns:
            Orthogonal matrix of shape (dim, dim).
        """
        # Seed from first 4 bytes of salt
        seed = int.from_bytes(salt[:4], 'big')
        rng = np.random.RandomState(seed)

        # Generate random matrix and decompose
        random_matrix = rng.randn(dim, dim)
        Q, R = np.linalg.qr(random_matrix)

        # Fix signs so the decomposition is unique
        signs = np.sign(np.diag(R))
        signs[signs == 0] = 1
        Q = Q * signs[np.newaxis, :]

        # Verify orthogonality
        identity_check = Q @ Q.T
        max_error = np.max(np.abs(identity_check - np.eye(dim)))
        assert max_error < 1e-10, f'Rotation matrix not orthogonal: max_error={max_error}'

        return Q

    def obfuscate(self, feature_vector: np.ndarray, epsilon: float = 1.0) -> dict:
        """Full obfuscation pipeline: noise + rotation.

        Args:
            feature_vector: 288-dim numpy array from FeatureExtractor.
            epsilon: differential privacy budget (lower = more noise).

        Returns:
            dict with obfuscated vector and metadata.
        """
        vec = np.asarray(feature_vector, dtype=np.float64)
        assert vec.shape == (288,), f'Expected (288,), got {vec.shape}'

        # Step 1: Laplace noise
        noised = self.privacy.add_laplace_noise(vec, epsilon)

        # Step 2: Daily salt → rotation matrix
        salt = self.get_daily_salt()
        Q = self.generate_rotation_matrix(salt)

        # Step 3: Rotate
        rotated = Q @ noised

        # Metadata
        salt_hash = hashlib.sha256(salt).digest()
        det = np.linalg.det(Q)

        return {
            'original_shape': (288,),
            'obfuscated_vector': rotated,
            'epsilon': epsilon,
            'salt_hash': salt_hash,
            'rotation_det': float(det),
            'timestamp': int(time.time()),
        }

    def verify_rotation(self, salt: bytes, dim: int = 288) -> bool:
        """Verify that a salt produces a valid orthogonal matrix."""
        try:
            Q = self.generate_rotation_matrix(salt, dim)
            det = np.linalg.det(Q)
            return abs(abs(det) - 1.0) < 1e-6
        except Exception:
            return False

    def _load_device_secret(self) -> bytes:
        """Load or generate a persistent device-specific secret."""
        secret_path = '/opt/nexus/config/.obfuscation_secret'
        if os.path.exists(secret_path):
            with open(secret_path, 'rb') as f:
                secret = f.read()
                if len(secret) >= 32:
                    return secret[:32]

        # Generate new secret
        secret = os.urandom(32)
        try:
            os.makedirs(os.path.dirname(secret_path), exist_ok=True)
            with open(secret_path, 'wb') as f:
                f.write(secret)
            os.chmod(secret_path, 0o600)
        except Exception:
            pass  # Non-fatal if we can't persist

        return secret
