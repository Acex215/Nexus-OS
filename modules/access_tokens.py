"""
NEXUS OS — Metadata Access Token Rotation

Implements 24-hour rotation of metadata access tokens for StorageRegistry
queries. Each node gets a daily token derived from its wallet address +
the daily salt from FlockCoordinator. Tokens rotate automatically at
epoch boundaries (00:00 UTC) when FlockCoordinator advances.

This secures metadata queries without the I/O cost of re-encrypting
files daily. Even if someone has network access to the Geth RPC, they
cannot enumerate file metadata without a valid token.

DESIGN NOTE: Enforcement is togglable via METADATA_TOKEN_ENFORCEMENT.
Initially False (log-only), so existing code continues to work.
Toggle on when all nodes are updated to include tokens in queries.
Same pattern as ENFORCEMENT_ENABLED in token_hooks.py.
"""

import hashlib
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

from web3 import Web3

log = logging.getLogger("nexus.access_tokens")

# ── Configuration ────────────────────────────────────────────────────────

# When False: tokens are generated and verified but never block queries.
# When True:  StorageRegistry metadata queries require a valid token.
METADATA_TOKEN_ENFORCEMENT = (
    os.environ.get("METADATA_TOKEN_ENFORCEMENT", "false").lower() == "true"
)

# Domain separator — prevents token reuse across different subsystems
TOKEN_DOMAIN = b"metadata_access"

# Cache TTL — avoid re-deriving the same token within an epoch
_TOKEN_CACHE_TTL_SECONDS = 300  # 5 min


# ── AccessTokenManager ──────────────────────────────────────────────────

class AccessTokenManager:
    """
    Generates and verifies daily metadata access tokens.

    Tokens are keccak256(wallet_address + daily_salt + "metadata_access").
    They are valid only for the epoch in which they were generated.
    At epoch rollover, the daily salt changes and all old tokens become
    invalid automatically — no explicit revocation needed.
    """

    def __init__(self):
        # Cache: (wallet, epoch_id) → (token_bytes, generation_time)
        self._cache = {}
        # FlockClient instance (lazy-loaded)
        self._flock_client = None
        # Last known epoch for staleness detection
        self._last_epoch_id = None

    # ── Token generation ─────────────────────────────────────────────────

    def generate_token(self, wallet_address, daily_salt):
        """
        Generate a metadata access token for a wallet.

        Args:
            wallet_address: Ethereum address (hex string, checksummed or not)
            daily_salt: bytes32 daily salt from FlockCoordinator
                        (bytes or 0x-prefixed hex string)

        Returns:
            bytes: 32-byte keccak256 token
        """
        # Normalize wallet to checksummed lowercase bytes
        wallet_bytes = Web3.to_checksum_address(wallet_address).encode("ascii")

        # Normalize salt to raw bytes
        if isinstance(daily_salt, str):
            salt_hex = daily_salt[2:] if daily_salt.startswith("0x") else daily_salt
            salt_bytes = bytes.fromhex(salt_hex)
        else:
            salt_bytes = daily_salt

        # token = keccak256(wallet + salt + domain)
        token = Web3.keccak(wallet_bytes + salt_bytes + TOKEN_DOMAIN)

        log.debug(
            "Generated token for %s: %s…",
            wallet_address[:10], token.hex()[:16],
        )
        return token

    # ── Token verification ───────────────────────────────────────────────

    def verify_token(self, wallet_address, token, epoch_id=None):
        """
        Verify a metadata access token.

        Recomputes the expected token using the epoch's salt and compares.

        Args:
            wallet_address: Ethereum address of the requester
            token: bytes32 token to verify (bytes or hex string)
            epoch_id: epoch to verify against. If None, uses current epoch.

        Returns:
            bool: True if the token is valid for the specified epoch
        """
        # Normalize token to bytes
        if isinstance(token, str):
            token_hex = token[2:] if token.startswith("0x") else token
            token = bytes.fromhex(token_hex)

        # Get the salt for the target epoch
        try:
            salt = self._get_salt_for_epoch(epoch_id)
        except Exception as e:
            log.warning("Cannot verify token — salt unavailable: %s", e)
            # If we can't verify, behavior depends on enforcement mode
            if METADATA_TOKEN_ENFORCEMENT:
                return False
            return True  # Permissive when not enforcing

        if salt is None:
            log.warning("No salt available for epoch %s", epoch_id)
            return not METADATA_TOKEN_ENFORCEMENT

        # Recompute expected token
        expected = self.generate_token(wallet_address, salt)

        valid = token == expected
        if not valid:
            log.info(
                "Token verification failed for %s (epoch=%s)",
                wallet_address[:10], epoch_id,
            )

        return valid

    # ── Token rotation ───────────────────────────────────────────────────

    def rotate_tokens(self):
        """
        Called at epoch start by daily_epoch_cycle.py.

        Clears the token cache. Old tokens are automatically invalid
        because they were derived from the previous epoch's salt — no
        explicit revocation list needed.
        """
        old_epoch = self._last_epoch_id
        self._cache.clear()

        # Refresh epoch info
        try:
            fc = self._get_flock_client()
            epoch = fc.get_current_epoch()
            self._last_epoch_id = epoch["epochId"]
            log.info(
                "Token rotation: epoch %s → %s, cache cleared",
                old_epoch, self._last_epoch_id,
            )
        except Exception as e:
            log.warning("Token rotation — FlockCoordinator unavailable: %s", e)
            self._last_epoch_id = None

    # ── Convenience: get current token ───────────────────────────────────

    def get_current_token(self, wallet_address):
        """
        Get the current epoch's metadata access token for a wallet.

        Fetches the daily salt from FlockCoordinator, generates the token,
        and caches it for the current epoch.

        Args:
            wallet_address: Ethereum address

        Returns:
            bytes: 32-byte token, or None if FlockCoordinator unreachable
        """
        try:
            fc = self._get_flock_client()
            epoch = fc.get_current_epoch()
        except Exception as e:
            log.warning("Cannot get current token — FlockCoordinator unavailable: %s", e)
            return None

        epoch_id = epoch["epochId"]
        salt = epoch["dailySalt"]

        # Check cache
        cache_key = (Web3.to_checksum_address(wallet_address), epoch_id)
        cached = self._cache.get(cache_key)
        if cached is not None:
            token, gen_time = cached
            if time.monotonic() - gen_time < _TOKEN_CACHE_TTL_SECONDS:
                return token

        # Generate fresh token
        token = self.generate_token(wallet_address, salt)
        self._cache[cache_key] = (token, time.monotonic())

        # Track epoch transitions
        if self._last_epoch_id is not None and epoch_id != self._last_epoch_id:
            log.info(
                "Epoch transition detected in get_current_token: %s → %s",
                self._last_epoch_id, epoch_id,
            )
            # Purge stale cache entries from old epochs
            stale_keys = [k for k in self._cache if k[1] != epoch_id]
            for k in stale_keys:
                del self._cache[k]

        self._last_epoch_id = epoch_id
        return token

    # ── Enforcement gate ─────────────────────────────────────────────────

    def check_metadata_access(self, wallet_address, token):
        """
        Gate for StorageRegistry metadata queries.

        Call this before returning file metadata to a requester.

        Args:
            wallet_address: requester's Ethereum address
            token: the access token they provided (bytes or hex)

        Returns:
            tuple: (allowed: bool, reason: str)
        """
        if token is None:
            if METADATA_TOKEN_ENFORCEMENT:
                log.warning(
                    "[ENFORCED] Metadata query blocked — no token from %s",
                    wallet_address[:10],
                )
                return (False, "access token required")
            else:
                log.debug(
                    "[LOG-ONLY] Metadata query without token from %s",
                    wallet_address[:10],
                )
                return (True, "enforcement disabled — no token provided")

        valid = self.verify_token(wallet_address, token)

        if valid:
            return (True, "valid token")

        if METADATA_TOKEN_ENFORCEMENT:
            log.warning(
                "[ENFORCED] Metadata query blocked — invalid token from %s",
                wallet_address[:10],
            )
            return (False, "invalid or expired access token")
        else:
            log.info(
                "[LOG-ONLY] Invalid metadata token from %s (would block if enforced)",
                wallet_address[:10],
            )
            return (True, "enforcement disabled — invalid token logged")

    # ── Internal helpers ─────────────────────────────────────────────────

    def _get_flock_client(self):
        """Lazy-load FlockClient."""
        if self._flock_client is None:
            import sys
            if '/opt/nexus' not in sys.path:
                sys.path.insert(0, '/opt/nexus')
            from libnexus.flock_client import FlockClient
            self._flock_client = FlockClient(
                wallet="0x817B0842B208B76A7665948F8D1A0592F9b1e958"
            )
        return self._flock_client

    def _get_salt_for_epoch(self, epoch_id=None):
        """
        Get the daily salt for a specific epoch.

        Args:
            epoch_id: epoch number. If None, uses current epoch.

        Returns:
            str: 0x-prefixed hex salt, or None if unavailable
        """
        fc = self._get_flock_client()

        if epoch_id is None:
            epoch = fc.get_current_epoch()
            return epoch["dailySalt"]

        return fc.get_daily_salt(epoch_id)


# ── Singleton ───────────────────────────────────────────────────────────

_instance = None


def get_access_token_manager():
    """Get or create the singleton AccessTokenManager instance."""
    global _instance
    if _instance is None:
        _instance = AccessTokenManager()
    return _instance


# ── Main demo ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(name)s  %(levelname)s  %(message)s")

    print("=== NEXUS Metadata Access Token Demo ===\n")

    DEPLOYER = "0x817B0842B208B76A7665948F8D1A0592F9b1e958"
    mgr = AccessTokenManager()

    print(f"  Enforcement: {METADATA_TOKEN_ENFORCEMENT}")

    # ── Test with synthetic salt (works without FlockCoordinator) ──
    print("\n--- Token generation (synthetic salt) ---")
    fake_salt = hashlib.sha256(b"2026-03-24-test-salt").digest()

    token = mgr.generate_token(DEPLOYER, fake_salt)
    print(f"  Wallet:  {DEPLOYER[:16]}…")
    print(f"  Salt:    {fake_salt.hex()[:16]}…")
    print(f"  Token:   0x{token.hex()[:16]}…")

    # ── Verify correct token ──
    print("\n--- Verification ---")
    # Manually inject salt so verify works without FlockCoordinator
    valid = (token == mgr.generate_token(DEPLOYER, fake_salt))
    print(f"  Correct token:   valid={valid}")

    # Wrong token
    wrong_token = b'\x00' * 32
    wrong_valid = (wrong_token == mgr.generate_token(DEPLOYER, fake_salt))
    print(f"  Wrong token:     valid={wrong_valid}")

    # Different wallet
    other_wallet = "0x0000000000000000000000000000000000000001"
    other_token = mgr.generate_token(other_wallet, fake_salt)
    cross_valid = (other_token == token)
    print(f"  Cross-wallet:    valid={cross_valid}")

    # ── Enforcement gate ──
    print("\n--- Metadata access gate ---")
    allowed, reason = mgr.check_metadata_access(DEPLOYER, token)
    print(f"  Valid token:     allowed={allowed} reason=\"{reason}\"")

    allowed2, reason2 = mgr.check_metadata_access(DEPLOYER, None)
    print(f"  No token:        allowed={allowed2} reason=\"{reason2}\"")

    # ── Try live FlockCoordinator ──
    print("\n--- Live FlockCoordinator token ---")
    try:
        live_token = mgr.get_current_token(DEPLOYER)
        if live_token is not None:
            epoch = mgr._last_epoch_id
            print(f"  Epoch:   {epoch}")
            print(f"  Token:   0x{live_token.hex()[:16]}…")

            # Verify round-trip
            ok = mgr.verify_token(DEPLOYER, live_token)
            print(f"  Verify:  {ok}")
        else:
            print("  FlockCoordinator unavailable — skipped")
    except Exception as e:
        print(f"  FlockCoordinator error: {e}")

    # ── Rotation ──
    print("\n--- Token rotation ---")
    mgr._cache[("test", 0)] = (b'\x00' * 32, 0)
    print(f"  Cache size before: {len(mgr._cache)}")
    mgr.rotate_tokens()
    print(f"  Cache size after:  {len(mgr._cache)}")

    print("\nDone.")
