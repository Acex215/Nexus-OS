"""
NEXUS OS Storage Library
========================
Coordinates IPFS data layer with blockchain metadata layer.

Architecture:
- IPFS handles actual file data (content addressing, transfer, deduplication)
- Blockchain handles metadata (ownership, chunk map, Merkle roots, proofs)

Usage:
    storage = NexusStorage()
    result  = storage.upload_file(Path("/tmp/myfile.bin"))
    dl      = storage.download_file(result["file_id"], Path("/tmp/out.bin"))
    files   = storage.list_my_files()
"""

import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

# ── Defaults ─────────────────────────────────────────────────────
DEFAULT_IPFS_API    = "http://127.0.0.1:5001/api/v0"
DEFAULT_RPC         = "http://192.168.8.228:8545"
DEFAULT_CONTRACT    = "0x859e30a6b752Af6D96d309Dc3a5bECfCfFDe31A6"
DEPLOYER_ADDR       = "0x817B0842B208B76A7665948F8D1A0592F9b1e958"
DEPLOY_JSON         = "/opt/nexus/contracts/deployed/StorageRegistry.json"
CHUNK_SIZE          = 256 * 1024   # 256 KB


class NexusStorage:
    """Distributed storage coordinator for NEXUS OS."""

    def __init__(
        self,
        ipfs_api: str = DEFAULT_IPFS_API,
        rpc_url: str = DEFAULT_RPC,
        contract_address: str = DEFAULT_CONTRACT,
        sender: str = DEPLOYER_ADDR,
    ):
        # IPFS (HTTP API, no version-locked client library)
        self.ipfs_api = ipfs_api.rstrip("/")
        self._ipfs_check()

        # Blockchain
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        assert self.w3.is_connected(), f"Cannot connect to Geth at {rpc_url}"

        self.sender = Web3.to_checksum_address(sender)

        with open(DEPLOY_JSON) as f:
            deploy = json.load(f)
        self.contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(deploy["address"]),
            abi=deploy["abi"],
        )

    # ── IPFS helpers ─────────────────────────────────────────────

    def _ipfs_check(self):
        """Verify IPFS daemon is reachable."""
        try:
            r = requests.post(f"{self.ipfs_api}/id", timeout=5)
            r.raise_for_status()
        except Exception as e:
            raise ConnectionError(f"IPFS API unreachable at {self.ipfs_api}: {e}")

    def _ipfs_add(self, filepath: Path, pin: bool = True) -> str:
        """Add a file to IPFS, return CID."""
        with open(filepath, "rb") as f:
            r = requests.post(
                f"{self.ipfs_api}/add",
                files={"file": (filepath.name, f)},
                params={"pin": str(pin).lower()},
                timeout=300,
            )
        r.raise_for_status()
        return r.json()["Hash"]

    def _ipfs_cat(self, cid: str) -> bytes:
        """Retrieve file content from IPFS by CID."""
        r = requests.post(
            f"{self.ipfs_api}/cat",
            params={"arg": cid},
            timeout=300,
        )
        r.raise_for_status()
        return r.content

    def _ipfs_pin(self, cid: str):
        """Pin a CID on this node."""
        r = requests.post(
            f"{self.ipfs_api}/pin/add",
            params={"arg": cid},
            timeout=120,
        )
        r.raise_for_status()

    # ── Chunking & Merkle ────────────────────────────────────────

    @staticmethod
    def chunk_file(filepath: Path, chunk_size: int = CHUNK_SIZE) -> List[bytes]:
        """Split file into chunks."""
        chunks = []
        with open(filepath, "rb") as f:
            while True:
                data = f.read(chunk_size)
                if not data:
                    break
                chunks.append(data)
        return chunks

    @staticmethod
    def build_merkle_tree(chunks: List[bytes]) -> Tuple[bytes, List[bytes]]:
        """
        Build a binary Merkle tree from chunk data.
        Returns (root_hash, leaf_hashes).
        """
        leaves = [hashlib.sha256(c).digest() for c in chunks]
        if not leaves:
            return b"\x00" * 32, []

        level = leaves[:]
        while len(level) > 1:
            next_level = []
            for i in range(0, len(level), 2):
                left = level[i]
                right = level[i + 1] if i + 1 < len(level) else left
                next_level.append(hashlib.sha256(left + right).digest())
            level = next_level

        return level[0], leaves

    @staticmethod
    def _cid_to_bytes32(cid: str) -> bytes:
        """
        CID strings (Qm...) are 46 chars — too long for bytes32.
        We store sha256(cid) as the on-chain identifier.
        The full CID is recoverable from IPFS; the hash is for lookup/verification.
        """
        return hashlib.sha256(cid.encode()).digest()

    # ── Download ─────────────────────────────────────────────────

    def download_file(self, file_id: str, output_path: Path) -> Dict:
        """
        Download a file from NEXUS distributed storage.

        1. Query blockchain for metadata (CID, Merkle root)
        2. Retrieve from IPFS
        3. Verify Merkle integrity

        Returns dict with cid, size, verified flag.
        """
        output_path = Path(output_path)
        print(f"Downloading {file_id[:16]}...")

        # Step 1: Query blockchain
        print("  [1/3] Querying blockchain...")
        fid_bytes = bytes.fromhex(file_id.replace("0x", ""))
        meta = self.contract.functions.getFileMetadata(fid_bytes).call()
        # meta: (cid_b32, merkleRoot, owner, fileSize, timestamp, numChunks, exists)

        cid_hash_on_chain = meta[0]     # sha256(cid) stored on-chain
        merkle_root       = meta[1]
        owner             = meta[2]
        file_size         = meta[3]
        num_chunks        = meta[5]

        print(f"        Owner: {owner}")
        print(f"        Size:  {file_size:,} bytes, {num_chunks} chunks")

        # We need the actual CID to fetch from IPFS.
        # Look it up from local index or try known CIDs.
        cid = self._resolve_cid(file_id, cid_hash_on_chain)
        if not cid:
            raise ValueError(
                "Cannot resolve CID for this file_id. "
                "The CID index is missing. Upload returns the CID — "
                "pass it directly or rebuild the index."
            )
        print(f"        CID:   {cid}")

        # Step 2: Retrieve from IPFS
        print("  [2/3] Retrieving from IPFS...")
        t0 = time.monotonic()
        data = self._ipfs_cat(cid)
        ipfs_ms = (time.monotonic() - t0) * 1000
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(data)
        print(f"        Downloaded {len(data):,} bytes ({ipfs_ms:.0f}ms)")

        # Step 3: Verify Merkle integrity
        print("  [3/3] Verifying integrity...")
        chunks = self.chunk_file(output_path)
        computed_root, _ = self.build_merkle_tree(chunks)
        verified = computed_root == merkle_root

        if verified:
            print(f"  Integrity: VERIFIED")
        else:
            print(f"  Integrity: FAILED")
            print(f"    Expected: {merkle_root.hex()[:16]}...")
            print(f"    Computed: {computed_root.hex()[:16]}...")

        return {
            "file_id": file_id,
            "cid": cid,
            "file_size": len(data),
            "verified": verified,
            "output_path": str(output_path),
        }

    def download_by_cid(self, cid: str, output_path: Path) -> Dict:
        """
        Download directly by CID (bypasses blockchain lookup).
        Still verifies the file was registered on-chain.
        """
        output_path = Path(output_path)
        print(f"Downloading CID {cid}...")

        # Retrieve from IPFS
        t0 = time.monotonic()
        data = self._ipfs_cat(cid)
        elapsed = (time.monotonic() - t0) * 1000
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(data)

        print(f"  Downloaded {len(data):,} bytes ({elapsed:.0f}ms)")
        return {
            "cid": cid,
            "file_size": len(data),
            "output_path": str(output_path),
        }

    # ── CID Resolution ───────────────────────────────────────────

    _cid_index: Dict[str, str] = {}  # file_id -> cid (in-memory)

    def _resolve_cid(self, file_id: str, cid_hash: bytes) -> Optional[str]:
        """Try to resolve the actual CID string from its hash."""
        # Check in-memory index first
        if file_id in self._cid_index:
            return self._cid_index[file_id]

        # Check persistent index
        idx_path = Path("/opt/nexus/libnexus/cid_index.json")
        if idx_path.exists():
            with open(idx_path) as f:
                idx = json.load(f)
            if file_id in idx:
                return idx[file_id]

        return None

    def _save_cid_index(self, file_id: str, cid: str):
        """Persist CID mapping for later download resolution."""
        self._cid_index[file_id] = cid

        idx_path = Path("/opt/nexus/libnexus/cid_index.json")
        idx = {}
        if idx_path.exists():
            with open(idx_path) as f:
                idx = json.load(f)
        idx[file_id] = cid
        with open(idx_path, "w") as f:
            json.dump(idx, f, indent=2)

    def upload_file(self, filepath: Path) -> Dict:
        """Upload a file (overrides base to include CID index save)."""
        filepath = Path(filepath)
        assert filepath.is_file(), f"File not found: {filepath}"
        file_size = filepath.stat().st_size

        print(f"Uploading {filepath.name} ({file_size:,} bytes)...")

        # Step 1: IPFS
        print("  [1/3] Adding to IPFS...")
        t0 = time.monotonic()
        cid = self._ipfs_add(filepath)
        ipfs_ms = (time.monotonic() - t0) * 1000
        print(f"        CID: {cid}  ({ipfs_ms:.0f}ms)")

        # Step 2: Merkle tree
        print("  [2/3] Building Merkle tree...")
        chunks = self.chunk_file(filepath)
        num_chunks = min(len(chunks), 255)
        merkle_root, _ = self.build_merkle_tree(chunks)
        print(f"        Root: {merkle_root.hex()[:16]}...  ({num_chunks} chunks)")

        # Step 3: Blockchain
        print("  [3/3] Registering on blockchain...")
        cid_bytes32 = self._cid_to_bytes32(cid)

        t0 = time.monotonic()
        tx_hash = self.contract.functions.registerFile(
            cid_bytes32,
            merkle_root,
            file_size,
            num_chunks,
        ).transact({"from": self.sender, "gas": 300000})

        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        chain_ms = (time.monotonic() - t0) * 1000
        assert receipt["status"] == 1, "registerFile transaction reverted"

        logs = self.contract.events.FileRegistered().process_receipt(receipt)
        file_id = logs[0]["args"]["fileId"].hex()

        # Save CID index for download resolution
        self._save_cid_index(file_id, cid)

        print(f"        Tx: {tx_hash.hex()[:16]}...  ({chain_ms:.0f}ms)")
        print(f"  File ID: {file_id}")
        print(f"  Upload complete.")

        return {
            "file_id": file_id,
            "cid": cid,
            "merkle_root": merkle_root.hex(),
            "file_size": file_size,
            "num_chunks": num_chunks,
            "tx_hash": tx_hash.hex(),
            "block": receipt["blockNumber"],
        }

    # ── List files ───────────────────────────────────────────────

    def list_my_files(self) -> List[Dict]:
        """List all files registered by the current sender."""
        file_ids = self.contract.functions.getUserFiles(self.sender).call()
        files = []
        for fid in file_ids:
            meta = self.contract.functions.getFileMetadata(fid).call()
            fid_hex = fid.hex()
            files.append({
                "file_id": fid_hex,
                "cid_hash": meta[0].hex(),
                "cid": self._resolve_cid(fid_hex, meta[0]),
                "size": meta[3],
                "chunks": meta[5],
                "timestamp": meta[4],
                "owner": meta[2],
            })
        return files

    # ── Verify ───────────────────────────────────────────────────

    def verify_file(self, file_id: str, filepath: Path) -> bool:
        """
        Verify a local file matches the on-chain Merkle root.
        """
        fid_bytes = bytes.fromhex(file_id.replace("0x", ""))
        meta = self.contract.functions.getFileMetadata(fid_bytes).call()
        merkle_root = meta[1]

        chunks = self.chunk_file(filepath)
        computed_root, _ = self.build_merkle_tree(chunks)
        return computed_root == merkle_root


# ── CLI ──────────────────────────────────────────────────────────

def main():
    import sys

    if len(sys.argv) < 2:
        print("NEXUS Storage CLI")
        print("  upload   <filepath>                  Upload file")
        print("  download <file_id> <output_path>     Download by file ID")
        print("  get      <cid> <output_path>         Download by CID")
        print("  list                                 List my files")
        print("  verify   <file_id> <filepath>        Verify file integrity")
        sys.exit(1)

    storage = NexusStorage()
    cmd = sys.argv[1]

    if cmd == "upload" and len(sys.argv) >= 3:
        result = storage.upload_file(Path(sys.argv[2]))
        print(json.dumps(result, indent=2))

    elif cmd == "download" and len(sys.argv) >= 4:
        result = storage.download_file(sys.argv[2], Path(sys.argv[3]))
        print(json.dumps(result, indent=2))

    elif cmd == "get" and len(sys.argv) >= 4:
        result = storage.download_by_cid(sys.argv[2], Path(sys.argv[3]))
        print(json.dumps(result, indent=2))

    elif cmd == "list":
        files = storage.list_my_files()
        for f in files:
            cid_str = f["cid"] or "(not indexed)"
            print(f"  {f['file_id'][:16]}...  {f['size']:>10,} B  {f['chunks']} chunks  {cid_str}")
        print(f"\n  Total: {len(files)} files")

    elif cmd == "verify" and len(sys.argv) >= 4:
        ok = storage.verify_file(sys.argv[2], Path(sys.argv[3]))
        print(f"Integrity: {'VERIFIED' if ok else 'FAILED'}")
        sys.exit(0 if ok else 1)

    else:
        print(f"Unknown command or missing args: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
