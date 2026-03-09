#!/usr/bin/env python3
"""Register all NEXUS nodes on-chain"""
from libnexus import NexusKernel

# Node configurations: each validator registers via its own local RPC
# where its wallet is unlocked
validators = [
    {
        'name': 'nexus-master',
        'rpc': 'http://10.0.20.3:8545',
        'wallet': '0x817B0842B208B76A7665948F8D1A0592F9b1e958',
        'hostname': 'nexus-master',
        'cpu': 4, 'memory': 8, 'storage': 256, 'tops': 0
    },
    {
        'name': 'nexus-ai',
        'rpc': 'http://10.0.20.4:8545',
        'wallet': '0x9602699C3Cb2aCf35CF20c32012A88CD451e55F0',
        'hostname': 'nexus-ai',
        'cpu': 4, 'memory': 8, 'storage': 128, 'tops': 26
    },
    {
        'name': 'nexus-storage',
        'rpc': 'http://10.0.20.11:8545',
        'wallet': '0x06eB84AE46d1b914A35432B6BA7351344aeb9C37',
        'hostname': 'nexus-storage',
        'cpu': 4, 'memory': 8, 'storage': 1800, 'tops': 0
    },
]

# Admin registers via master's RPC using a personal_sendTransaction
# Since admin wallet isn't unlocked on any node, we'll fund it and
# use eth_sendTransaction from master to register admin's specs
# For now, admin is registered by master as a "managed node"

print("NEXUS Node Registration")
print("=" * 60)

for node in validators:
    print(f"\nRegistering {node['name']}...")
    print(f"  Wallet: {node['wallet']}")
    print(f"  RPC:    {node['rpc']}")
    print(f"  Specs:  {node['cpu']}C / {node['memory']}GB / {node['storage']}GB / {node['tops']} TOPS")

    try:
        k = NexusKernel(rpc_url=node['rpc'], wallet=node['wallet'])
        result = k.register_node(
            node['hostname'],
            node['cpu'],
            node['memory'],
            node['storage'],
            node['tops']
        )
        print(f"  Registered in block {result['block']}")
        print(f"  TX: {result['tx_hash']}")
    except Exception as e:
        print(f"  Error: {e}")

# Verify all registrations
print(f"\n{'=' * 60}")
print("Verification")
print("=" * 60)

k = NexusKernel(rpc_url='http://10.0.20.3:8545')
count = k.get_node_count()
print(f"Total nodes registered: {count}")

all_nodes = k.get_all_nodes()
for addr in all_nodes:
    specs = k.get_node(addr)
    tops_str = f" | {specs[4]} TOPS" if specs[4] > 0 else ""
    print(f"  {specs[0]:16s} {specs[1]}C / {specs[2]}GB RAM / {specs[3]}GB disk{tops_str}")
    print(f"    wallet: {addr}")
