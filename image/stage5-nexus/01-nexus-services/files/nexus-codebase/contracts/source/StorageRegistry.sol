// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/**
 * @title StorageRegistry
 * @dev Metadata registry for NEXUS OS distributed storage.
 *
 * CRITICAL: This contract stores ONLY metadata, not file data.
 * Actual files are stored in IPFS. The blockchain coordinates who stores what.
 */
contract StorageRegistry {

    // File metadata structure
    struct FileMetadata {
        bytes32 cid;            // IPFS Content ID (hash)
        bytes32 merkleRoot;     // Root of chunk Merkle tree for integrity
        address owner;          // File owner (Ethereum address)
        uint256 fileSize;       // Original file size in bytes
        uint256 timestamp;      // Upload timestamp
        uint8   numChunks;      // Number of chunks (max 255)
        bool    exists;         // Whether file is registered
    }

    // Chunk assignment structure
    struct ChunkAssignment {
        bytes32   fileId;       // Reference to file
        uint8     chunkIndex;   // Which chunk (0-254)
        address[] storageNodes; // Nodes storing this chunk
        uint256   lastVerified; // Last proof-of-storage verification
    }

    // ── Storage ─────────────────────────────────────────────────
    mapping(bytes32  => FileMetadata)       public files;
    mapping(bytes32  => ChunkAssignment[])  private _chunks;
    mapping(address  => bytes32[])          private _userFiles;
    mapping(address  => uint256)            public storageCommitment;

    uint256 public fileCount;

    // ── Events ──────────────────────────────────────────────────
    event FileRegistered(
        bytes32 indexed fileId,
        bytes32 cid,
        address indexed owner,
        uint256 fileSize,
        uint8   numChunks
    );

    event ChunksAssigned(
        bytes32 indexed fileId,
        uint8   numChunks,
        uint256 totalNodes
    );

    event StorageProofSubmitted(
        bytes32 indexed fileId,
        uint8   chunkIndex,
        address indexed node,
        bool    valid
    );

    // ── File registration ───────────────────────────────────────

    /**
     * @dev Register a new file in the distributed storage system.
     * @param cid        IPFS content identifier (first 32 bytes)
     * @param merkleRoot Merkle tree root of all chunks
     * @param fileSize   Original file size in bytes
     * @param numChunks  Number of chunks file is split into
     * @return fileId    Unique identifier for this file
     */
    function registerFile(
        bytes32 cid,
        bytes32 merkleRoot,
        uint256 fileSize,
        uint8   numChunks
    ) external returns (bytes32 fileId) {
        require(numChunks > 0, "Must have at least one chunk");

        fileId = keccak256(abi.encodePacked(cid, msg.sender, block.timestamp));
        require(!files[fileId].exists, "File already registered");

        files[fileId] = FileMetadata({
            cid:        cid,
            merkleRoot: merkleRoot,
            owner:      msg.sender,
            fileSize:   fileSize,
            timestamp:  block.timestamp,
            numChunks:  numChunks,
            exists:     true
        });

        _userFiles[msg.sender].push(fileId);
        fileCount++;

        emit FileRegistered(fileId, cid, msg.sender, fileSize, numChunks);
        return fileId;
    }

    // ── Chunk assignment ────────────────────────────────────────

    /**
     * @dev Assign chunk storage to specific nodes.
     * @param fileId        File to assign chunks for
     * @param chunkIndices  Array of chunk indices
     * @param storageNodes  Parallel array: nodes storing each chunk
     */
    function assignChunks(
        bytes32     fileId,
        uint8[]     calldata chunkIndices,
        address[][] calldata storageNodes
    ) external {
        require(files[fileId].exists, "File not registered");
        require(files[fileId].owner == msg.sender, "Not file owner");
        require(chunkIndices.length == storageNodes.length, "Array length mismatch");

        uint256 totalNodes = 0;
        uint256 chunkSize  = files[fileId].fileSize / files[fileId].numChunks;

        for (uint256 i = 0; i < chunkIndices.length; i++) {
            require(chunkIndices[i] < files[fileId].numChunks, "Invalid chunk index");

            _chunks[fileId].push(ChunkAssignment({
                fileId:       fileId,
                chunkIndex:   chunkIndices[i],
                storageNodes: storageNodes[i],
                lastVerified: block.timestamp
            }));

            for (uint256 j = 0; j < storageNodes[i].length; j++) {
                storageCommitment[storageNodes[i][j]] += chunkSize;
            }
            totalNodes += storageNodes[i].length;
        }

        emit ChunksAssigned(fileId, uint8(chunkIndices.length), totalNodes);
    }

    // ── Storage proofs ──────────────────────────────────────────

    /**
     * @dev Submit proof of storage for a chunk (simplified).
     * @param fileId     File being verified
     * @param chunkIndex Which chunk
     */
    function submitStorageProof(
        bytes32 fileId,
        uint8   chunkIndex,
        bytes32 /* proof */
    ) external returns (bool valid) {
        require(files[fileId].exists, "File not found");

        ChunkAssignment[] storage fileChunks = _chunks[fileId];
        for (uint256 i = 0; i < fileChunks.length; i++) {
            if (fileChunks[i].chunkIndex == chunkIndex) {
                fileChunks[i].lastVerified = block.timestamp;
                emit StorageProofSubmitted(fileId, chunkIndex, msg.sender, true);
                return true;
            }
        }

        emit StorageProofSubmitted(fileId, chunkIndex, msg.sender, false);
        return false;
    }

    // ── View functions ──────────────────────────────────────────

    function getFileMetadata(bytes32 fileId)
        external view returns (FileMetadata memory)
    {
        require(files[fileId].exists, "File not found");
        return files[fileId];
    }

    function getChunkAssignments(bytes32 fileId)
        external view returns (ChunkAssignment[] memory)
    {
        require(files[fileId].exists, "File not found");
        return _chunks[fileId];
    }

    function getUserFiles(address owner)
        external view returns (bytes32[] memory)
    {
        return _userFiles[owner];
    }

    function getStorageCommitment(address node)
        external view returns (uint256)
    {
        return storageCommitment[node];
    }
}
