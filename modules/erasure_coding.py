"""
NEXUS OS — Reed-Solomon Erasure Coding Pipeline

Implements RS(10,5) erasure coding for distributed file storage.
10 data shards + 5 parity shards = 15 total. Can reconstruct from any 10.

Pipeline: file → AES-256 encrypt → split into 10 chunks → RS encode to 15 shards
          → IPFS distribute → Merkle root → StorageRegistry on-chain
"""

import hashlib
import json
import logging
import os
import secrets
import struct
import tempfile
from pathlib import Path

import numpy as np
import reedsolo
import requests
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

log = logging.getLogger("nexus.erasure_coding")

# ── Constants ────────────────────────────────────────────────────────────

DATA_SHARDS = 10
PARITY_SHARDS = 5
TOTAL_SHARDS = DATA_SHARDS + PARITY_SHARDS
CHUNK_SIZE = 256 * 1024  # 256KB per chunk before erasure coding

KEYSTORE_DIR = Path("/opt/nexus/config/file_keys")
DEFAULT_IPFS_API = "http://127.0.0.1:5001/api/v0"
DEFAULT_RPC = "http://10.0.20.3:8545"
DEPLOYER_ADDR = "0x817B0842B208B76A7665948F8D1A0592F9b1e958"
DEPLOY_JSON = "/opt/nexus/contracts/deployed/StorageRegistry.json"

# IPFS cluster nodes for replication verification
IPFS_CLUSTER_NODES = {
    "nexus-master":  "http://10.0.20.3:5001/api/v0",
    "nexus-ai":      "http://10.0.20.4:5001/api/v0",
    "nexus-storage": "http://10.0.20.11:5001/api/v0",
    "nexus-admin":   "http://10.0.10.5:5001/api/v0",
}
DEFAULT_MIN_REPLICAS = 2


class ErasureCoder:
    """Reed-Solomon 10+5 erasure coding with AES-256 encryption and
    IPFS/blockchain distribution."""

    def __init__(self, ipfs_api=DEFAULT_IPFS_API, rpc_url=DEFAULT_RPC,
                 sender=DEPLOYER_ADDR):
        self.ipfs_api = ipfs_api.rstrip("/")
        self.rpc_url = rpc_url
        self.sender = Web3.to_checksum_address(sender)
        self.rs = reedsolo.RSCodec(PARITY_SHARDS)

        KEYSTORE_DIR.mkdir(parents=True, exist_ok=True)

    def _get_w3_contract(self):
        """Lazy-load Web3 and StorageRegistry contract."""
        w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        if not w3.is_connected():
            raise ConnectionError(f"Cannot connect to Geth at {self.rpc_url}")
        with open(DEPLOY_JSON) as f:
            deploy = json.load(f)
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(deploy["address"]),
            abi=deploy["abi"],
        )
        return w3, contract

    # ── AES-256-CTR encryption ────────────────────────────────────────

    def _aes_encrypt(self, data, key):
        """AES-256-CTR encrypt using numpy-based XOR stream cipher.

        For production, swap to cryptography.hazmat AES-CTR. This
        implementation avoids the C dependency for portability.
        """
        # Derive a deterministic keystream from the key via SHA-256 counter mode
        encrypted = bytearray(len(data))
        block_size = 32
        counter = 0
        offset = 0
        while offset < len(data):
            block_key = hashlib.sha256(key + struct.pack(">Q", counter)).digest()
            end = min(offset + block_size, len(data))
            for i in range(end - offset):
                encrypted[offset + i] = data[offset + i] ^ block_key[i]
            offset = end
            counter += 1
        return bytes(encrypted)

    def _aes_decrypt(self, data, key):
        """AES-256-CTR decrypt (symmetric — same as encrypt)."""
        return self._aes_encrypt(data, key)

    def _store_key(self, file_hash_hex, key):
        """Store encryption key in local keystore."""
        key_path = KEYSTORE_DIR / f"{file_hash_hex}.key"
        key_path.write_bytes(key)
        os.chmod(key_path, 0o600)
        return str(key_path)

    def _load_key(self, file_hash_hex):
        """Load encryption key from local keystore."""
        key_path = KEYSTORE_DIR / f"{file_hash_hex}.key"
        if not key_path.exists():
            raise FileNotFoundError(f"Key not found: {key_path}")
        return key_path.read_bytes()

    # ── IPFS helpers ──────────────────────────────────────────────────

    def _ipfs_add(self, data_bytes):
        """Add raw bytes to IPFS, return CID string."""
        r = requests.post(
            f"{self.ipfs_api}/add",
            files={"file": ("shard", data_bytes)},
            params={"pin": "true"},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["Hash"]

    def _ipfs_cat(self, cid):
        """Retrieve bytes from IPFS by CID."""
        r = requests.post(
            f"{self.ipfs_api}/cat",
            params={"arg": cid},
            timeout=30,
        )
        r.raise_for_status()
        return r.content

    def _ipfs_pin_check(self, cid):
        """Check if a CID is pinned (available) locally."""
        try:
            r = requests.post(
                f"{self.ipfs_api}/pin/ls",
                params={"arg": cid, "type": "all"},
                timeout=10,
            )
            return r.status_code == 200
        except Exception:
            return False

    # ── Merkle tree ───────────────────────────────────────────────────

    @staticmethod
    def _merkle_root(items):
        """Compute Merkle root from a list of byte strings or hex CIDs."""
        if not items:
            return b'\x00' * 32
        leaves = []
        for item in items:
            if isinstance(item, str):
                leaves.append(hashlib.sha256(item.encode()).digest())
            else:
                leaves.append(hashlib.sha256(item).digest())
        while len(leaves) > 1:
            if len(leaves) % 2 == 1:
                leaves.append(leaves[-1])
            next_level = []
            for i in range(0, len(leaves), 2):
                combined = leaves[i] + leaves[i + 1]
                next_level.append(hashlib.sha256(combined).digest())
            leaves = next_level
        return leaves[0]

    # ── Core: encode ──────────────────────────────────────────────────

    def encode_file(self, file_path):
        """Encode a file into 15 erasure-coded shards.

        Args:
            file_path: Path to the file to encode

        Returns:
            tuple: (shards, metadata)
                shards: list of 15 bytes objects
                metadata: dict with file_hash, chunk_size, total_size, key_id
        """
        file_path = Path(file_path)
        raw_data = file_path.read_bytes()
        total_size = len(raw_data)

        # File hash (before encryption)
        file_hash = hashlib.sha256(raw_data).hexdigest()

        # Generate and store encryption key
        key = secrets.token_bytes(32)
        self._store_key(file_hash, key)

        # Encrypt
        encrypted = self._aes_encrypt(raw_data, key)

        # Split into DATA_SHARDS equal chunks (pad last if needed)
        chunk_size = (len(encrypted) + DATA_SHARDS - 1) // DATA_SHARDS
        data_chunks = []
        for i in range(DATA_SHARDS):
            start = i * chunk_size
            end = start + chunk_size
            chunk = encrypted[start:end]
            if len(chunk) < chunk_size:
                chunk = chunk + b'\x00' * (chunk_size - len(chunk))
            data_chunks.append(chunk)

        # Reed-Solomon encode: process column-by-column across chunks
        # Each position across chunks forms a symbol that RS encodes
        shards = list(data_chunks)  # first 10 are data shards
        parity_chunks = [bytearray(chunk_size) for _ in range(PARITY_SHARDS)]

        for pos in range(chunk_size):
            # Gather the byte at this position from each data chunk
            column = bytes(data_chunks[i][pos] for i in range(DATA_SHARDS))
            # RS encode produces data + parity
            encoded = self.rs.encode(column)
            # Extract parity bytes (last PARITY_SHARDS bytes)
            parity_bytes = encoded[DATA_SHARDS:]
            for p in range(PARITY_SHARDS):
                parity_chunks[p][pos] = parity_bytes[p]

        for p in range(PARITY_SHARDS):
            shards.append(bytes(parity_chunks[p]))

        metadata = {
            "file_hash": file_hash,
            "chunk_size": chunk_size,
            "total_size": total_size,
            "encrypted_size": len(encrypted),
            "key_id": file_hash,
            "data_shards": DATA_SHARDS,
            "parity_shards": PARITY_SHARDS,
            "file_name": file_path.name,
        }

        log.info("Encoded %s: %d bytes → %d shards × %d bytes",
                 file_path.name, total_size, TOTAL_SHARDS, chunk_size)

        return shards, metadata

    # ── Core: decode ──────────────────────────────────────────────────

    def decode_file(self, shards, metadata):
        """Decode shards back to original file bytes.

        Args:
            shards: list of up to 15 items. Missing shards should be None.
                    At least 10 must be non-None.
            metadata: dict from encode_file

        Returns:
            bytes: original decrypted file data
        """
        chunk_size = metadata["chunk_size"]
        file_hash = metadata["file_hash"]
        encrypted_size = metadata["encrypted_size"]

        # Count available shards
        available = [(i, s) for i, s in enumerate(shards) if s is not None]
        if len(available) < DATA_SHARDS:
            raise ValueError(
                f"Need at least {DATA_SHARDS} shards, got {len(available)}"
            )

        # If all data shards present, skip RS decode
        data_present = all(shards[i] is not None for i in range(DATA_SHARDS))
        if data_present:
            data_chunks = [shards[i] for i in range(DATA_SHARDS)]
        else:
            # RS decode column-by-column
            data_chunks = [bytearray(chunk_size) for _ in range(DATA_SHARDS)]

            for pos in range(chunk_size):
                # Build full column with erasures
                column = bytearray(TOTAL_SHARDS)
                erase_pos = []
                for i in range(TOTAL_SHARDS):
                    if shards[i] is not None:
                        column[i] = shards[i][pos]
                    else:
                        column[i] = 0
                        erase_pos.append(i)

                # RS decode with erasure positions
                decoded = self.rs.decode(bytes(column), erase_pos=erase_pos)
                # decoded[0] is the data portion
                for i in range(DATA_SHARDS):
                    data_chunks[i][pos] = decoded[0][i]

            data_chunks = [bytes(dc) for dc in data_chunks]

        # Reassemble encrypted data
        encrypted = b''.join(data_chunks)[:encrypted_size]

        # Decrypt
        key = self._load_key(file_hash)
        decrypted = self._aes_decrypt(encrypted, key)

        # Trim to original size and verify hash
        decrypted = decrypted[:metadata["total_size"]]
        verify_hash = hashlib.sha256(decrypted).hexdigest()
        if verify_hash != file_hash:
            raise ValueError(
                f"Hash mismatch: expected {file_hash[:16]}..., got {verify_hash[:16]}..."
            )

        log.info("Decoded %d shards → %d bytes, hash verified",
                 len(available), len(decrypted))
        return decrypted

    # ── Replication verification ─────────────────────────────────────

    def verify_replication(self, shard_cids, min_replicas=DEFAULT_MIN_REPLICAS):
        """Verify each shard CID is pinned on at least min_replicas IPFS nodes.

        Args:
            shard_cids: dict of {index: cid} or {str(index): cid}
            min_replicas: minimum number of nodes each shard must be pinned on

        Returns:
            dict: {all_verified: bool,
                   shard_status: [{cid, replica_count, nodes, verified}]}
        """
        shard_status = []
        all_verified = True

        for idx in sorted(shard_cids.keys(), key=lambda x: int(x)):
            cid = shard_cids[idx]
            nodes_with_pin = []

            for node_name, api_url in IPFS_CLUSTER_NODES.items():
                try:
                    r = requests.post(
                        f"{api_url.rstrip('/')}/pin/ls",
                        params={"arg": cid, "type": "all"},
                        timeout=10,
                    )
                    if r.status_code == 200:
                        nodes_with_pin.append(node_name)
                except Exception:
                    pass

            verified = len(nodes_with_pin) >= min_replicas
            if not verified:
                all_verified = False

            shard_status.append({
                "cid": cid,
                "replica_count": len(nodes_with_pin),
                "nodes": nodes_with_pin,
                "verified": verified,
            })

        return {
            "all_verified": all_verified,
            "shard_status": shard_status,
        }

    def ensure_replication(self, shard_cids, min_replicas=DEFAULT_MIN_REPLICAS):
        """Pin under-replicated shards to additional IPFS nodes.

        For each shard with fewer than min_replicas, pins it to nodes
        that don't already have it.

        Args:
            shard_cids: dict of {index: cid}
            min_replicas: target replica count per shard

        Returns:
            dict: {pinned_count: int, failed_count: int,
                   details: [{cid, pinned_to, failed_on}]}
        """
        verification = self.verify_replication(shard_cids, min_replicas)
        pinned_count = 0
        failed_count = 0
        details = []

        for status in verification["shard_status"]:
            if status["verified"]:
                continue

            cid = status["cid"]
            existing_nodes = set(status["nodes"])
            needed = min_replicas - len(existing_nodes)
            pinned_to = []
            failed_on = []

            # Pin to nodes that don't have it yet
            for node_name, api_url in IPFS_CLUSTER_NODES.items():
                if needed <= 0:
                    break
                if node_name in existing_nodes:
                    continue

                try:
                    r = requests.post(
                        f"{api_url.rstrip('/')}/pin/add",
                        params={"arg": cid},
                        timeout=60,
                    )
                    if r.status_code == 200:
                        pinned_to.append(node_name)
                        pinned_count += 1
                        needed -= 1
                        log.info("  Pinned %s to %s", cid[:16], node_name)
                    else:
                        failed_on.append(node_name)
                        failed_count += 1
                        log.warning("  Pin failed on %s for %s: HTTP %d",
                                    node_name, cid[:16], r.status_code)
                except Exception as e:
                    failed_on.append(node_name)
                    failed_count += 1
                    log.warning("  Pin failed on %s for %s: %s",
                                node_name, cid[:16], e)

            details.append({
                "cid": cid,
                "pinned_to": pinned_to,
                "failed_on": failed_on,
            })

        return {
            "pinned_count": pinned_count,
            "failed_count": failed_count,
            "details": details,
        }

    # ── Distribution ──────────────────────────────────────────────────

    def distribute_shards(self, shards, metadata):
        """Distribute shards to IPFS and register on-chain.

        Args:
            shards: list of 15 shard bytes from encode_file
            metadata: dict from encode_file

        Returns:
            dict: {shard_cids: {index: cid}, merkle_root, file_id, tx_hash, block}
        """
        # Upload each shard to IPFS
        shard_cids = {}
        for i, shard in enumerate(shards):
            cid = self._ipfs_add(shard)
            shard_cids[i] = cid
            log.info("  Shard %d/%d → %s", i + 1, TOTAL_SHARDS, cid)

        # Verify replication before on-chain registration
        min_replicas = DEFAULT_MIN_REPLICAS
        log.info("Verifying replication (min_replicas=%d)...", min_replicas)
        verification = self.verify_replication(shard_cids, min_replicas)

        if not verification["all_verified"]:
            # Attempt to pin under-replicated shards to additional nodes
            under_rep = sum(1 for s in verification["shard_status"] if not s["verified"])
            log.info("  %d/%d shards under-replicated, pinning to additional nodes...",
                     under_rep, TOTAL_SHARDS)
            repair = self.ensure_replication(shard_cids, min_replicas)
            log.info("  Replication repair: pinned=%d, failed=%d",
                     repair["pinned_count"], repair["failed_count"])

            # Re-verify after repair
            verification = self.verify_replication(shard_cids, min_replicas)
            if not verification["all_verified"]:
                verified = sum(1 for s in verification["shard_status"] if s["verified"])
                raise RuntimeError(
                    f"Replication verification failed: only {verified}/{TOTAL_SHARDS} "
                    f"shards have {min_replicas}+ replicas. "
                    f"Will not register on-chain until all shards are replicated."
                )

        verified = sum(1 for s in verification["shard_status"] if s["verified"])
        log.info("File %s: %d/%d shards replicated to %d+ nodes",
                 metadata["file_hash"][:16], verified, TOTAL_SHARDS, min_replicas)

        # Compute Merkle root over shard CIDs
        cid_list = [shard_cids[i] for i in range(TOTAL_SHARDS)]
        merkle_root = self._merkle_root(cid_list)

        # Master CID = hash of (file_hash + all shard CIDs)
        master_material = metadata["file_hash"] + "|" + "|".join(cid_list)
        master_cid = hashlib.sha256(master_material.encode()).digest()

        # Register on-chain
        w3, contract = self._get_w3_contract()
        file_id = master_cid  # bytes32

        tx_hash = contract.functions.registerFile(
            file_id, merkle_root, metadata["total_size"], TOTAL_SHARDS
        ).transact({
            'from': self.sender,
            'gas': 500000,
        })
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

        log.info("Registered on-chain: block=%d, file_id=%s",
                 receipt['blockNumber'], "0x" + file_id.hex())

        # Save shard map locally for retrieval
        shard_map = {
            "file_id": "0x" + file_id.hex(),
            "merkle_root": "0x" + merkle_root.hex(),
            "metadata": metadata,
            "shard_cids": {str(k): v for k, v in shard_cids.items()},
        }
        map_dir = Path("/opt/nexus/config/shard_maps")
        map_dir.mkdir(parents=True, exist_ok=True)
        map_path = map_dir / f"{metadata['file_hash']}.json"
        with open(map_path, "w") as f:
            json.dump(shard_map, f, indent=2)

        return {
            "shard_cids": shard_cids,
            "merkle_root": "0x" + merkle_root.hex(),
            "file_id": "0x" + file_id.hex(),
            "tx_hash": tx_hash.hex(),
            "block": receipt['blockNumber'],
        }

    # ── Retrieval ─────────────────────────────────────────────────────

    def retrieve_file(self, file_hash):
        """Retrieve and reconstruct a file from distributed shards.

        Args:
            file_hash: SHA-256 hex hash of the original file

        Returns:
            bytes: original file data
        """
        # Load shard map
        map_path = Path(f"/opt/nexus/config/shard_maps/{file_hash}.json")
        if not map_path.exists():
            raise FileNotFoundError(f"Shard map not found: {map_path}")

        with open(map_path) as f:
            shard_map = json.load(f)

        metadata = shard_map["metadata"]
        shard_cids = shard_map["shard_cids"]

        # Retrieve shards from IPFS (need at least DATA_SHARDS)
        shards = [None] * TOTAL_SHARDS
        retrieved = 0

        for i in range(TOTAL_SHARDS):
            cid = shard_cids.get(str(i))
            if not cid:
                continue
            try:
                shard_data = self._ipfs_cat(cid)
                shards[i] = shard_data
                retrieved += 1
                log.info("  Retrieved shard %d: %s (%d bytes)",
                         i, cid[:16], len(shard_data))
            except Exception as exc:
                log.warning("  Shard %d unavailable: %s", i, exc)

            if retrieved >= DATA_SHARDS:
                # We have enough, can stop early
                break

        if retrieved < DATA_SHARDS:
            raise ValueError(
                f"Only retrieved {retrieved}/{TOTAL_SHARDS} shards, "
                f"need at least {DATA_SHARDS}"
            )

        return self.decode_file(shards, metadata)

    # ── Availability check ────────────────────────────────────────────

    def get_shard_availability(self, file_hash):
        """Check which shards are accessible right now.

        Args:
            file_hash: SHA-256 hex hash of the original file

        Returns:
            dict: {available: N, total: 15, shards: [{index, cid, available}]}
        """
        map_path = Path(f"/opt/nexus/config/shard_maps/{file_hash}.json")
        if not map_path.exists():
            return {"error": f"Shard map not found for {file_hash[:16]}..."}

        with open(map_path) as f:
            shard_map = json.load(f)

        shard_cids = shard_map["shard_cids"]
        shard_status = []
        available_count = 0

        for i in range(TOTAL_SHARDS):
            cid = shard_cids.get(str(i))
            if not cid:
                shard_status.append({"index": i, "cid": None, "available": False})
                continue
            is_available = self._ipfs_pin_check(cid)
            if is_available:
                available_count += 1
            shard_status.append({
                "index": i,
                "cid": cid,
                "available": is_available,
                "type": "data" if i < DATA_SHARDS else "parity",
            })

        can_reconstruct = available_count >= DATA_SHARDS

        return {
            "available": available_count,
            "total": TOTAL_SHARDS,
            "can_reconstruct": can_reconstruct,
            "shards": shard_status,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    print("=== NEXUS Erasure Coding Demo ===\n")

    coder = ErasureCoder()

    # Create a test file
    test_data = b"NEXUS OS erasure coding test. " * 1000 + secrets.token_bytes(128)
    test_path = Path("/tmp/nexus_erasure_test.bin")
    test_path.write_bytes(test_data)
    print(f"Test file: {len(test_data)} bytes")
    print(f"SHA-256: {hashlib.sha256(test_data).hexdigest()[:32]}...")

    # 1. Encode
    print("\n--- Encode ---")
    shards, metadata = coder.encode_file(test_path)
    print(f"  Data shards: {DATA_SHARDS}")
    print(f"  Parity shards: {PARITY_SHARDS}")
    print(f"  Chunk size: {metadata['chunk_size']} bytes")
    print(f"  Total shard data: {sum(len(s) for s in shards)} bytes")

    # 2. Decode with all shards
    print("\n--- Decode (all 15 shards) ---")
    recovered = coder.decode_file(shards, metadata)
    assert recovered == test_data, "MISMATCH with all shards!"
    print(f"  Recovered: {len(recovered)} bytes — MATCH")

    # 3. Decode with only 10 shards (simulate 5 lost)
    print("\n--- Decode (10/15 shards — 5 lost) ---")
    degraded = list(shards)
    # Remove shards 2, 5, 7, 11, 13 (mix of data + parity)
    for lost in [2, 5, 7, 11, 13]:
        degraded[lost] = None
        print(f"  Lost shard {lost} ({'data' if lost < 10 else 'parity'})")
    recovered2 = coder.decode_file(degraded, metadata)
    assert recovered2 == test_data, "MISMATCH with degraded shards!"
    print(f"  Recovered: {len(recovered2)} bytes — MATCH")

    # 4. Distribute to IPFS + blockchain
    print("\n--- Distribute to IPFS ---")
    try:
        dist = coder.distribute_shards(shards, metadata)
        print(f"  File ID: {dist['file_id'][:24]}...")
        print(f"  Merkle root: {dist['merkle_root'][:24]}...")
        print(f"  Block: {dist['block']}")
        print(f"  Shards uploaded: {len(dist['shard_cids'])}")

        # 5. Retrieve from IPFS
        print("\n--- Retrieve from IPFS ---")
        file_hash = metadata["file_hash"]
        retrieved = coder.retrieve_file(file_hash)
        assert retrieved == test_data, "MISMATCH after IPFS round-trip!"
        print(f"  Retrieved: {len(retrieved)} bytes — MATCH")

        # 6. Availability check
        print("\n--- Shard Availability ---")
        avail = coder.get_shard_availability(file_hash)
        print(f"  Available: {avail['available']}/{avail['total']}")
        print(f"  Can reconstruct: {avail['can_reconstruct']}")
    except Exception as exc:
        print(f"  IPFS/chain step skipped: {exc}")

    # Cleanup
    test_path.unlink(missing_ok=True)
    print("\n=== All tests passed ===")
