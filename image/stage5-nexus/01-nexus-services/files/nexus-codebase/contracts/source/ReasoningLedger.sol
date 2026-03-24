// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract ReasoningLedger {
    struct ReasoningEntry {
        address agent;
        uint256 timestamp;
        string decision;
        string reasoning;
        bytes32 entryHash;
    }

    ReasoningEntry[] public entries;
    mapping(address => uint256[]) public agentHistory;

    event ReasoningLogged(
        uint256 indexed entryId,
        address indexed agent,
        bytes32 entryHash,
        uint256 timestamp
    );

    function logReasoning(
        string memory decision,
        string memory reasoning
    ) public returns (uint256) {
        bytes32 entryHash = keccak256(abi.encodePacked(
            msg.sender,
            block.timestamp,
            decision,
            reasoning
        ));

        ReasoningEntry memory entry = ReasoningEntry({
            agent: msg.sender,
            timestamp: block.timestamp,
            decision: decision,
            reasoning: reasoning,
            entryHash: entryHash
        });

        entries.push(entry);
        uint256 entryId = entries.length - 1;
        agentHistory[msg.sender].push(entryId);

        emit ReasoningLogged(entryId, msg.sender, entryHash, block.timestamp);
        return entryId;
    }

    function getEntry(uint256 entryId) public view returns (
        address agent,
        uint256 timestamp,
        string memory decision,
        string memory reasoning,
        bytes32 entryHash
    ) {
        require(entryId < entries.length, "Entry does not exist");
        ReasoningEntry memory entry = entries[entryId];
        return (entry.agent, entry.timestamp, entry.decision, entry.reasoning, entry.entryHash);
    }

    function getAgentHistory(address agent) public view returns (uint256[] memory) {
        return agentHistory[agent];
    }

    function getEntryCount() public view returns (uint256) {
        return entries.length;
    }
}
