// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract NetworkObscuration {

    // ── Structs ──────────────────────────────────────────────────────────

    struct PrivacyProof {
        address contributor;
        bytes32 datasetMerkleRoot;
        uint256 epoch;
        uint256 epsilon;
        bytes32 saltUsed;
        uint256 timestamp;
        bool verified;
    }

    // ── State ────────────────────────────────────────────────────────────

    mapping(uint256 => PrivacyProof[]) private _epochProofs;
    uint256 public totalProofs;
    uint256 public minEpsilon;
    address public admin;

    // ── Events ───────────────────────────────────────────────────────────

    event PrivacyProofSubmitted(
        uint256 indexed epoch,
        uint256 proofIndex,
        address indexed contributor,
        bytes32 datasetMerkleRoot,
        uint256 epsilon
    );
    event PrivacyProofVerified(
        uint256 indexed epoch,
        uint256 proofIndex,
        address indexed contributor
    );
    event PrivacyProofRejected(
        uint256 indexed epoch,
        uint256 proofIndex,
        address indexed contributor,
        string reason
    );

    // ── Modifiers ────────────────────────────────────────────────────────

    modifier onlyAdmin() {
        require(msg.sender == admin, "Not admin");
        _;
    }

    // ── Constructor ──────────────────────────────────────────────────────

    constructor(uint256 _minEpsilon) {
        admin = msg.sender;
        minEpsilon = _minEpsilon > 0 ? _minEpsilon : 100; // default ε=0.1 (scaled by 1000)
    }

    // ── Write functions ──────────────────────────────────────────────────

    function submitPrivacyProof(
        bytes32 datasetRoot,
        uint256 epsilon,
        bytes32 saltUsed
    ) external returns (uint256) {
        require(datasetRoot != bytes32(0), "Empty dataset root");
        require(saltUsed != bytes32(0), "Empty salt");
        require(epsilon >= minEpsilon, "Epsilon below minimum");

        // Derive current epoch from proof count (monotonic)
        uint256 epoch = totalProofs / 100 + 1;

        uint256 proofIndex = _epochProofs[epoch].length;

        _epochProofs[epoch].push(PrivacyProof({
            contributor: msg.sender,
            datasetMerkleRoot: datasetRoot,
            epoch: epoch,
            epsilon: epsilon,
            saltUsed: saltUsed,
            timestamp: block.timestamp,
            verified: false
        }));

        totalProofs++;

        emit PrivacyProofSubmitted(epoch, proofIndex, msg.sender, datasetRoot, epsilon);
        return proofIndex;
    }

    function verifyProof(
        uint256 epoch,
        uint256 proofIndex,
        bytes32 expectedSalt
    ) external onlyAdmin {
        require(proofIndex < _epochProofs[epoch].length, "Invalid proof index");
        PrivacyProof storage proof = _epochProofs[epoch][proofIndex];
        require(!proof.verified, "Already verified");

        if (proof.saltUsed == expectedSalt) {
            proof.verified = true;
            emit PrivacyProofVerified(epoch, proofIndex, proof.contributor);
        } else {
            emit PrivacyProofRejected(
                epoch, proofIndex, proof.contributor,
                "Salt mismatch - potential re-identification attempt"
            );
        }
    }

    function setMinEpsilon(uint256 newMin) external onlyAdmin {
        require(newMin > 0, "Must be > 0");
        minEpsilon = newMin;
    }

    // ── Read functions ───────────────────────────────────────────────────

    function getEpochProofs(uint256 epoch) external view returns (
        address[] memory contributors,
        bytes32[] memory datasetRoots,
        uint256[] memory epsilons,
        bytes32[] memory salts,
        uint256[] memory timestamps,
        bool[] memory verifiedFlags
    ) {
        PrivacyProof[] storage proofs = _epochProofs[epoch];
        uint256 n = proofs.length;

        contributors = new address[](n);
        datasetRoots = new bytes32[](n);
        epsilons = new uint256[](n);
        salts = new bytes32[](n);
        timestamps = new uint256[](n);
        verifiedFlags = new bool[](n);

        for (uint256 i = 0; i < n; i++) {
            PrivacyProof storage p = proofs[i];
            contributors[i] = p.contributor;
            datasetRoots[i] = p.datasetMerkleRoot;
            epsilons[i] = p.epsilon;
            salts[i] = p.saltUsed;
            timestamps[i] = p.timestamp;
            verifiedFlags[i] = p.verified;
        }
    }

    function getVerifiedCount(uint256 epoch) external view returns (uint256) {
        PrivacyProof[] storage proofs = _epochProofs[epoch];
        uint256 count = 0;
        for (uint256 i = 0; i < proofs.length; i++) {
            if (proofs[i].verified) {
                count++;
            }
        }
        return count;
    }

    function getProof(uint256 epoch, uint256 proofIndex) external view returns (
        address contributor,
        bytes32 datasetMerkleRoot,
        uint256 epsilon,
        bytes32 saltUsed,
        uint256 timestamp,
        bool verified
    ) {
        require(proofIndex < _epochProofs[epoch].length, "Invalid proof index");
        PrivacyProof storage p = _epochProofs[epoch][proofIndex];
        return (p.contributor, p.datasetMerkleRoot, p.epsilon, p.saltUsed, p.timestamp, p.verified);
    }

    function getEpochProofCount(uint256 epoch) external view returns (uint256) {
        return _epochProofs[epoch].length;
    }
}
