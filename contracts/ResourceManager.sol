// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title ResourceManager
 * @dev Manages computational resource allocation across the Raspberry Pi cluster
 * @notice Part of NEXUS OS - Blockchain Operating System
 *
 * This contract enables:
 * - Node registration with CPU/memory/storage specifications
 * - Resource allocation requests with automatic node selection
 * - Resource tracking and release
 * - Load balancing across cluster nodes
 */
contract ResourceManager {
    // Contract owner
    address public owner;

    // Node resource specifications
    struct NodeResources {
        uint256 cpuCores;           // Number of CPU cores
        uint256 memoryMB;           // Memory in MB
        uint256 storageMB;          // Storage in MB
        uint256 availableCpu;       // Currently available CPU cores
        uint256 availableMemory;    // Currently available memory
        uint256 availableStorage;   // Currently available storage
        bool isActive;              // Whether node is active
        uint256 registeredAt;       // Registration timestamp
        uint256 lastHeartbeat;      // Last activity timestamp
    }

    // Resource allocation record
    struct ResourceAllocation {
        address requester;          // Who requested the resources
        address node;               // Which node was allocated
        uint256 cpuCores;           // Allocated CPU cores
        uint256 memoryMB;           // Allocated memory
        uint256 storageMB;          // Allocated storage
        uint256 timestamp;          // When allocated
        bool isActive;              // Whether allocation is active
        string purpose;             // Purpose/description of allocation
    }

    // Storage
    mapping(address => NodeResources) public nodes;
    address[] public nodeList;

    mapping(bytes32 => ResourceAllocation) public allocations;
    bytes32[] public allocationIds;

    // Node statistics
    mapping(address => uint256) public nodeAllocationCount;
    mapping(address => bytes32[]) public nodeActiveAllocations;

    // Events
    event NodeRegistered(
        address indexed node,
        uint256 cpuCores,
        uint256 memoryMB,
        uint256 storageMB
    );

    event NodeUpdated(
        address indexed node,
        uint256 cpuCores,
        uint256 memoryMB,
        uint256 storageMB
    );

    event NodeDeactivated(address indexed node);
    event NodeActivated(address indexed node);

    event ResourceAllocated(
        bytes32 indexed allocationId,
        address indexed requester,
        address indexed node,
        uint256 cpuCores,
        uint256 memoryMB,
        uint256 storageMB
    );

    event ResourceReleased(
        bytes32 indexed allocationId,
        address indexed node
    );

    event HeartbeatReceived(address indexed node, uint256 timestamp);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    // Modifiers
    modifier onlyOwner() {
        require(msg.sender == owner, "ResourceManager: caller is not owner");
        _;
    }

    modifier onlyRegisteredNode() {
        require(nodes[msg.sender].registeredAt > 0, "ResourceManager: not registered");
        _;
    }

    /**
     * @dev Constructor sets the deployer as owner
     */
    constructor() {
        owner = msg.sender;
    }

    /**
     * @dev Register a node with its resource specifications
     * @param cpuCores Number of CPU cores
     * @param memoryMB Total memory in MB
     * @param storageMB Total storage in MB
     */
    function registerNode(
        uint256 cpuCores,
        uint256 memoryMB,
        uint256 storageMB
    ) external {
        require(cpuCores > 0, "ResourceManager: zero CPU");
        require(memoryMB > 0, "ResourceManager: zero memory");
        require(storageMB > 0, "ResourceManager: zero storage");

        if (nodes[msg.sender].registeredAt == 0) {
            // New registration
            nodeList.push(msg.sender);
        }

        nodes[msg.sender] = NodeResources({
            cpuCores: cpuCores,
            memoryMB: memoryMB,
            storageMB: storageMB,
            availableCpu: cpuCores,
            availableMemory: memoryMB,
            availableStorage: storageMB,
            isActive: true,
            registeredAt: block.timestamp,
            lastHeartbeat: block.timestamp
        });

        emit NodeRegistered(msg.sender, cpuCores, memoryMB, storageMB);
    }

    /**
     * @dev Update node resource specifications
     * @param cpuCores New CPU core count
     * @param memoryMB New memory amount
     * @param storageMB New storage amount
     */
    function updateNodeResources(
        uint256 cpuCores,
        uint256 memoryMB,
        uint256 storageMB
    ) external onlyRegisteredNode {
        require(cpuCores > 0, "ResourceManager: zero CPU");
        require(memoryMB > 0, "ResourceManager: zero memory");
        require(storageMB > 0, "ResourceManager: zero storage");

        NodeResources storage node = nodes[msg.sender];

        // Calculate used resources
        uint256 usedCpu = node.cpuCores - node.availableCpu;
        uint256 usedMemory = node.memoryMB - node.availableMemory;
        uint256 usedStorage = node.storageMB - node.availableStorage;

        // Ensure new values can accommodate current usage
        require(cpuCores >= usedCpu, "ResourceManager: insufficient CPU");
        require(memoryMB >= usedMemory, "ResourceManager: insufficient memory");
        require(storageMB >= usedStorage, "ResourceManager: insufficient storage");

        // Update totals and available
        node.cpuCores = cpuCores;
        node.memoryMB = memoryMB;
        node.storageMB = storageMB;
        node.availableCpu = cpuCores - usedCpu;
        node.availableMemory = memoryMB - usedMemory;
        node.availableStorage = storageMB - usedStorage;
        node.lastHeartbeat = block.timestamp;

        emit NodeUpdated(msg.sender, cpuCores, memoryMB, storageMB);
    }

    /**
     * @dev Send heartbeat to update last activity timestamp
     */
    function heartbeat() external onlyRegisteredNode {
        nodes[msg.sender].lastHeartbeat = block.timestamp;
        emit HeartbeatReceived(msg.sender, block.timestamp);
    }

    /**
     * @dev Deactivate a node (owner or node itself)
     * @param nodeAddr Address of node to deactivate
     */
    function deactivateNode(address nodeAddr) external {
        require(
            msg.sender == owner || msg.sender == nodeAddr,
            "ResourceManager: not authorized"
        );
        require(nodes[nodeAddr].registeredAt > 0, "ResourceManager: not registered");
        require(nodes[nodeAddr].isActive, "ResourceManager: already inactive");

        nodes[nodeAddr].isActive = false;
        emit NodeDeactivated(nodeAddr);
    }

    /**
     * @dev Reactivate a node
     * @param nodeAddr Address of node to activate
     */
    function activateNode(address nodeAddr) external {
        require(
            msg.sender == owner || msg.sender == nodeAddr,
            "ResourceManager: not authorized"
        );
        require(nodes[nodeAddr].registeredAt > 0, "ResourceManager: not registered");
        require(!nodes[nodeAddr].isActive, "ResourceManager: already active");

        nodes[nodeAddr].isActive = true;
        nodes[nodeAddr].lastHeartbeat = block.timestamp;
        emit NodeActivated(nodeAddr);
    }

    /**
     * @dev Request resource allocation - automatically selects best node
     * @param cpuCores Required CPU cores
     * @param memoryMB Required memory
     * @param storageMB Required storage
     * @param purpose Description of what resources are for
     * @return allocationId Unique identifier for this allocation
     */
    function requestAllocation(
        uint256 cpuCores,
        uint256 memoryMB,
        uint256 storageMB,
        string memory purpose
    ) external returns (bytes32 allocationId) {
        require(cpuCores > 0 || memoryMB > 0 || storageMB > 0, "ResourceManager: no resources requested");

        // Find best available node
        address selectedNode = _selectNode(cpuCores, memoryMB, storageMB);
        require(selectedNode != address(0), "ResourceManager: no suitable node");

        // Generate allocation ID
        allocationId = keccak256(
            abi.encodePacked(
                msg.sender,
                selectedNode,
                block.timestamp,
                allocationIds.length
            )
        );

        // Create allocation
        allocations[allocationId] = ResourceAllocation({
            requester: msg.sender,
            node: selectedNode,
            cpuCores: cpuCores,
            memoryMB: memoryMB,
            storageMB: storageMB,
            timestamp: block.timestamp,
            isActive: true,
            purpose: purpose
        });

        allocationIds.push(allocationId);
        nodeAllocationCount[selectedNode]++;
        nodeActiveAllocations[selectedNode].push(allocationId);

        // Deduct resources from node
        NodeResources storage node = nodes[selectedNode];
        node.availableCpu -= cpuCores;
        node.availableMemory -= memoryMB;
        node.availableStorage -= storageMB;

        emit ResourceAllocated(
            allocationId,
            msg.sender,
            selectedNode,
            cpuCores,
            memoryMB,
            storageMB
        );

        return allocationId;
    }

    /**
     * @dev Request allocation on a specific node
     * @param nodeAddr Address of desired node
     * @param cpuCores Required CPU cores
     * @param memoryMB Required memory
     * @param storageMB Required storage
     * @param purpose Description of what resources are for
     * @return allocationId Unique identifier for this allocation
     */
    function requestAllocationOnNode(
        address nodeAddr,
        uint256 cpuCores,
        uint256 memoryMB,
        uint256 storageMB,
        string memory purpose
    ) external returns (bytes32 allocationId) {
        require(cpuCores > 0 || memoryMB > 0 || storageMB > 0, "ResourceManager: no resources requested");

        NodeResources storage node = nodes[nodeAddr];
        require(node.registeredAt > 0, "ResourceManager: node not registered");
        require(node.isActive, "ResourceManager: node not active");
        require(node.availableCpu >= cpuCores, "ResourceManager: insufficient CPU");
        require(node.availableMemory >= memoryMB, "ResourceManager: insufficient memory");
        require(node.availableStorage >= storageMB, "ResourceManager: insufficient storage");

        // Generate allocation ID
        allocationId = keccak256(
            abi.encodePacked(
                msg.sender,
                nodeAddr,
                block.timestamp,
                allocationIds.length
            )
        );

        // Create allocation
        allocations[allocationId] = ResourceAllocation({
            requester: msg.sender,
            node: nodeAddr,
            cpuCores: cpuCores,
            memoryMB: memoryMB,
            storageMB: storageMB,
            timestamp: block.timestamp,
            isActive: true,
            purpose: purpose
        });

        allocationIds.push(allocationId);
        nodeAllocationCount[nodeAddr]++;
        nodeActiveAllocations[nodeAddr].push(allocationId);

        // Deduct resources
        node.availableCpu -= cpuCores;
        node.availableMemory -= memoryMB;
        node.availableStorage -= storageMB;

        emit ResourceAllocated(
            allocationId,
            msg.sender,
            nodeAddr,
            cpuCores,
            memoryMB,
            storageMB
        );

        return allocationId;
    }

    /**
     * @dev Release allocated resources
     * @param allocationId ID of allocation to release
     */
    function releaseAllocation(bytes32 allocationId) external {
        ResourceAllocation storage allocation = allocations[allocationId];

        require(allocation.timestamp > 0, "ResourceManager: allocation not found");
        require(allocation.isActive, "ResourceManager: already released");
        require(
            msg.sender == allocation.requester ||
            msg.sender == owner ||
            msg.sender == allocation.node,
            "ResourceManager: not authorized"
        );

        // Return resources to node
        NodeResources storage node = nodes[allocation.node];
        node.availableCpu += allocation.cpuCores;
        node.availableMemory += allocation.memoryMB;
        node.availableStorage += allocation.storageMB;

        allocation.isActive = false;

        // Remove from active allocations
        _removeFromActiveAllocations(allocation.node, allocationId);

        emit ResourceReleased(allocationId, allocation.node);
    }

    /**
     * @dev Internal function to select best node for allocation
     * @param cpuCores Required CPU
     * @param memoryMB Required memory
     * @param storageMB Required storage
     * @return Best node address, or zero address if none suitable
     */
    function _selectNode(
        uint256 cpuCores,
        uint256 memoryMB,
        uint256 storageMB
    ) internal view returns (address) {
        address bestNode = address(0);
        uint256 bestScore = 0;

        for (uint256 i = 0; i < nodeList.length; i++) {
            address nodeAddr = nodeList[i];
            NodeResources storage node = nodes[nodeAddr];

            // Skip inactive or insufficient nodes
            if (!node.isActive) continue;
            if (node.availableCpu < cpuCores) continue;
            if (node.availableMemory < memoryMB) continue;
            if (node.availableStorage < storageMB) continue;

            // Score based on available resources (higher is better)
            // This implements a simple "most available" selection
            uint256 score = node.availableCpu * 1000 +
                           node.availableMemory +
                           node.availableStorage / 1000;

            if (score > bestScore) {
                bestScore = score;
                bestNode = nodeAddr;
            }
        }

        return bestNode;
    }

    /**
     * @dev Remove allocation from active allocations array
     */
    function _removeFromActiveAllocations(address nodeAddr, bytes32 allocationId) internal {
        bytes32[] storage active = nodeActiveAllocations[nodeAddr];
        for (uint256 i = 0; i < active.length; i++) {
            if (active[i] == allocationId) {
                active[i] = active[active.length - 1];
                active.pop();
                break;
            }
        }
    }

    /**
     * @dev Get allocation details
     * @param allocationId ID of the allocation
     */
    function getAllocation(bytes32 allocationId) external view returns (
        address requester,
        address node,
        uint256 cpuCores,
        uint256 memoryMB,
        uint256 storageMB,
        uint256 timestamp,
        bool isActive,
        string memory purpose
    ) {
        ResourceAllocation storage a = allocations[allocationId];
        require(a.timestamp > 0, "ResourceManager: allocation not found");

        return (
            a.requester,
            a.node,
            a.cpuCores,
            a.memoryMB,
            a.storageMB,
            a.timestamp,
            a.isActive,
            a.purpose
        );
    }

    /**
     * @dev Get node details
     * @param nodeAddr Address of the node
     */
    function getNode(address nodeAddr) external view returns (
        uint256 cpuCores,
        uint256 memoryMB,
        uint256 storageMB,
        uint256 availableCpu,
        uint256 availableMemory,
        uint256 availableStorage,
        bool isActive,
        uint256 registeredAt,
        uint256 lastHeartbeat
    ) {
        NodeResources storage n = nodes[nodeAddr];
        require(n.registeredAt > 0, "ResourceManager: node not found");

        return (
            n.cpuCores,
            n.memoryMB,
            n.storageMB,
            n.availableCpu,
            n.availableMemory,
            n.availableStorage,
            n.isActive,
            n.registeredAt,
            n.lastHeartbeat
        );
    }

    /**
     * @dev Get total number of registered nodes
     */
    function getNodeCount() external view returns (uint256) {
        return nodeList.length;
    }

    /**
     * @dev Get total number of allocations
     */
    function getAllocationCount() external view returns (uint256) {
        return allocationIds.length;
    }

    /**
     * @dev Get active allocations for a node
     * @param nodeAddr Address of the node
     */
    function getNodeActiveAllocations(address nodeAddr) external view returns (bytes32[] memory) {
        return nodeActiveAllocations[nodeAddr];
    }

    /**
     * @dev Get list of all node addresses
     * @param offset Starting index
     * @param limit Maximum entries to return
     */
    function getNodes(uint256 offset, uint256 limit) external view returns (address[] memory) {
        require(offset < nodeList.length || nodeList.length == 0, "ResourceManager: offset out of bounds");

        if (nodeList.length == 0) {
            return new address[](0);
        }

        uint256 remaining = nodeList.length - offset;
        uint256 count = remaining < limit ? remaining : limit;

        address[] memory result = new address[](count);
        for (uint256 i = 0; i < count; i++) {
            result[i] = nodeList[offset + i];
        }

        return result;
    }

    /**
     * @dev Get cluster utilization statistics
     */
    function getClusterStats() external view returns (
        uint256 totalNodes,
        uint256 activeNodes,
        uint256 totalCpu,
        uint256 availableCpu,
        uint256 totalMemory,
        uint256 availableMemory,
        uint256 totalStorage,
        uint256 availableStorage
    ) {
        totalNodes = nodeList.length;

        for (uint256 i = 0; i < nodeList.length; i++) {
            NodeResources storage node = nodes[nodeList[i]];

            if (node.isActive) {
                activeNodes++;
                totalCpu += node.cpuCores;
                availableCpu += node.availableCpu;
                totalMemory += node.memoryMB;
                availableMemory += node.availableMemory;
                totalStorage += node.storageMB;
                availableStorage += node.availableStorage;
            }
        }

        return (
            totalNodes,
            activeNodes,
            totalCpu,
            availableCpu,
            totalMemory,
            availableMemory,
            totalStorage,
            availableStorage
        );
    }

    /**
     * @dev Transfer ownership
     * @param newOwner Address of new owner
     */
    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "ResourceManager: zero address");

        address oldOwner = owner;
        owner = newOwner;

        emit OwnershipTransferred(oldOwner, newOwner);
    }
}
