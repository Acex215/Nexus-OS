// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract TournamentManager {

    // ── Structs ──────────────────────────────────────────────────────────

    struct Tournament {
        uint256 id;
        string name;
        string description;
        uint256 prizePool;
        uint256 startEpoch;
        uint256 endEpoch;
        bytes32 validationDataHash;
        bool finalized;
        address winner;
        uint256 winnerScore;
    }

    struct Submission {
        address contributor;
        bytes32 predictionHash;
        uint256 score;
        uint256 timestamp;
    }

    struct CauseAllocation {
        address contributor;
        string causeName;
        uint256 percentage;
    }

    // ── State ────────────────────────────────────────────────────────────

    mapping(uint256 => Tournament) public tournaments;
    mapping(uint256 => Submission[]) private _submissions;
    mapping(address => CauseAllocation) public causeAllocations;
    address[] private _causeContributors;

    uint256 public tournamentCount;
    uint256 public totalPrizeDistributed;
    address public admin;

    // ── Events ───────────────────────────────────────────────────────────

    event TournamentCreated(
        uint256 indexed tournamentId,
        string name,
        uint256 prizePool,
        uint256 startEpoch,
        uint256 endEpoch,
        bytes32 validationDataHash
    );
    event PredictionSubmitted(
        uint256 indexed tournamentId,
        address indexed contributor,
        bytes32 predictionHash,
        uint256 submissionIndex
    );
    event PredictionScored(
        uint256 indexed tournamentId,
        uint256 submissionIndex,
        address indexed contributor,
        uint256 score
    );
    event TournamentFinalized(
        uint256 indexed tournamentId,
        address indexed winner,
        uint256 winnerScore,
        uint256 prizePool
    );
    event CauseAllocated(
        address indexed contributor,
        string causeName,
        uint256 percentage
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

    // ── Write functions ──────────────────────────────────────────────────

    function createTournament(
        string calldata name,
        string calldata description,
        uint256 prizePool,
        uint256 startEpoch,
        uint256 endEpoch,
        bytes32 validationDataHash
    ) external onlyAdmin returns (uint256) {
        require(endEpoch > startEpoch, "End must be after start");
        require(bytes(name).length > 0, "Empty name");

        uint256 tid = tournamentCount;

        tournaments[tid] = Tournament({
            id: tid,
            name: name,
            description: description,
            prizePool: prizePool,
            startEpoch: startEpoch,
            endEpoch: endEpoch,
            validationDataHash: validationDataHash,
            finalized: false,
            winner: address(0),
            winnerScore: 0
        });

        tournamentCount++;

        emit TournamentCreated(tid, name, prizePool, startEpoch, endEpoch, validationDataHash);
        return tid;
    }

    function submitPrediction(
        uint256 tournamentId,
        bytes32 predictionHash
    ) external returns (uint256) {
        require(tournamentId < tournamentCount, "Invalid tournament");
        Tournament storage t = tournaments[tournamentId];
        require(!t.finalized, "Tournament finalized");
        require(block.timestamp >= t.startEpoch, "Not started");
        require(block.timestamp <= t.endEpoch, "Submissions closed");
        require(predictionHash != bytes32(0), "Empty prediction hash");

        uint256 idx = _submissions[tournamentId].length;

        _submissions[tournamentId].push(Submission({
            contributor: msg.sender,
            predictionHash: predictionHash,
            score: 0,
            timestamp: block.timestamp
        }));

        emit PredictionSubmitted(tournamentId, msg.sender, predictionHash, idx);
        return idx;
    }

    function scorePrediction(
        uint256 tournamentId,
        uint256 submissionIndex,
        uint256 score
    ) external onlyAdmin {
        require(tournamentId < tournamentCount, "Invalid tournament");
        require(submissionIndex < _submissions[tournamentId].length, "Invalid submission");

        Submission storage s = _submissions[tournamentId][submissionIndex];
        s.score = score;

        emit PredictionScored(tournamentId, submissionIndex, s.contributor, score);
    }

    function finalizeTournament(uint256 tournamentId) external onlyAdmin {
        require(tournamentId < tournamentCount, "Invalid tournament");
        Tournament storage t = tournaments[tournamentId];
        require(!t.finalized, "Already finalized");

        Submission[] storage subs = _submissions[tournamentId];
        require(subs.length > 0, "No submissions");

        uint256 bestScore = 0;
        address bestContributor = address(0);

        for (uint256 i = 0; i < subs.length; i++) {
            if (subs[i].score > bestScore) {
                bestScore = subs[i].score;
                bestContributor = subs[i].contributor;
            }
        }

        t.finalized = true;
        t.winner = bestContributor;
        t.winnerScore = bestScore;
        totalPrizeDistributed += t.prizePool;

        emit TournamentFinalized(tournamentId, bestContributor, bestScore, t.prizePool);
    }

    function setCauseAllocation(
        string calldata causeName,
        uint256 percentage
    ) external {
        require(percentage <= 10000, "Max 10000 basis points");
        require(bytes(causeName).length > 0, "Empty cause name");

        if (causeAllocations[msg.sender].contributor == address(0)) {
            _causeContributors.push(msg.sender);
        }

        causeAllocations[msg.sender] = CauseAllocation({
            contributor: msg.sender,
            causeName: causeName,
            percentage: percentage
        });

        emit CauseAllocated(msg.sender, causeName, percentage);
    }

    // ── Read functions ───────────────────────────────────────────────────

    function getCauseAllocations() external view returns (
        address[] memory contributors,
        string[] memory causeNames,
        uint256[] memory percentages
    ) {
        uint256 n = _causeContributors.length;
        contributors = new address[](n);
        causeNames = new string[](n);
        percentages = new uint256[](n);

        for (uint256 i = 0; i < n; i++) {
            address addr = _causeContributors[i];
            CauseAllocation storage ca = causeAllocations[addr];
            contributors[i] = addr;
            causeNames[i] = ca.causeName;
            percentages[i] = ca.percentage;
        }
    }

    function getLeaderboard(uint256 tournamentId) external view returns (
        address[] memory contributors,
        bytes32[] memory predictionHashes,
        uint256[] memory scores,
        uint256[] memory timestamps
    ) {
        require(tournamentId < tournamentCount, "Invalid tournament");
        Submission[] storage subs = _submissions[tournamentId];
        uint256 n = subs.length;

        contributors = new address[](n);
        predictionHashes = new bytes32[](n);
        scores = new uint256[](n);
        timestamps = new uint256[](n);

        // Copy into memory for sorting
        uint256[] memory indices = new uint256[](n);
        for (uint256 i = 0; i < n; i++) {
            indices[i] = i;
        }

        // Insertion sort descending by score
        for (uint256 i = 1; i < n; i++) {
            uint256 key = indices[i];
            uint256 keyScore = subs[key].score;
            uint256 j = i;
            while (j > 0 && subs[indices[j - 1]].score < keyScore) {
                indices[j] = indices[j - 1];
                j--;
            }
            indices[j] = key;
        }

        for (uint256 i = 0; i < n; i++) {
            Submission storage s = subs[indices[i]];
            contributors[i] = s.contributor;
            predictionHashes[i] = s.predictionHash;
            scores[i] = s.score;
            timestamps[i] = s.timestamp;
        }
    }

    function getSubmissionCount(uint256 tournamentId) external view returns (uint256) {
        require(tournamentId < tournamentCount, "Invalid tournament");
        return _submissions[tournamentId].length;
    }

    function getSubmission(uint256 tournamentId, uint256 index) external view returns (
        address contributor,
        bytes32 predictionHash,
        uint256 score,
        uint256 timestamp
    ) {
        require(tournamentId < tournamentCount, "Invalid tournament");
        require(index < _submissions[tournamentId].length, "Invalid index");
        Submission storage s = _submissions[tournamentId][index];
        return (s.contributor, s.predictionHash, s.score, s.timestamp);
    }

    function getTournamentCount() external view returns (uint256) {
        return tournamentCount;
    }
}
