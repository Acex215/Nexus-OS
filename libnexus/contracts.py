"""Contract address and ABI registry"""
import json
import os

CONTRACTS_DIR = '/opt/nexus/contracts/deployed'

def load_contract_info(name):
    """Load deployed contract address and ABI"""
    path = os.path.join(CONTRACTS_DIR, f'{name}.json')
    if not os.path.exists(path):
        raise FileNotFoundError(f"Contract {name} not found at {path}")

    with open(path, 'r') as f:
        return json.load(f)

# Lazy-load contract info
_cache = {}

def get_contract(name):
    """Get contract info with caching"""
    if name not in _cache:
        _cache[name] = load_contract_info(name)
    return _cache[name]
