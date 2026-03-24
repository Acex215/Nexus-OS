// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract TemporalScheduler {

    struct Bin {
        uint16 year;
        uint8 week;         // 1-53
        uint8 dayOfWeek;    // 0=Mon, 6=Sun
        uint8 hour;         // 0-23
        uint256 taskCount;
        uint256 totalECTSpent;
        uint256 createdAt;
        bool exists;
    }

    struct TaskAssignment {
        bytes32 binId;
        bytes32 taskHash;    // SHA256 of task description
        address assignedBy;
        uint256 ectCost;
        uint256 timestamp;
    }

    // Storage
    mapping(bytes32 => Bin) public bins;
    mapping(bytes32 => bytes32[]) public binTasks;  // binId => taskHash[]
    TaskAssignment[] public assignments;
    uint256 public totalAssignments;
    uint256 public totalBinsUsed;

    // Events
    event BinCreated(bytes32 indexed binId, uint16 year, uint8 week, uint8 dayOfWeek, uint8 hour);
    event TaskAssigned(bytes32 indexed binId, bytes32 taskHash, address assignedBy, uint256 ectCost, uint256 timestamp);

    // === Bin Management ===

    function computeBinId(uint16 year, uint8 week, uint8 dayOfWeek, uint8 hour)
        public pure returns (bytes32)
    {
        return keccak256(abi.encodePacked(year, week, dayOfWeek, hour));
    }

    function getOrCreateBin(uint16 year, uint8 week, uint8 dayOfWeek, uint8 hour)
        public returns (bytes32 binId)
    {
        require(week >= 1 && week <= 53, "Invalid week");
        require(dayOfWeek <= 6, "Invalid day");
        require(hour <= 23, "Invalid hour");

        binId = computeBinId(year, week, dayOfWeek, hour);

        if (!bins[binId].exists) {
            bins[binId] = Bin({
                year: year,
                week: week,
                dayOfWeek: dayOfWeek,
                hour: hour,
                taskCount: 0,
                totalECTSpent: 0,
                createdAt: block.timestamp,
                exists: true
            });
            totalBinsUsed++;
            emit BinCreated(binId, year, week, dayOfWeek, hour);
        }

        return binId;
    }

    // === Task Assignment ===

    function assignTask(
        uint16 year, uint8 week, uint8 dayOfWeek, uint8 hour,
        bytes32 taskHash, uint256 ectCost
    ) public returns (bytes32 binId) {
        binId = getOrCreateBin(year, week, dayOfWeek, hour);

        bins[binId].taskCount++;
        bins[binId].totalECTSpent += ectCost;

        binTasks[binId].push(taskHash);

        assignments.push(TaskAssignment({
            binId: binId,
            taskHash: taskHash,
            assignedBy: msg.sender,
            ectCost: ectCost,
            timestamp: block.timestamp
        }));
        totalAssignments++;

        emit TaskAssigned(binId, taskHash, msg.sender, ectCost, block.timestamp);
        return binId;
    }

    // === Read Functions ===

    function getBin(bytes32 binId) public view returns (
        uint16 year, uint8 week, uint8 dayOfWeek, uint8 hour,
        uint256 taskCount, uint256 totalECTSpent, uint256 createdAt, bool exists
    ) {
        Bin memory b = bins[binId];
        return (b.year, b.week, b.dayOfWeek, b.hour,
                b.taskCount, b.totalECTSpent, b.createdAt, b.exists);
    }

    function getBinTaskCount(bytes32 binId) public view returns (uint256) {
        return bins[binId].taskCount;
    }

    function getBinTasks(bytes32 binId) public view returns (bytes32[] memory) {
        return binTasks[binId];
    }

    function getAssignment(uint256 index) public view returns (
        bytes32 binId, bytes32 taskHash, address assignedBy,
        uint256 ectCost, uint256 timestamp
    ) {
        require(index < totalAssignments, "Index out of bounds");
        TaskAssignment memory a = assignments[index];
        return (a.binId, a.taskHash, a.assignedBy, a.ectCost, a.timestamp);
    }

    // === Batch Read for Heat Map ===

    function getBinUtilization(bytes32[] calldata binIds)
        public view returns (uint256[] memory taskCounts, uint256[] memory ectSpent)
    {
        taskCounts = new uint256[](binIds.length);
        ectSpent = new uint256[](binIds.length);
        for (uint256 i = 0; i < binIds.length; i++) {
            taskCounts[i] = bins[binIds[i]].taskCount;
            ectSpent[i] = bins[binIds[i]].totalECTSpent;
        }
    }
}
