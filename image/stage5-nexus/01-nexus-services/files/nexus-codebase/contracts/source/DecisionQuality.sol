// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

interface IReasoningLedger {
    function getEntry(uint256 entryId) external view returns (
        address agent,
        uint256 timestamp,
        string memory decision,
        string memory reasoning,
        bytes32 entryHash
    );
}

interface ITokenManager {
    function earnRST(address agent, uint256 amount, string calldata reason) external;
    function slashRST(address agent, uint256 amount, string calldata reason) external;
}

contract DecisionQuality {

    // ── State ────────────────────────────────────────────────────────────

    address public admin;
    IReasoningLedger public reasoningLedger;
    ITokenManager public tokenManager;

    uint256 public constant WINDOW_SIZE = 20;

    uint256 public rewardThreshold;
    uint256 public penaltyThreshold;
    uint256 public rewardAmount;
    uint256 public penaltyAmount;
    uint256 public evalCooldown;

    // ── Outcome storage ──────────────────────────────────────────────────

    struct Outcome {
        bool submitted;
        bool success;
        uint8 impact;
        address submitter;
        uint256 timestamp;
    }

    mapping(uint256 => Outcome) public outcomes;

    // ── Per-agent stats ──────────────────────────────────────────────────

    struct AgentStats {
        uint256 totalDecisions;
        uint256 successCount;
        uint256 impactSum;
        uint256 lastEvalBlock;
    }

    mapping(address => AgentStats) public agentStats;
    mapping(address => uint256[]) private _agentDecisionIds;

    // ── Events ───────────────────────────────────────────────────────────

    event OutcomeSubmitted(
        uint256 indexed decisionId,
        address indexed agent,
        bool success,
        uint8 impact,
        uint256 timestamp
    );

    event QualityScoreCalculated(
        address indexed agent,
        uint256 score,
        uint256 windowSize,
        uint256 successes,
        uint256 avgImpact,
        uint256 timestamp
    );

    event RewardTriggered(
        address indexed agent,
        uint256 score,
        uint256 rstAmount,
        uint256 timestamp
    );

    event PenaltyTriggered(
        address indexed agent,
        uint256 score,
        uint256 rstAmount,
        uint256 timestamp
    );

    event ThresholdsUpdated(
        uint256 rewardThreshold,
        uint256 penaltyThreshold,
        uint256 rewardAmount,
        uint256 penaltyAmount
    );

    // ── Modifiers ────────────────────────────────────────────────────────

    modifier onlyAdmin() {
        require(msg.sender == admin, "Not admin");
        _;
    }

    // ── Constructor ──────────────────────────────────────────────────────

    constructor(address _reasoningLedger, address _tokenManager) {
        admin = msg.sender;
        reasoningLedger = IReasoningLedger(_reasoningLedger);
        tokenManager = ITokenManager(_tokenManager);

        rewardThreshold = 75;
        penaltyThreshold = 30;
        rewardAmount = 10;
        penaltyAmount = 5;
        evalCooldown = 50;
    }

    // ── Submit outcomes ──────────────────────────────────────────────────

    function submitOutcome(
        uint256 decisionId,
        bool success,
        uint8 impact
    ) public {
        require(!outcomes[decisionId].submitted, "Already submitted");

        (address agent,,,,) = reasoningLedger.getEntry(decisionId);
        require(agent != address(0), "Decision not found");

        outcomes[decisionId] = Outcome({
            submitted: true,
            success: success,
            impact: impact,
            submitter: msg.sender,
            timestamp: block.timestamp
        });

        AgentStats storage stats = agentStats[agent];
        stats.totalDecisions++;
        if (success) {
            stats.successCount++;
        }
        stats.impactSum += impact;
        _agentDecisionIds[agent].push(decisionId);

        emit OutcomeSubmitted(decisionId, agent, success, impact, block.timestamp);
    }

    function batchSubmitOutcomes(
        uint256[] calldata decisionIds,
        bool[] calldata successes,
        uint8[] calldata impacts
    ) external {
        require(decisionIds.length == successes.length, "Length mismatch");
        require(decisionIds.length == impacts.length, "Length mismatch");
        for (uint256 i = 0; i < decisionIds.length; i++) {
            submitOutcome(decisionIds[i], successes[i], impacts[i]);
        }
    }

    // ── Quality scoring ──────────────────────────────────────────────────

    function calculateQualityScore(address agent) public view returns (
        uint256 score,
        uint256 windowUsed,
        uint256 successes,
        uint256 avgImpact
    ) {
        uint256[] storage ids = _agentDecisionIds[agent];
        uint256 total = ids.length;
        if (total == 0) {
            return (0, 0, 0, 0);
        }

        windowUsed = total < WINDOW_SIZE ? total : WINDOW_SIZE;
        uint256 start = total - windowUsed;

        uint256 impactAccum = 0;
        for (uint256 i = start; i < total; i++) {
            Outcome storage o = outcomes[ids[i]];
            if (o.success) {
                successes++;
            }
            impactAccum += o.impact;
        }

        avgImpact = impactAccum / windowUsed;

        // Score: 60% success rate + 40% avg impact (impact 0-10 scaled to 0-100)
        uint256 successPart = successes * 60 / windowUsed;
        uint256 impactPart = avgImpact * 4;
        score = successPart + impactPart;
    }

    // ── Rewards & penalties ──────────────────────────────────────────────

    function triggerReward(address agent) external {
        AgentStats storage stats = agentStats[agent];
        require(block.number >= stats.lastEvalBlock + evalCooldown, "Cooldown active");

        (uint256 score, uint256 windowUsed, uint256 successes, uint256 avgImpact) = calculateQualityScore(agent);
        require(score >= rewardThreshold, "Score below reward threshold");

        stats.lastEvalBlock = block.number;
        tokenManager.earnRST(agent, rewardAmount, "DecisionQuality reward");

        emit QualityScoreCalculated(agent, score, windowUsed, successes, avgImpact, block.timestamp);
        emit RewardTriggered(agent, score, rewardAmount, block.timestamp);
    }

    function triggerPenalty(address agent) external {
        AgentStats storage stats = agentStats[agent];
        require(block.number >= stats.lastEvalBlock + evalCooldown, "Cooldown active");
        require(stats.totalDecisions > 0, "No decisions");

        (uint256 score, uint256 windowUsed, uint256 successes, uint256 avgImpact) = calculateQualityScore(agent);
        require(score <= penaltyThreshold, "Score above penalty threshold");

        stats.lastEvalBlock = block.number;
        tokenManager.slashRST(agent, penaltyAmount, "DecisionQuality penalty");

        emit QualityScoreCalculated(agent, score, windowUsed, successes, avgImpact, block.timestamp);
        emit PenaltyTriggered(agent, score, penaltyAmount, block.timestamp);
    }

    // ── Read helpers ─────────────────────────────────────────────────────

    function getOutcome(uint256 decisionId) external view returns (
        bool submitted,
        bool success,
        uint8 impact,
        address submitter,
        uint256 timestamp
    ) {
        Outcome storage o = outcomes[decisionId];
        return (o.submitted, o.success, o.impact, o.submitter, o.timestamp);
    }

    function getRecentDecisionIds(address agent) external view returns (uint256[] memory) {
        uint256[] storage ids = _agentDecisionIds[agent];
        uint256 total = ids.length;
        uint256 count = total < WINDOW_SIZE ? total : WINDOW_SIZE;
        uint256 start = total - count;

        uint256[] memory result = new uint256[](count);
        for (uint256 i = 0; i < count; i++) {
            result[i] = ids[start + i];
        }
        return result;
    }

    function getAgentSummary(address agent) external view returns (
        uint256 totalDecisions,
        uint256 successCount,
        uint256 impactSum,
        uint256 lastEvalBlock,
        uint256 currentScore
    ) {
        AgentStats storage stats = agentStats[agent];
        (currentScore,,,) = calculateQualityScore(agent);
        return (stats.totalDecisions, stats.successCount, stats.impactSum, stats.lastEvalBlock, currentScore);
    }

    // ── Admin ────────────────────────────────────────────────────────────

    function setThresholds(
        uint256 _rewardThreshold,
        uint256 _penaltyThreshold,
        uint256 _rewardAmount,
        uint256 _penaltyAmount
    ) external onlyAdmin {
        rewardThreshold = _rewardThreshold;
        penaltyThreshold = _penaltyThreshold;
        rewardAmount = _rewardAmount;
        penaltyAmount = _penaltyAmount;
        emit ThresholdsUpdated(_rewardThreshold, _penaltyThreshold, _rewardAmount, _penaltyAmount);
    }

    function setEvalCooldown(uint256 _blocks) external onlyAdmin {
        evalCooldown = _blocks;
    }

    function setTokenManager(address _tokenManager) external onlyAdmin {
        tokenManager = ITokenManager(_tokenManager);
    }
}
