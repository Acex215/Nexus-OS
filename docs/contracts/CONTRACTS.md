# NEXUS OS Smart Contract Documentation

## Overview

NEXUS OS uses smart contracts as the coordination layer between the blockchain kernel and higher-level services. These contracts replace traditional system calls with blockchain transactions, providing immutable audit trails and distributed coordination.

## Contract Architecture

```
+--------------------------------------------------+
|              AI Agents / Applications             |
+--------------------------------------------------+
|  ReasoningLedger  |  ResourceManager  |  ...     |
+--------------------------------------------------+
|              Geth Blockchain Kernel               |
+--------------------------------------------------+
```

## ReasoningLedger.sol

### Purpose
Provides on-chain storage for AI agent reasoning, enabling:
- Transparent decision-making audit trails
- Multi-agent reasoning verification
- Parent-child reasoning chains for complex decisions

### Key Functions

```solidity
// Record a new reasoning entry
function recordReasoning(
    bytes32 reasoningHash,
    string memory reasoningType,
    bytes32 parentReasoningId
) external returns (bytes32 reasoningId);

// Verify a reasoning entry
function verifyReasoning(bytes32 reasoningId) external;

// Authorize an agent to record reasoning
function authorizeAgent(address agent) external;
```

### Events

- `ReasoningRecorded(bytes32 indexed reasoningId, address indexed agent, bytes32 reasoningHash)`
- `ReasoningVerified(bytes32 indexed reasoningId, address indexed verifier)`
- `AgentAuthorized(address indexed agent)`
- `AgentRevoked(address indexed agent)`

## ResourceManager.sol

### Purpose
Manages computational resource allocation across the Raspberry Pi cluster:
- Node registration with resource specifications
- Allocation requests with automatic node selection
- Resource tracking and release

### Key Structures

```solidity
struct NodeResources {
    uint256 cpuCores;
    uint256 memoryMB;
    uint256 storageMB;
    uint256 availableCpu;
    uint256 availableMemory;
    uint256 availableStorage;
    bool isActive;
}

struct ResourceAllocation {
    address requester;
    address node;
    uint256 cpuCores;
    uint256 memoryMB;
    uint256 storageMB;
    uint256 timestamp;
    bool isActive;
}
```

### Key Functions

```solidity
// Register a node with its resources
function registerNode(
    uint256 cpuCores,
    uint256 memoryMB,
    uint256 storageMB
) external;

// Request resource allocation
function requestAllocation(
    uint256 cpuCores,
    uint256 memoryMB,
    uint256 storageMB,
    string memory purpose
) external returns (bytes32 allocationId);

// Release allocated resources
function releaseAllocation(bytes32 allocationId) external;
```

### Events

- `NodeRegistered(address indexed node, uint256 cpu, uint256 memory, uint256 storage)`
- `ResourceAllocated(bytes32 indexed allocationId, address indexed requester, address indexed node)`
- `ResourceReleased(bytes32 indexed allocationId)`

## Deployment

### Prerequisites

1. Running NEXUS OS blockchain (`nexus-cli status` shows healthy)
2. Solidity compiler (`solc`) installed
3. Node wallet has ETH for gas

### Deploy Command

```bash
cd /opt/nexus/contracts
python3 deploy_contracts.py
```

### Output

- Contract addresses printed to console
- ABIs saved to `/opt/nexus/contracts/deployed/`
- Deployment log saved to `/opt/nexus/logs/contract_deployment.log`

## Integration Example

```python
from web3 import Web3
import json

# Connect to NEXUS OS blockchain
w3 = Web3(Web3.HTTPProvider('http://localhost:8545'))

# Load contract ABI
with open('/opt/nexus/contracts/deployed/ReasoningLedger.json') as f:
    contract_data = json.load(f)

# Create contract instance
ledger = w3.eth.contract(
    address=contract_data['address'],
    abi=contract_data['abi']
)

# Record reasoning
tx_hash = ledger.functions.recordReasoning(
    reasoning_hash,
    "decision",
    bytes(32)  # No parent
).transact({'from': w3.eth.accounts[0]})

# Wait for transaction
receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
```

## Security Considerations

1. **Owner Privileges**: Both contracts have owner-only functions. Ensure the deploying account is secured.

2. **Agent Authorization**: Only authorized agents can record reasoning. Manage authorizations carefully.

3. **Gas Costs**: Each transaction costs gas. Monitor wallet balance.

4. **Reentrancy**: Contracts use checks-effects-interactions pattern but have not been formally audited.

## Future Contracts

The roadmap includes additional contracts:

- **ProcessCoordinator**: Inter-process communication via blockchain
- **ContractRegistry**: Service discovery for deployed contracts
- **TokenManager**: ECT/RST token economy implementation
