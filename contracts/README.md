# NEXUS OS Smart Contracts

## Contracts

### ReasoningLedger.sol
Stores AI agent reasoning on-chain for transparency and auditability.
- Records reasoning with hashes and metadata
- Supports parent-child reasoning chains
- Agent authorization system
- Cross-verification between agents

### ResourceManager.sol
Manages computational resource allocation across the cluster.
- Node registration with CPU/memory/storage specs
- Resource allocation requests
- Automatic node selection algorithm
- Resource release and tracking

## Deployment

After blockchain is running:
```bash
cd /opt/nexus/contracts
python3 deploy_contracts.py
```

Requires: `solc` (Solidity compiler)

## Contract Addresses

After deployment, addresses are saved to `/opt/nexus/contracts/deployed/`
