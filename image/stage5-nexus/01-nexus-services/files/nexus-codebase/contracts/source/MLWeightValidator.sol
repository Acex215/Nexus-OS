// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract MLWeightValidator {

    // ── Structs ──────────────────────────────────────────────────────────

    struct ModelUpdate {
        bytes32 weightsHash;
        string ipfsCID;
        address submitter;
        uint256 epoch;
        uint256 validationScore;
        uint256 approvals;
        uint256 rejections;
        bool accepted;
        bool resolved;
        uint256 timestamp;
    }

    // ── State ────────────────────────────────────────────────────────────

    ModelUpdate[] public updates;
    uint256 public updateCount;
    uint256 public requiredApprovals;
    uint256 public latestAcceptedId;
    address public admin;

    // Validator votes tracked separately (mappings cannot live inside memory structs)
    mapping(uint256 => mapping(address => bool)) private _hasVoted;

    // ── Events ───────────────────────────────────────────────────────────

    event WeightsSubmitted(
        uint256 indexed updateId,
        address indexed submitter,
        bytes32 weightsHash,
        string ipfsCID,
        uint256 epoch,
        uint256 validationScore
    );
    event WeightsValidated(
        uint256 indexed updateId,
        address indexed validator,
        bool approve
    );
    event WeightsAccepted(
        uint256 indexed updateId,
        bytes32 weightsHash,
        string ipfsCID,
        uint256 approvals
    );
    event WeightsRejected(
        uint256 indexed updateId,
        bytes32 weightsHash,
        uint256 rejections
    );

    // ── Modifiers ────────────────────────────────────────────────────────

    modifier onlyAdmin() {
        require(msg.sender == admin, "Not admin");
        _;
    }

    // ── Constructor ──────────────────────────────────────────────────────

    constructor(uint256 _requiredApprovals) {
        admin = msg.sender;
        requiredApprovals = _requiredApprovals > 0 ? _requiredApprovals : 2;
    }

    // ── Write functions ──────────────────────────────────────────────────

    function submitWeights(
        bytes32 weightsHash,
        string calldata ipfsCID,
        uint256 validationScore
    ) external returns (uint256) {
        require(weightsHash != bytes32(0), "Empty weights hash");
        require(bytes(ipfsCID).length > 0, "Empty IPFS CID");

        uint256 updateId = updates.length;

        updates.push(ModelUpdate({
            weightsHash: weightsHash,
            ipfsCID: ipfsCID,
            submitter: msg.sender,
            epoch: updateId + 1,
            validationScore: validationScore,
            approvals: 0,
            rejections: 0,
            accepted: false,
            resolved: false,
            timestamp: block.timestamp
        }));

        updateCount++;

        emit WeightsSubmitted(updateId, msg.sender, weightsHash, ipfsCID, updateId + 1, validationScore);
        return updateId;
    }

    function validateWeights(uint256 updateId, bool approve) external {
        require(updateId < updates.length, "Invalid update ID");
        ModelUpdate storage u = updates[updateId];
        require(!u.resolved, "Already resolved");
        require(!_hasVoted[updateId][msg.sender], "Already voted");

        _hasVoted[updateId][msg.sender] = true;

        if (approve) {
            u.approvals++;
        } else {
            u.rejections++;
        }

        emit WeightsValidated(updateId, msg.sender, approve);

        if (u.approvals >= requiredApprovals) {
            u.accepted = true;
            u.resolved = true;
            latestAcceptedId = updateId;
            emit WeightsAccepted(updateId, u.weightsHash, u.ipfsCID, u.approvals);
        } else if (u.rejections >= requiredApprovals) {
            u.resolved = true;
            emit WeightsRejected(updateId, u.weightsHash, u.rejections);
        }
    }

    function setRequiredApprovals(uint256 _required) external onlyAdmin {
        require(_required > 0, "Must be > 0");
        requiredApprovals = _required;
    }

    // ── Read functions ───────────────────────────────────────────────────

    function getLatestAcceptedWeights() external view returns (
        uint256 updateId,
        bytes32 weightsHash,
        string memory ipfsCID,
        address submitter,
        uint256 epoch,
        uint256 validationScore,
        uint256 approvals,
        uint256 timestamp
    ) {
        require(updates.length > 0, "No updates");
        ModelUpdate storage u = updates[latestAcceptedId];
        require(u.accepted, "No accepted weights");
        return (
            latestAcceptedId,
            u.weightsHash,
            u.ipfsCID,
            u.submitter,
            u.epoch,
            u.validationScore,
            u.approvals,
            u.timestamp
        );
    }

    function getUpdate(uint256 updateId) external view returns (
        bytes32 weightsHash,
        string memory ipfsCID,
        address submitter,
        uint256 epoch,
        uint256 validationScore,
        uint256 approvals,
        uint256 rejections,
        bool accepted,
        bool resolved,
        uint256 timestamp
    ) {
        require(updateId < updates.length, "Invalid update ID");
        ModelUpdate storage u = updates[updateId];
        return (
            u.weightsHash, u.ipfsCID, u.submitter, u.epoch,
            u.validationScore, u.approvals, u.rejections,
            u.accepted, u.resolved, u.timestamp
        );
    }

    function getUpdateHistory(uint256 count) external view returns (
        uint256[] memory ids,
        bytes32[] memory hashes,
        address[] memory submitters,
        bool[] memory acceptedFlags,
        uint256[] memory timestamps
    ) {
        uint256 total = updates.length;
        uint256 n = count < total ? count : total;
        uint256 start = total - n;

        ids = new uint256[](n);
        hashes = new bytes32[](n);
        submitters = new address[](n);
        acceptedFlags = new bool[](n);
        timestamps = new uint256[](n);

        for (uint256 i = 0; i < n; i++) {
            ModelUpdate storage u = updates[start + i];
            ids[i] = start + i;
            hashes[i] = u.weightsHash;
            submitters[i] = u.submitter;
            acceptedFlags[i] = u.accepted;
            timestamps[i] = u.timestamp;
        }
    }

    function hasVoted(uint256 updateId, address validator) external view returns (bool) {
        return _hasVoted[updateId][validator];
    }

    function getUpdateCount() external view returns (uint256) {
        return updates.length;
    }
}
