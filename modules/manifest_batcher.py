"""
NEXUS OS — Off-Chain Manifest Batching

Solves the blockchain throughput bottleneck for large files.
Instead of N transactions for N shards, batch all metadata into ONE
off-chain manifest, compute a Merkle root, and submit ONE transaction.

A 1GB file = ~4000 chunks = 4000 tx at 30 tx/s = 133 seconds.
With batching: 1 manifest + 1 tx = <2 seconds.
"""

import hashlib
import json
import logging
import os
import time
from pathlib import Path

import requests
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

log = logging.getLogger("nexus.manifest_batcher")

DEFAULT_IPFS_API = "http://127.0.0.1:5001/api/v0"
DEFAULT_RPC = "http://10.0.20.3:8545"
DEPLOYER_ADDR = "0x817B0842B208B76A7665948F8D1A0592F9b1e958"
DEPLOY_JSON = "/opt/nexus/contracts/deployed/StorageRegistry.json"
MANIFEST_DIR = Path("/opt/nexus/config/manifests")


class ManifestBatcher:
    """Batches shard metadata into off-chain manifests for single-transaction
    on-chain registration."""

    def __init__(self, ipfs_api=DEFAULT_IPFS_API, rpc_url=DEFAULT_RPC,
                 sender=DEPLOYER_ADDR):
        self.ipfs_api = ipfs_api.rstrip("/")
        self.rpc_url = rpc_url
        self.sender = Web3.to_checksum_address(sender)
        MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    def _get_w3_contract(self):
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

    def _ipfs_add_json(self, data):
        """Add JSON data to IPFS, return CID."""
        payload = json.dumps(data, separators=(',', ':')).encode()
        r = requests.post(
            f"{self.ipfs_api}/add",
            files={"file": ("manifest.json", payload)},
            params={"pin": "true"},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["Hash"]

    # ── Merkle tree ───────────────────────────────────────────────────

    @staticmethod
    def compute_merkle_root(shard_cids):
        """Build Merkle tree from shard CIDs, return root as bytes32.

        Args:
            shard_cids: list of CID strings

        Returns:
            bytes: 32-byte Merkle root
        """
        if not shard_cids:
            return b'\x00' * 32

        leaves = [hashlib.sha256(cid.encode()).digest() for cid in shard_cids]

        while len(leaves) > 1:
            if len(leaves) % 2 == 1:
                leaves.append(leaves[-1])
            next_level = []
            for i in range(0, len(leaves), 2):
                combined = leaves[i] + leaves[i + 1]
                next_level.append(hashlib.sha256(combined).digest())
            leaves = next_level

        return leaves[0]

    @staticmethod
    def _merkle_proof(shard_cids, index):
        """Compute Merkle proof for a single shard at index."""
        if not shard_cids:
            return []

        leaves = [hashlib.sha256(cid.encode()).digest() for cid in shard_cids]
        proof = []
        idx = index

        while len(leaves) > 1:
            if len(leaves) % 2 == 1:
                leaves.append(leaves[-1])
            sibling = idx ^ 1
            proof.append({
                "hash": leaves[sibling].hex(),
                "position": "right" if idx % 2 == 0 else "left",
            })
            next_level = []
            for i in range(0, len(leaves), 2):
                combined = leaves[i] + leaves[i + 1]
                next_level.append(hashlib.sha256(combined).digest())
            leaves = next_level
            idx //= 2

        return proof

    # ── Manifest creation ─────────────────────────────────────────────

    def create_manifest(self, file_id, shards_metadata):
        """Create an off-chain manifest for a file's shards.

        Args:
            file_id: hex string file identifier
            shards_metadata: dict with keys:
                shard_cids: list of IPFS CID strings
                total_size: original file size in bytes
                node_assignments: dict {shard_index: [node_addresses]}
                    (optional, can be empty)

        Returns:
            dict: complete manifest
        """
        shard_cids = shards_metadata.get("shard_cids", [])
        merkle_root = self.compute_merkle_root(shard_cids)

        manifest = {
            "version": 1,
            "file_id": file_id,
            "total_size": shards_metadata.get("total_size", 0),
            "shard_count": len(shard_cids),
            "shard_cids": shard_cids,
            "node_assignments": shards_metadata.get("node_assignments", {}),
            "merkle_root": "0x" + merkle_root.hex(),
            "timestamp": int(time.time()),
            "checksum": hashlib.sha256(
                json.dumps(shard_cids, separators=(',', ':')).encode()
            ).hexdigest(),
        }

        # Save locally
        manifest_path = MANIFEST_DIR / f"{file_id.replace('0x', '')[:32]}.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        log.info("Created manifest for %s: %d shards, merkle=%s",
                 file_id[:18], len(shard_cids), manifest["merkle_root"][:18])

        return manifest

    # ── IPFS storage ──────────────────────────────────────────────────

    def store_manifest_ipfs(self, manifest):
        """Pin the manifest JSON to IPFS.

        Args:
            manifest: dict from create_manifest

        Returns:
            str: IPFS CID of the manifest
        """
        cid = self._ipfs_add_json(manifest)
        log.info("Manifest pinned to IPFS: %s", cid)
        return cid

    # ── On-chain registration ─────────────────────────────────────────

    def register_on_chain(self, file_id, manifest_ipfs_cid, merkle_root,
                          total_size, shard_count):
        """Register file with ONE blockchain transaction.

        Instead of N shard transactions, we store:
        - file_id (bytes32)
        - manifest CID hash as merkle_root (bytes32) — the manifest
          CID itself is recoverable from IPFS
        - total size
        - shard count

        Args:
            file_id: hex string or bytes32
            manifest_ipfs_cid: IPFS CID of the off-chain manifest
            merkle_root: bytes32 Merkle root of shard CIDs
            total_size: file size in bytes
            shard_count: number of shards

        Returns:
            dict: {tx_hash, block, gas_used}
        """
        w3, contract = self._get_w3_contract()

        if isinstance(file_id, str):
            file_id_bytes = bytes.fromhex(file_id.replace('0x', '').zfill(64))
        else:
            file_id_bytes = file_id

        if isinstance(merkle_root, str):
            merkle_bytes = bytes.fromhex(merkle_root.replace('0x', '').zfill(64))
        else:
            merkle_bytes = merkle_root

        # Cap shard_count to uint8 max (255). For files with >255 shards,
        # the manifest holds the true count.
        chain_shard_count = min(shard_count, 255)

        tx_hash = contract.functions.registerFile(
            file_id_bytes, merkle_bytes, total_size, chain_shard_count
        ).transact({
            'from': self.sender,
            'gas': 500000,
        })
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

        log.info("Registered on-chain: block=%d, gas=%d (1 tx for %d shards)",
                 receipt['blockNumber'], receipt['gasUsed'], shard_count)

        return {
            "tx_hash": tx_hash.hex(),
            "block": receipt['blockNumber'],
            "gas_used": receipt['gasUsed'],
            "manifest_cid": manifest_ipfs_cid,
        }

    # ── Verification ──────────────────────────────────────────────────

    def verify_manifest(self, manifest, merkle_root):
        """Verify that the manifest's shard CIDs produce the given Merkle root.

        Args:
            manifest: dict with shard_cids list
            merkle_root: hex string or bytes32 to verify against

        Returns:
            bool: True if Merkle root matches
        """
        shard_cids = manifest.get("shard_cids", [])
        computed = self.compute_merkle_root(shard_cids)

        if isinstance(merkle_root, str):
            expected = bytes.fromhex(merkle_root.replace('0x', ''))
        else:
            expected = merkle_root

        match = computed == expected
        if not match:
            log.warning("Merkle mismatch: computed=%s expected=%s",
                        computed.hex()[:16], expected.hex()[:16])
        return match

    # ── Batch registration ────────────────────────────────────────────

    def batch_register_files(self, files_metadata_list):
        """Batch multiple files into a single super-manifest and register
        with one transaction.

        Args:
            files_metadata_list: list of dicts, each with:
                file_id: hex string
                shard_cids: list of CID strings
                total_size: int

        Returns:
            dict: {batch_id, file_count, total_shards, tx_hash, block, manifest_cid}
        """
        if not files_metadata_list:
            return {"error": "Empty file list"}

        # Collect all shard CIDs across files
        all_cids = []
        file_entries = []
        total_size = 0

        for fm in files_metadata_list:
            cids = fm.get("shard_cids", [])
            file_entries.append({
                "file_id": fm["file_id"],
                "shard_count": len(cids),
                "total_size": fm.get("total_size", 0),
                "shard_offset": len(all_cids),
            })
            all_cids.extend(cids)
            total_size += fm.get("total_size", 0)

        # Compute batch Merkle root over ALL shard CIDs
        merkle_root = self.compute_merkle_root(all_cids)

        # Build super-manifest
        batch_id_material = "|".join(fm["file_id"] for fm in files_metadata_list)
        batch_id = hashlib.sha256(
            (batch_id_material + str(int(time.time()))).encode()
        ).hexdigest()

        super_manifest = {
            "version": 1,
            "type": "batch",
            "batch_id": batch_id,
            "file_count": len(files_metadata_list),
            "total_shards": len(all_cids),
            "total_size": total_size,
            "merkle_root": "0x" + merkle_root.hex(),
            "files": file_entries,
            "all_shard_cids": all_cids,
            "timestamp": int(time.time()),
        }

        # Save locally
        manifest_path = MANIFEST_DIR / f"batch_{batch_id[:16]}.json"
        with open(manifest_path, "w") as f:
            json.dump(super_manifest, f, indent=2)

        # Pin to IPFS
        manifest_cid = self.store_manifest_ipfs(super_manifest)

        # ONE transaction for the entire batch
        batch_file_id = bytes.fromhex(batch_id[:64].ljust(64, '0'))

        result = self.register_on_chain(
            file_id=batch_file_id,
            manifest_ipfs_cid=manifest_cid,
            merkle_root=merkle_root,
            total_size=total_size,
            shard_count=len(all_cids),
        )

        result.update({
            "batch_id": batch_id,
            "file_count": len(files_metadata_list),
            "total_shards": len(all_cids),
        })

        log.info("Batch registered: %d files, %d shards in 1 tx",
                 len(files_metadata_list), len(all_cids))

        return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    print("=== NEXUS Manifest Batcher Demo ===\n")

    batcher = ManifestBatcher()

    # Generate 100 fake shard CIDs
    fake_cids = [
        f"Qm{''.join(f'{b:02x}' for b in hashlib.sha256(f'shard-{i}'.encode()).digest()[:22])}"
        for i in range(100)
    ]
    file_id = "0x" + hashlib.sha256(b"test-file-100-shards").hexdigest()

    # 1. Create manifest
    print("--- Create Manifest ---")
    manifest = batcher.create_manifest(file_id, {
        "shard_cids": fake_cids,
        "total_size": 100 * 256 * 1024,  # 25.6 MB
        "node_assignments": {
            "0": ["10.0.20.3", "10.0.20.4"],
            "50": ["10.0.20.11"],
        },
    })
    print(f"  File ID: {manifest['file_id'][:24]}...")
    print(f"  Shards: {manifest['shard_count']}")
    print(f"  Merkle root: {manifest['merkle_root'][:24]}...")

    # 2. Verify manifest
    print("\n--- Verify Manifest ---")
    valid = batcher.verify_manifest(manifest, manifest["merkle_root"])
    print(f"  Valid: {valid}")

    # Tamper test
    tampered = dict(manifest)
    tampered["shard_cids"] = list(manifest["shard_cids"])
    tampered["shard_cids"][0] = "QmTAMPERED"
    tampered_valid = batcher.verify_manifest(tampered, manifest["merkle_root"])
    print(f"  Tampered valid: {tampered_valid}")

    # 3. Store manifest on IPFS
    print("\n--- Store Manifest on IPFS ---")
    try:
        manifest_cid = batcher.store_manifest_ipfs(manifest)
        print(f"  Manifest CID: {manifest_cid}")
    except Exception as exc:
        manifest_cid = None
        print(f"  IPFS skipped: {exc}")

    # 4. Register on-chain (1 transaction for 100 shards)
    print("\n--- Register On-Chain ---")
    merkle_bytes = bytes.fromhex(manifest["merkle_root"].replace("0x", ""))
    try:
        result = batcher.register_on_chain(
            file_id=file_id,
            manifest_ipfs_cid=manifest_cid or "local",
            merkle_root=merkle_bytes,
            total_size=manifest["total_size"],
            shard_count=manifest["shard_count"],
        )
        print(f"  TX: {result['tx_hash'][:24]}...")
        print(f"  Block: {result['block']}")
        print(f"  Gas: {result['gas_used']}")
    except Exception as exc:
        print(f"  Chain skipped: {exc}")

    print(f"\n100 shards registered in 1 transaction (vs 100 without batching)")

    # 5. Batch register multiple files
    print("\n--- Batch Register (3 files) ---")
    batch_files = []
    for f_idx in range(3):
        batch_files.append({
            "file_id": "0x" + hashlib.sha256(f"batch-file-{f_idx}".encode()).hexdigest(),
            "shard_cids": [
                f"QmBatch{f_idx}Shard{s:04d}" for s in range(15)
            ],
            "total_size": 15 * 256 * 1024,
        })

    try:
        batch_result = batcher.batch_register_files(batch_files)
        print(f"  Batch ID: {batch_result['batch_id'][:24]}...")
        print(f"  Files: {batch_result['file_count']}")
        print(f"  Total shards: {batch_result['total_shards']}")
        print(f"  Block: {batch_result['block']}")
        print(f"  Gas: {batch_result['gas_used']}")
        print(f"\n  3 files × 15 shards = 45 shards in 1 transaction")
    except Exception as exc:
        print(f"  Batch skipped: {exc}")

    print("\n=== Done ===")
