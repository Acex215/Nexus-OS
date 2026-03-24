// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract PidRegistry {
    mapping(address => uint256) public pids;
    uint256 private nextPid = 1;

    event PidAssigned(address indexed node, uint256 pid);

    function getPid(address node) external returns (uint256) {
        if (pids[node] == 0) {
            pids[node] = nextPid++;
            emit PidAssigned(node, pids[node]);
        }
        return pids[node];
    }

    function viewPid(address node) external view returns (uint256) {
        return pids[node];
    }
}
