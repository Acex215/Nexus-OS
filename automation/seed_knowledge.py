#!/usr/bin/env python3
"""Seed ChromaDB with existing NEXUS OS project knowledge."""
import os
import sys
sys.path.insert(0, '/opt/nexus/automation')
from chroma_memory import seed_from_file, remember

files_to_seed = [
    ('/opt/nexus/agents/agent_registry.py', 'agent_definitions'),
    ('/opt/nexus/agents/agent_workflow.py', 'agent_workflow'),
    ('/opt/nexus/agents/llm_client.py', 'llm_client'),
    ('/opt/nexus/automation/project_state.json', 'project_state'),
]

for path, tag in files_to_seed:
    if os.path.exists(path):
        print(f"Seeding: {path}")
        seed_from_file(path, tag)
    else:
        print(f"Skipping (not found): {path}")

decisions = [
    "Blockchain IS the kernel. Geth starts before all other services.",
    "Every device equals an Ethereum wallet. Hardware identity is cryptographic.",
    "Smart contracts replace syscalls. Operations execute as blockchain transactions.",
    "Block time is the kernel scheduler tick rate. Period=0 gives ~28ms confirmation.",
    "Air-gapped security with VLAN segmentation. Cluster has no internet.",
    "Temporal binning with 8760 hourly bins is the universal scheduling abstraction.",
    "Token economy ECT/RST governs resource allocation, not fixed priority.",
    "Privacy by design: daily encryption rotation, homomorphic encryption.",
    "Zero cloud dependency. Your Data. Your Hardware. Your Rules.",
    "Blockchain stores metadata. IPFS stores data. Never push bulk data through chain.",
    "LangGraph for agent workflows. SmolAgents only for narrow execution.",
    "Patent filed. All innovations must be consistent with patent claims.",
    "Never modify hierarchy_manager.py autonomously. It is proven working.",
]

for i, decision in enumerate(decisions):
    remember(decision, {'type': 'architecture', 'index': str(i), 'source': 'constitution'}, 'decisions')
    print(f"Stored decision {i}: {decision[:60]}...")

print("\nKnowledge seeding complete.")
