// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract ResourceManager {
    struct Node {
        address wallet;
        string hostname;
        uint256 cpuCores;
        uint256 memoryGB;
        uint256 storageGB;
        uint256 aiTops;
        bool active;
        uint256 registeredAt;
    }

    mapping(address => Node) public nodes;
    address[] public nodeAddresses;

    event NodeRegistered(address indexed wallet, string hostname, uint256 timestamp);
    event ResourcesAllocated(address indexed node, address indexed requester, uint256 amount);

    function registerNode(
        string memory hostname,
        uint256 cpuCores,
        uint256 memoryGB,
        uint256 storageGB,
        uint256 aiTops
    ) public {
        require(nodes[msg.sender].wallet == address(0), "Node already registered");

        nodes[msg.sender] = Node({
            wallet: msg.sender,
            hostname: hostname,
            cpuCores: cpuCores,
            memoryGB: memoryGB,
            storageGB: storageGB,
            aiTops: aiTops,
            active: true,
            registeredAt: block.timestamp
        });

        nodeAddresses.push(msg.sender);
        emit NodeRegistered(msg.sender, hostname, block.timestamp);
    }

    function getNode(address wallet) public view returns (
        string memory hostname,
        uint256 cpuCores,
        uint256 memoryGB,
        uint256 storageGB,
        uint256 aiTops,
        bool active
    ) {
        Node memory node = nodes[wallet];
        require(node.wallet != address(0), "Node not found");
        return (node.hostname, node.cpuCores, node.memoryGB, node.storageGB, node.aiTops, node.active);
    }

    function getNodeCount() public view returns (uint256) {
        return nodeAddresses.length;
    }

    function getAllNodes() public view returns (address[] memory) {
        return nodeAddresses;
    }
}
