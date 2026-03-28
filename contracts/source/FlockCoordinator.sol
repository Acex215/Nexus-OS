// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title FlockCoordinator
 * @notice Manages federated learning epochs, gradient submissions,
 *         contribution scoring, and model checkpoint tracking.
 *
 * @dev Daily cycle:
 *   00:00 UTC: startEpoch() — generate salt, set epoch ID
 *   00:00-23:49: nodes submit gradients via submitGradient()
 *   23:50: finalizeEpoch() — score contributions, adjust RST, record model CID
 *
 * @dev The contract NEVER sees raw behavioral data or feature vectors.
 *      It only sees: gradient hashes (bytes32), quality scores (uint16),
 *      and model checkpoint CIDs (IPFS strings).
 */
contract FlockCoordinator {

    // ═══════════════════════════════════════════
    // STATE
    // ═══════════════════════════════════════════

    struct Epoch {
        uint256 epochId;
        bytes32 dailySalt;
        uint32 startTime;
        uint32 endTime;         // 0 until finalized
        uint256 submissionCount;
        string modelCID;        // IPFS CID of the model checkpoint after this epoch
        bool finalized;
    }

    struct GradientSubmission {
        address node;
        bytes32 gradientHash;   // keccak256 of the obfuscated gradient
        uint16 qualityScore;    // Self-reported local validation score (0-10000)
        uint32 timestamp;
        uint256 epochId;
        bool scored;            // Whether contribution scoring has been applied
        uint16 contributionScore; // Assigned after finalization (0-10000)
    }

    // Current epoch
    uint256 public currentEpochId;
    mapping(uint256 => Epoch) public epochs;

    // Submissions per epoch
    mapping(uint256 => GradientSubmission[]) public epochSubmissions;
    mapping(uint256 => mapping(address => bool)) public hasSubmitted;

    // Contribution scores (cumulative across epochs)
    mapping(address => uint256) public totalContributions;
    mapping(address => uint256) public epochsParticipated;
    mapping(address => uint256) public cumulativeQualityScore;

    // Model checkpoint history
    string[] public modelCheckpoints;  // IPFS CIDs in order

    // Admin
    address public admin;
    bool public adminLocked;

    // Reference to TokenManager for RST adjustments
    address public tokenManagerAddress;

    // ═══════════════════════════════════════════
    // EVENTS
    // ═══════════════════════════════════════════

    event EpochStarted(
        uint256 indexed epochId,
        bytes32 dailySalt,
        uint32 startTime
    );

    event GradientSubmitted(
        uint256 indexed epochId,
        address indexed node,
        bytes32 gradientHash,
        uint16 qualityScore
    );

    event EpochFinalized(
        uint256 indexed epochId,
        uint256 submissionCount,
        string modelCID
    );

    event ContributionScored(
        uint256 indexed epochId,
        address indexed node,
        uint16 contributionScore
    );

    event ModelCheckpointRecorded(
        uint256 indexed epochId,
        string cid
    );

    // ═══════════════════════════════════════════
    // MODIFIERS
    // ═══════════════════════════════════════════

    modifier onlyAdmin() {
        require(msg.sender == admin, "Not admin");
        require(!adminLocked, "Admin locked");
        _;
    }

    modifier epochActive() {
        require(currentEpochId > 0, "No epoch started");
        require(!epochs[currentEpochId].finalized, "Epoch finalized");
        _;
    }

    // ═══════════════════════════════════════════
    // CONSTRUCTOR
    // ═══════════════════════════════════════════

    constructor(address _tokenManager) {
        admin = msg.sender;
        adminLocked = false;
        tokenManagerAddress = _tokenManager;
        currentEpochId = 0;
    }

    // ═══════════════════════════════════════════
    // EPOCH MANAGEMENT
    // ═══════════════════════════════════════════

    /**
     * @notice Start a new epoch. Generates daily salt from block state.
     * @dev Called at 00:00 UTC by the epoch processing script.
     */
    function startEpoch() external onlyAdmin returns (uint256 epochId, bytes32 salt) {
        // Finalize previous epoch if it wasn't finalized
        if (currentEpochId > 0 && !epochs[currentEpochId].finalized) {
            _finalizeEpoch(currentEpochId, "");
        }

        currentEpochId++;
        epochId = currentEpochId;

        // Generate daily salt from unpredictable block state
        salt = keccak256(abi.encodePacked(
            block.timestamp,
            block.number,
            blockhash(block.number - 1),
            epochId
        ));

        epochs[epochId] = Epoch({
            epochId: epochId,
            dailySalt: salt,
            startTime: uint32(block.timestamp),
            endTime: 0,
            submissionCount: 0,
            modelCID: "",
            finalized: false
        });

        emit EpochStarted(epochId, salt, uint32(block.timestamp));
        return (epochId, salt);
    }

    /**
     * @notice Get the daily salt for an epoch.
     */
    function getDailySalt(uint256 epochId) external view returns (bytes32) {
        return epochs[epochId].dailySalt;
    }

    /**
     * @notice Get the current epoch's daily salt.
     */
    function getCurrentSalt() external view returns (bytes32) {
        return epochs[currentEpochId].dailySalt;
    }

    // ═══════════════════════════════════════════
    // GRADIENT SUBMISSION
    // ═══════════════════════════════════════════

    /**
     * @notice Submit a gradient hash for the current epoch.
     * @param gradientHash keccak256 hash of the obfuscated feature gradient
     * @param qualityScore Self-reported local validation quality (0-10000)
     * @dev Each node can only submit once per epoch.
     *      The contract never sees raw data — only the hash.
     */
    function submitGradient(
        bytes32 gradientHash,
        uint16 qualityScore
    ) external epochActive {
        require(!hasSubmitted[currentEpochId][msg.sender], "Already submitted this epoch");
        require(qualityScore <= 10000, "Score must be 0-10000");

        epochSubmissions[currentEpochId].push(GradientSubmission({
            node: msg.sender,
            gradientHash: gradientHash,
            qualityScore: qualityScore,
            timestamp: uint32(block.timestamp),
            epochId: currentEpochId,
            scored: false,
            contributionScore: 0
        }));

        hasSubmitted[currentEpochId][msg.sender] = true;
        epochs[currentEpochId].submissionCount++;

        emit GradientSubmitted(currentEpochId, msg.sender, gradientHash, qualityScore);
    }

    // ═══════════════════════════════════════════
    // EPOCH FINALIZATION
    // ═══════════════════════════════════════════

    /**
     * @notice Finalize the current epoch with model checkpoint.
     * @param modelCID IPFS CID of the new model checkpoint after federated averaging
     * @dev Called at 23:50 UTC by the epoch processing script.
     */
    function finalizeEpoch(string calldata modelCID) external onlyAdmin {
        require(currentEpochId > 0, "No epoch");
        require(!epochs[currentEpochId].finalized, "Already finalized");
        _finalizeEpoch(currentEpochId, modelCID);
    }

    function _finalizeEpoch(uint256 epochId, string memory modelCID) internal {
        Epoch storage epoch = epochs[epochId];
        epoch.endTime = uint32(block.timestamp);
        epoch.finalized = true;

        if (bytes(modelCID).length > 0) {
            epoch.modelCID = modelCID;
            modelCheckpoints.push(modelCID);
            emit ModelCheckpointRecorded(epochId, modelCID);
        }

        emit EpochFinalized(epochId, epoch.submissionCount, modelCID);
    }

    // ═══════════════════════════════════════════
    // CONTRIBUTION SCORING
    // ═══════════════════════════════════════════

    /**
     * @notice Score a node's contribution for an epoch.
     * @param epochId The epoch to score
     * @param submissionIndex Index in the epochSubmissions array
     * @param contributionScore The computed contribution score (0-10000)
     * @dev Called by the off-chain scoring engine after finalization.
     *      The score represents how much removing this gradient
     *      degraded the meta-model (leave-one-out evaluation).
     */
    function scoreContribution(
        uint256 epochId,
        uint256 submissionIndex,
        uint16 contributionScore
    ) external onlyAdmin {
        require(epochs[epochId].finalized, "Epoch not finalized");
        GradientSubmission storage sub = epochSubmissions[epochId][submissionIndex];
        require(!sub.scored, "Already scored");

        sub.scored = true;
        sub.contributionScore = contributionScore;

        // Update cumulative stats
        totalContributions[sub.node] += contributionScore;
        epochsParticipated[sub.node]++;
        cumulativeQualityScore[sub.node] += sub.qualityScore;

        emit ContributionScored(epochId, sub.node, contributionScore);
    }

    // ═══════════════════════════════════════════
    // QUERY FUNCTIONS
    // ═══════════════════════════════════════════

    function getEpoch(uint256 epochId) external view returns (
        bytes32 dailySalt, uint32 startTime, uint32 endTime,
        uint256 submissionCount, string memory modelCID, bool finalized
    ) {
        Epoch storage e = epochs[epochId];
        return (e.dailySalt, e.startTime, e.endTime,
                e.submissionCount, e.modelCID, e.finalized);
    }

    function getSubmission(uint256 epochId, uint256 index) external view returns (
        address node, bytes32 gradientHash, uint16 qualityScore,
        uint32 timestamp, bool scored, uint16 contributionScore
    ) {
        GradientSubmission storage s = epochSubmissions[epochId][index];
        return (s.node, s.gradientHash, s.qualityScore,
                s.timestamp, s.scored, s.contributionScore);
    }

    function getEpochSubmissionCount(uint256 epochId) external view returns (uint256) {
        return epochSubmissions[epochId].length;
    }

    function getNodeStats(address node) external view returns (
        uint256 contributions, uint256 participated, uint256 avgQuality
    ) {
        uint256 ep = epochsParticipated[node];
        uint256 avg = ep > 0 ? cumulativeQualityScore[node] / ep : 0;
        return (totalContributions[node], ep, avg);
    }

    function getLatestModelCID() external view returns (string memory) {
        if (modelCheckpoints.length == 0) return "";
        return modelCheckpoints[modelCheckpoints.length - 1];
    }

    function getModelCheckpointCount() external view returns (uint256) {
        return modelCheckpoints.length;
    }

    // ═══════════════════════════════════════════
    // ADMIN
    // ═══════════════════════════════════════════

    function setTokenManager(address _tokenManager) external onlyAdmin {
        tokenManagerAddress = _tokenManager;
    }

    function lockAdmin() external onlyAdmin {
        adminLocked = true;
        admin = address(0);
    }
}
