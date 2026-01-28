// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title ReasoningLedger
 * @dev Stores AI agent reasoning on-chain for transparency and auditability
 * @notice Part of NEXUS OS - Blockchain Operating System
 *
 * This contract enables:
 * - Recording AI reasoning with hashes and metadata
 * - Parent-child reasoning chains for complex decisions
 * - Agent authorization system
 * - Cross-verification between agents
 */
contract ReasoningLedger {
    // Contract owner
    address public owner;

    // Authorized agents that can record reasoning
    mapping(address => bool) public authorizedAgents;

    // Reasoning entry structure
    struct ReasoningEntry {
        bytes32 reasoningHash;      // Hash of the full reasoning content
        string reasoningType;       // Type: "decision", "analysis", "inference", etc.
        address agent;              // Agent that recorded this reasoning
        uint256 timestamp;          // When reasoning was recorded
        bytes32 parentReasoningId;  // Parent reasoning (for chains)
        bool verified;              // Whether this reasoning has been verified
        address[] verifiers;        // Agents who verified this reasoning
    }

    // Storage
    mapping(bytes32 => ReasoningEntry) public reasonings;
    bytes32[] public reasoningIds;

    // Agent statistics
    mapping(address => uint256) public agentReasoningCount;
    mapping(address => uint256) public agentVerificationCount;

    // Events
    event ReasoningRecorded(
        bytes32 indexed reasoningId,
        address indexed agent,
        bytes32 reasoningHash,
        string reasoningType,
        bytes32 parentReasoningId
    );

    event ReasoningVerified(
        bytes32 indexed reasoningId,
        address indexed verifier
    );

    event AgentAuthorized(address indexed agent);
    event AgentRevoked(address indexed agent);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    // Modifiers
    modifier onlyOwner() {
        require(msg.sender == owner, "ReasoningLedger: caller is not owner");
        _;
    }

    modifier onlyAuthorized() {
        require(authorizedAgents[msg.sender], "ReasoningLedger: caller is not authorized");
        _;
    }

    /**
     * @dev Constructor sets the deployer as owner and first authorized agent
     */
    constructor() {
        owner = msg.sender;
        authorizedAgents[msg.sender] = true;
        emit AgentAuthorized(msg.sender);
    }

    /**
     * @dev Authorize an agent to record reasoning
     * @param agent Address of the agent to authorize
     */
    function authorizeAgent(address agent) external onlyOwner {
        require(agent != address(0), "ReasoningLedger: zero address");
        require(!authorizedAgents[agent], "ReasoningLedger: already authorized");

        authorizedAgents[agent] = true;
        emit AgentAuthorized(agent);
    }

    /**
     * @dev Revoke an agent's authorization
     * @param agent Address of the agent to revoke
     */
    function revokeAgent(address agent) external onlyOwner {
        require(authorizedAgents[agent], "ReasoningLedger: not authorized");
        require(agent != owner, "ReasoningLedger: cannot revoke owner");

        authorizedAgents[agent] = false;
        emit AgentRevoked(agent);
    }

    /**
     * @dev Record a new reasoning entry
     * @param reasoningHash Hash of the full reasoning content (stored off-chain)
     * @param reasoningType Type of reasoning (decision, analysis, inference, etc.)
     * @param parentReasoningId ID of parent reasoning (bytes32(0) if none)
     * @return reasoningId The unique ID of the recorded reasoning
     */
    function recordReasoning(
        bytes32 reasoningHash,
        string memory reasoningType,
        bytes32 parentReasoningId
    ) external onlyAuthorized returns (bytes32 reasoningId) {
        require(reasoningHash != bytes32(0), "ReasoningLedger: empty hash");
        require(bytes(reasoningType).length > 0, "ReasoningLedger: empty type");

        // Validate parent exists if specified
        if (parentReasoningId != bytes32(0)) {
            require(
                reasonings[parentReasoningId].timestamp > 0,
                "ReasoningLedger: parent not found"
            );
        }

        // Generate unique reasoning ID
        reasoningId = keccak256(
            abi.encodePacked(
                reasoningHash,
                msg.sender,
                block.timestamp,
                reasoningIds.length
            )
        );

        // Ensure ID is unique
        require(
            reasonings[reasoningId].timestamp == 0,
            "ReasoningLedger: ID collision"
        );

        // Create reasoning entry
        reasonings[reasoningId] = ReasoningEntry({
            reasoningHash: reasoningHash,
            reasoningType: reasoningType,
            agent: msg.sender,
            timestamp: block.timestamp,
            parentReasoningId: parentReasoningId,
            verified: false,
            verifiers: new address[](0)
        });

        reasoningIds.push(reasoningId);
        agentReasoningCount[msg.sender]++;

        emit ReasoningRecorded(
            reasoningId,
            msg.sender,
            reasoningHash,
            reasoningType,
            parentReasoningId
        );

        return reasoningId;
    }

    /**
     * @dev Verify a reasoning entry (another agent confirms validity)
     * @param reasoningId ID of the reasoning to verify
     */
    function verifyReasoning(bytes32 reasoningId) external onlyAuthorized {
        ReasoningEntry storage entry = reasonings[reasoningId];

        require(entry.timestamp > 0, "ReasoningLedger: reasoning not found");
        require(entry.agent != msg.sender, "ReasoningLedger: cannot self-verify");

        // Check if already verified by this agent
        for (uint256 i = 0; i < entry.verifiers.length; i++) {
            require(
                entry.verifiers[i] != msg.sender,
                "ReasoningLedger: already verified"
            );
        }

        entry.verifiers.push(msg.sender);
        entry.verified = true;
        agentVerificationCount[msg.sender]++;

        emit ReasoningVerified(reasoningId, msg.sender);
    }

    /**
     * @dev Get reasoning entry details
     * @param reasoningId ID of the reasoning
     * @return reasoningHash The hash of the reasoning content
     * @return reasoningType The type of reasoning
     * @return agent The agent who recorded it
     * @return timestamp When it was recorded
     * @return parentReasoningId Parent reasoning ID (if any)
     * @return verified Whether it has been verified
     * @return verifierCount Number of verifiers
     */
    function getReasoning(bytes32 reasoningId) external view returns (
        bytes32 reasoningHash,
        string memory reasoningType,
        address agent,
        uint256 timestamp,
        bytes32 parentReasoningId,
        bool verified,
        uint256 verifierCount
    ) {
        ReasoningEntry storage entry = reasonings[reasoningId];
        require(entry.timestamp > 0, "ReasoningLedger: reasoning not found");

        return (
            entry.reasoningHash,
            entry.reasoningType,
            entry.agent,
            entry.timestamp,
            entry.parentReasoningId,
            entry.verified,
            entry.verifiers.length
        );
    }

    /**
     * @dev Get verifiers for a reasoning entry
     * @param reasoningId ID of the reasoning
     * @return Array of verifier addresses
     */
    function getVerifiers(bytes32 reasoningId) external view returns (address[] memory) {
        require(
            reasonings[reasoningId].timestamp > 0,
            "ReasoningLedger: reasoning not found"
        );
        return reasonings[reasoningId].verifiers;
    }

    /**
     * @dev Get child reasoning entries for a parent
     * @param parentId ID of the parent reasoning
     * @return childIds Array of child reasoning IDs
     */
    function getChildren(bytes32 parentId) external view returns (bytes32[] memory childIds) {
        // Count children first
        uint256 count = 0;
        for (uint256 i = 0; i < reasoningIds.length; i++) {
            if (reasonings[reasoningIds[i]].parentReasoningId == parentId) {
                count++;
            }
        }

        // Populate array
        childIds = new bytes32[](count);
        uint256 index = 0;
        for (uint256 i = 0; i < reasoningIds.length; i++) {
            if (reasonings[reasoningIds[i]].parentReasoningId == parentId) {
                childIds[index] = reasoningIds[i];
                index++;
            }
        }

        return childIds;
    }

    /**
     * @dev Get total reasoning count
     * @return Total number of reasoning entries
     */
    function getTotalReasoningCount() external view returns (uint256) {
        return reasoningIds.length;
    }

    /**
     * @dev Get reasoning IDs with pagination
     * @param offset Starting index
     * @param limit Maximum entries to return
     * @return Array of reasoning IDs
     */
    function getReasoningIds(
        uint256 offset,
        uint256 limit
    ) external view returns (bytes32[] memory) {
        require(offset < reasoningIds.length, "ReasoningLedger: offset out of bounds");

        uint256 remaining = reasoningIds.length - offset;
        uint256 count = remaining < limit ? remaining : limit;

        bytes32[] memory result = new bytes32[](count);
        for (uint256 i = 0; i < count; i++) {
            result[i] = reasoningIds[offset + i];
        }

        return result;
    }

    /**
     * @dev Transfer ownership
     * @param newOwner Address of new owner
     */
    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "ReasoningLedger: zero address");

        address oldOwner = owner;
        owner = newOwner;

        // Ensure new owner is authorized
        if (!authorizedAgents[newOwner]) {
            authorizedAgents[newOwner] = true;
            emit AgentAuthorized(newOwner);
        }

        emit OwnershipTransferred(oldOwner, newOwner);
    }
}
