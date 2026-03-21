# Skill: Contract Deployment

## When to activate
Task contains: "deploy", "contract", "solidity", "smart contract"

## Instructions
- All contract source in /opt/nexus/contracts/source/
- Deployed ABIs and addresses in /opt/nexus/contracts/deployed/
- Compile with solcjs: solcjs --abi --bin source/ContractName.sol
- Deploy via: .venv/bin/python3 scripts/deploy.py
- After deploy, update deployed/*.json with new address + ABI
- Update libnexus/contracts.py if contract list changes
- Risk level: ALWAYS HIGH — requires manual approval
