// SPDX-License-Identifier: MIT
// WARNING: Deploying this contract starts a 90-day countdown.
// After finalizeLock(), ALL admin capabilities are permanently destroyed.
// There is no recovery mechanism. This is intentional.
pragma solidity ^0.8.19;

contract ImmutableOS {

    // ── State ────────────────────────────────────────────────────────────

    address public deployer;
    uint256 public deployTimestamp;
    uint256 public constant LOCK_PERIOD = 90 days;
    bool public locked;

    // ── Events ───────────────────────────────────────────────────────────

    event ProtocolLocked(uint256 timestamp, uint256 blockNumber);

    // ── Constructor ──────────────────────────────────────────────────────

    constructor() {
        deployer = msg.sender;
        deployTimestamp = block.timestamp;
    }

    // ── Write functions ──────────────────────────────────────────────────

    function finalizeLock() external {
        require(msg.sender == deployer, "Not deployer");
        require(!locked, "Already locked");
        require(
            block.timestamp >= deployTimestamp + LOCK_PERIOD,
            "Lock period not elapsed"
        );

        deployer = address(0);
        locked = true;

        emit ProtocolLocked(block.timestamp, block.number);
    }

    // ── Read functions ───────────────────────────────────────────────────

    function isLocked() external view returns (bool) {
        return locked;
    }

    function timeUntilLock() external view returns (uint256) {
        uint256 deadline = deployTimestamp + LOCK_PERIOD;
        if (block.timestamp >= deadline) {
            return 0;
        }
        return deadline - block.timestamp;
    }

    function getDeployer() external view returns (address) {
        return deployer;
    }
}
