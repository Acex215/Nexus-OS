// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract ServiceRegistry {
    struct ServiceInfo {
        address nodeWallet;
        bool active;
        bytes32 configHash;
        uint256 timestamp;
    }

    mapping(bytes32 => ServiceInfo) public services;

    event ServiceRegistered(string name, address node, bytes32 configHash, uint256 timestamp);
    event ServiceDeregistered(string name, address node, uint256 timestamp);

    function register(string calldata name, bytes32 configHash) external {
        bytes32 key = keccak256(abi.encodePacked(name, msg.sender));
        services[key] = ServiceInfo(msg.sender, true, configHash, block.timestamp);
        emit ServiceRegistered(name, msg.sender, configHash, block.timestamp);
    }

    function deregister(string calldata name) external {
        bytes32 key = keccak256(abi.encodePacked(name, msg.sender));
        require(services[key].active, "Service not active");
        services[key].active = false;
        emit ServiceDeregistered(name, msg.sender, block.timestamp);
    }

    function getService(string calldata name, address node) external view returns (bool active, bytes32 configHash, uint256 timestamp) {
        bytes32 key = keccak256(abi.encodePacked(name, node));
        ServiceInfo memory s = services[key];
        return (s.active, s.configHash, s.timestamp);
    }
}
