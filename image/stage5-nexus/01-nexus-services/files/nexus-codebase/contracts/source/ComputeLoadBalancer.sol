// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract ComputeLoadBalancer {
    struct ComputeNode {
        address wallet;
        uint256 cpuTokens;
        uint256 aiTokens;
        uint256 memoryTokens;
        uint256 storageTokens;
        uint256 cpuUsed;
        uint256 aiUsed;
        uint256 memUsed;
        bool active;
    }

    struct WorkloadRequest {
        bytes32 taskId;
        address requester;
        uint256 cpuRequired;
        uint256 aiRequired;
        uint256 memRequired;
        address assignedNode;
        bool fulfilled;
        uint256 timestamp;
    }

    mapping(address => ComputeNode) public nodes;
    address[] public nodeList;
    WorkloadRequest[] public workloads;
    address public admin;

    event NodeRegistered(address indexed wallet, uint256 cpuTokens, uint256 aiTokens, uint256 memoryTokens, uint256 storageTokens, uint256 timestamp);
    event WorkloadRequested(uint256 indexed workloadId, bytes32 taskId, address indexed requester, uint256 cpuRequired, uint256 aiRequired, uint256 memRequired);
    event WorkloadAssigned(uint256 indexed workloadId, address indexed nodeWallet, uint256 timestamp);
    event WorkloadCompleted(uint256 indexed workloadId, address indexed nodeWallet, uint256 timestamp);

    modifier onlyAdmin() {
        require(msg.sender == admin, "Admin only");
        _;
    }

    constructor() {
        admin = msg.sender;
    }

    function registerNode(uint256 cpu, uint256 ai, uint256 mem, uint256 storage_) external {
        if (!nodes[msg.sender].active) {
            nodeList.push(msg.sender);
        }
        nodes[msg.sender] = ComputeNode({
            wallet: msg.sender,
            cpuTokens: cpu,
            aiTokens: ai,
            memoryTokens: mem,
            storageTokens: storage_,
            cpuUsed: 0,
            aiUsed: 0,
            memUsed: 0,
            active: true
        });
        emit NodeRegistered(msg.sender, cpu, ai, mem, storage_, block.timestamp);
    }

    function requestWorkload(bytes32 taskId, uint256 cpu, uint256 ai, uint256 mem) external returns (uint256) {
        uint256 workloadId = workloads.length;
        workloads.push(WorkloadRequest({
            taskId: taskId,
            requester: msg.sender,
            cpuRequired: cpu,
            aiRequired: ai,
            memRequired: mem,
            assignedNode: address(0),
            fulfilled: false,
            timestamp: block.timestamp
        }));
        emit WorkloadRequested(workloadId, taskId, msg.sender, cpu, ai, mem);
        return workloadId;
    }

    function assignWorkload(uint256 workloadId, address nodeWallet) external onlyAdmin {
        require(workloadId < workloads.length, "Invalid workload ID");
        WorkloadRequest storage w = workloads[workloadId];
        require(!w.fulfilled, "Already fulfilled");
        require(w.assignedNode == address(0), "Already assigned");

        ComputeNode storage node = nodes[nodeWallet];
        require(node.active, "Node not active");

        uint256 cpuAvail = node.cpuTokens - node.cpuUsed;
        uint256 aiAvail = node.aiTokens - node.aiUsed;
        uint256 memAvail = node.memoryTokens - node.memUsed;
        require(cpuAvail >= w.cpuRequired, "Insufficient CPU");
        require(aiAvail >= w.aiRequired, "Insufficient AI");
        require(memAvail >= w.memRequired, "Insufficient memory");

        node.cpuUsed += w.cpuRequired;
        node.aiUsed += w.aiRequired;
        node.memUsed += w.memRequired;
        w.assignedNode = nodeWallet;

        emit WorkloadAssigned(workloadId, nodeWallet, block.timestamp);
    }

    function completeWorkload(uint256 workloadId) external {
        require(workloadId < workloads.length, "Invalid workload ID");
        WorkloadRequest storage w = workloads[workloadId];
        require(w.assignedNode != address(0), "Not assigned");
        require(!w.fulfilled, "Already completed");
        require(msg.sender == w.assignedNode || msg.sender == admin, "Not authorized");

        ComputeNode storage node = nodes[w.assignedNode];
        node.cpuUsed -= w.cpuRequired;
        node.aiUsed -= w.aiRequired;
        node.memUsed -= w.memRequired;
        w.fulfilled = true;

        emit WorkloadCompleted(workloadId, w.assignedNode, block.timestamp);
    }

    function getAvailableNodes(uint256 minCpu, uint256 minAi) external view returns (address[] memory) {
        uint256 count = 0;
        for (uint256 i = 0; i < nodeList.length; i++) {
            ComputeNode memory n = nodes[nodeList[i]];
            if (n.active && (n.cpuTokens - n.cpuUsed) >= minCpu && (n.aiTokens - n.aiUsed) >= minAi) {
                count++;
            }
        }

        address[] memory result = new address[](count);
        uint256 idx = 0;
        for (uint256 i = 0; i < nodeList.length; i++) {
            ComputeNode memory n = nodes[nodeList[i]];
            if (n.active && (n.cpuTokens - n.cpuUsed) >= minCpu && (n.aiTokens - n.aiUsed) >= minAi) {
                result[idx] = nodeList[i];
                idx++;
            }
        }
        return result;
    }

    function getNodeUtilization(address wallet) external view returns (
        uint256 cpuCapacity, uint256 cpuUsed,
        uint256 aiCapacity, uint256 aiUsed,
        uint256 memCapacity, uint256 memUsed,
        uint256 storageCapacity
    ) {
        ComputeNode memory n = nodes[wallet];
        require(n.active, "Node not registered");
        return (n.cpuTokens, n.cpuUsed, n.aiTokens, n.aiUsed, n.memoryTokens, n.memUsed, n.storageTokens);
    }

    function getNodeCount() external view returns (uint256) {
        return nodeList.length;
    }

    function getWorkloadCount() external view returns (uint256) {
        return workloads.length;
    }

    function getNodeAddress(uint256 index) external view returns (address) {
        require(index < nodeList.length, "Index out of bounds");
        return nodeList[index];
    }
}
