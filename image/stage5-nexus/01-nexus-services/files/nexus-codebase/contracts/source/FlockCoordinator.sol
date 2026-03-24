// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract FlockCoordinator {

    // ── Structs ──────────────────────────────────────────────────────────

    struct GradientSubmission {
        address contributor;
        bytes32 gradientHash;
        uint256 epoch;
        uint256 qualityScore;
        uint256 rstStake;
        uint256 timestamp;
    }

    struct Epoch {
        uint256 epochId;
        bytes32 dailySalt;
        uint256 startBlock;
        uint256 endBlock;
        uint256 submissionCount;
        bytes32 aggregatedModelHash;
        bool finalized;
    }

    // ── State ────────────────────────────────────────────────────────────

    mapping(uint256 => Epoch) public epochs;
    mapping(uint256 => GradientSubmission[]) private _epochSubmissions;
    uint256 public currentEpoch;
    uint256 public totalSubmissions;
    address public admin;

    // ── Events ───────────────────────────────────────────────────────────

    event EpochStarted(uint256 indexed epochId, bytes32 dailySalt, uint256 startBlock);
    event GradientSubmitted(
        uint256 indexed epochId,
        address indexed contributor,
        bytes32 gradientHash,
        uint256 qualityScore
    );
    event EpochFinalized(
        uint256 indexed epochId,
        bytes32 aggregatedModelHash,
        uint256 submissions
    );

    // ── Modifiers ────────────────────────────────────────────────────────

    modifier onlyAdmin() {
        require(msg.sender == admin, "Not admin");
        _;
    }

    // ── Constructor ──────────────────────────────────────────────────────

    constructor() {
        admin = msg.sender;
    }

    // ── Epoch lifecycle ──────────────────────────────────────────────────

    function startEpoch() external onlyAdmin {
        if (currentEpoch > 0) {
            require(epochs[currentEpoch].finalized, "Current epoch not finalized");
        }

        currentEpoch++;
        bytes32 salt = keccak256(abi.encodePacked(
            block.timestamp, block.number, currentEpoch
        ));

        epochs[currentEpoch] = Epoch({
            epochId: currentEpoch,
            dailySalt: salt,
            startBlock: block.number,
            endBlock: 0,
            submissionCount: 0,
            aggregatedModelHash: bytes32(0),
            finalized: false
        });

        emit EpochStarted(currentEpoch, salt, block.number);
    }

    function submitGradient(bytes32 gradientHash, uint256 qualityScore) external {
        require(currentEpoch > 0, "No active epoch");
        Epoch storage ep = epochs[currentEpoch];
        require(!ep.finalized, "Epoch finalized");

        _epochSubmissions[currentEpoch].push(GradientSubmission({
            contributor: msg.sender,
            gradientHash: gradientHash,
            epoch: currentEpoch,
            qualityScore: qualityScore,
            rstStake: 0,
            timestamp: block.timestamp
        }));

        ep.submissionCount++;
        totalSubmissions++;

        emit GradientSubmitted(currentEpoch, msg.sender, gradientHash, qualityScore);
    }

    function finalizeEpoch(bytes32 aggregatedModelHash) external onlyAdmin {
        require(currentEpoch > 0, "No active epoch");
        Epoch storage ep = epochs[currentEpoch];
        require(!ep.finalized, "Already finalized");

        ep.endBlock = block.number;
        ep.aggregatedModelHash = aggregatedModelHash;
        ep.finalized = true;

        emit EpochFinalized(currentEpoch, aggregatedModelHash, ep.submissionCount);
    }

    // ── Read functions ───────────────────────────────────────────────────

    function getEpochSubmissions(uint256 epochId) external view returns (GradientSubmission[] memory) {
        return _epochSubmissions[epochId];
    }

    function getDailySalt(uint256 epochId) external view returns (bytes32) {
        return epochs[epochId].dailySalt;
    }

    function getCurrentEpoch() external view returns (Epoch memory) {
        return epochs[currentEpoch];
    }

    function getSubmissionCount(uint256 epochId) external view returns (uint256) {
        return epochs[epochId].submissionCount;
    }
}
