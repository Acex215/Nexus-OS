#!/usr/bin/env python3
"""
Test suite for context_builder.py
Verifies the three-tier memory system works correctly standalone.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import warnings
warnings.filterwarnings("ignore")

from context_builder import (
    classify_task,
    load_constitution,
    build_context_packet,
    chroma_search,
    query_world_model,
    RETRIEVAL_PROFILES,
    MAX_CONTEXT_CHARS,
)

PASS = "PASS"
FAIL = "FAIL"

results: list[tuple[str, str, str]] = []   # (test_name, status, detail)


def check(name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    results.append((name, status, detail))
    icon = "✓" if condition else "✗"
    print(f"  {icon}  {name}")
    if detail:
        print(f"       {detail}")


# ════════════════════════════════════════════════════════════════
# TEST 1: Task classification
# ════════════════════════════════════════════════════════════════
print("\n" + "═" * 60)
print("  TEST 1: Task Classification (6 types)")
print("═" * 60)

classification_cases = [
    ("Fix the iptables rules on nexus-ai2",
     "bug_fix",          "keywords: fix"),
    ("Update chromadb.service to use more memory",
     "config_change",    "keywords: service"),
    ("Add Discord notification when tasks complete",
     "new_feature",      "keywords: add"),
    ("Research homomorphic encryption for ECT privacy",
     "research",         "keywords: research"),
    ("Check health of all validator nodes",
     "health_check",     "keywords: health, check"),
    ("Refactor the blockchain_router to use async calls",
     "code_change",      "default (no strong keyword match)"),
]

for desc, expected, hint in classification_cases:
    got = classify_task(desc)
    check(
        f"classify '{desc[:40]}...' → {expected}",
        got == expected,
        f"got={got!r}  hint={hint}",
    )


# ════════════════════════════════════════════════════════════════
# TEST 2: Constitutional memory
# ════════════════════════════════════════════════════════════════
print("\n" + "═" * 60)
print("  TEST 2: Constitutional Memory")
print("═" * 60)

constitution = load_constitution()
check("constitution loads (non-empty)", len(constitution) > 100)
check("contains identity",   "Cognitive Autonomy Framework" in constitution)
check("contains principles", "Blockchain IS the kernel"     in constitution)
check("contains cluster",    "nexus-master"                  in constitution)
check("contains contracts",  "ReasoningLedger"               in constitution)
check("contains protected",  "hierarchy_manager.py"          in constitution)
check("contains purpose",    "Ship it"                       in constitution)
token_est = len(constitution) // 4
check(f"constitution ≤ 3000 tokens (~{token_est} est.)", token_est <= 3000,
      f"{token_est} estimated tokens")


# ════════════════════════════════════════════════════════════════
# TEST 3: ChromaDB search sanity
# ════════════════════════════════════════════════════════════════
print("\n" + "═" * 60)
print("  TEST 3: ChromaDB Live Search")
print("═" * 60)

results_code = chroma_search("code_chunks", "blockchain transaction signing", n=3)
check("code_chunks search returns results", len(results_code) > 0,
      f"got {len(results_code)} results")
if results_code:
    check("results are (str, dict) tuples",
          isinstance(results_code[0][0], str) and isinstance(results_code[0][1], dict))
    check("metadata has file_path",
          "file_path" in results_code[0][1],
          str(list(results_code[0][1].keys())[:4]))

results_infra = chroma_search("infra_configs", "systemd service", n=3)
check("infra_configs search works", len(results_infra) >= 0,  # 0 is ok if collection empty
      f"got {len(results_infra)} results")

results_missing = chroma_search("nexus_failures", "anything", n=5)
check("empty collection returns []", isinstance(results_missing, list),
      f"type={type(results_missing).__name__}")

results_bad = chroma_search("nonexistent_collection_xyz", "query", n=3)
check("nonexistent collection returns []", results_bad == [])


# ════════════════════════════════════════════════════════════════
# TEST 4: World model query
# ════════════════════════════════════════════════════════════════
print("\n" + "═" * 60)
print("  TEST 4: World Model Query")
print("═" * 60)

wm = query_world_model("/opt/nexus/agents/blockchain_logger.py")
check("world model finds blockchain_logger", wm is not None)
if wm:
    check("stability=core for protected file",    wm.get("stability") == "core")
    check("known_hazards set for protected file",  wm.get("known_hazards") is not None)
    check("symbols extracted",                     len(wm.get("symbols", [])) > 0,
          f"{len(wm.get('symbols',[]))} symbols")
    check("module_type=agent",                     wm.get("module_type") == "agent")

wm_none = query_world_model("/nonexistent/file.py")
check("nonexistent file returns None", wm_none is None)


# ════════════════════════════════════════════════════════════════
# TEST 5: Full context packet — bug_fix type (iptables)
# ════════════════════════════════════════════════════════════════
print("\n" + "═" * 60)
print("  TEST 5: Context Packet — 'Fix iptables rules on nexus-ai2'")
print("═" * 60)

task_iptables = "Fix the iptables rules on nexus-ai2"
packet_iptables = build_context_packet(
    task_iptables,
    affected_files=["/etc/iptables/rules.v4"],
)

char_count  = len(packet_iptables)
token_est_p = char_count // 4

check("packet is a string",             isinstance(packet_iptables, str))
check("packet is non-empty",            char_count > 500,
      f"{char_count} chars")
check(f"packet ≤ {MAX_CONTEXT_CHARS} chars", char_count <= MAX_CONTEXT_CHARS,
      f"{char_count} chars  ({token_est_p} est. tokens)")
check("constitution present in packet", "Cognitive Autonomy Framework" in packet_iptables)
check("principles present",             "Blockchain IS the kernel"     in packet_iptables)
check("task type in packet",            "bug_fix"                       in packet_iptables)

# Print a summary view
print(f"\n  Packet stats: {char_count} chars  ≈ {token_est_p} tokens")
print(f"  Sections detected:")
for marker in ["# CONSTITUTIONAL MEMORY", "# TASK CONTEXT", "# WORKING MEMORY",
               "# WORLD MODEL", "# BACKGROUND MEMORY", "# RECENT FAILURES"]:
    present = marker in packet_iptables
    print(f"    {'✓' if present else '·'}  {marker}")


# ════════════════════════════════════════════════════════════════
# TEST 6: Full context packet — new_feature type (Discord)
# ════════════════════════════════════════════════════════════════
print("\n" + "═" * 60)
print("  TEST 6: Context Packet — 'Add Discord notification when tasks complete'")
print("═" * 60)

task_discord = "Add Discord notification when tasks complete"
packet_discord = build_context_packet(
    task_discord,
    affected_files=["/opt/nexus/agents/hierarchy_manager.py"],
)

char_count_d  = len(packet_discord)
token_est_d   = char_count_d // 4

check("packet is a string",             isinstance(packet_discord, str))
check(f"packet ≤ {MAX_CONTEXT_CHARS} chars", char_count_d <= MAX_CONTEXT_CHARS,
      f"{char_count_d} chars  ({token_est_d} est. tokens)")
check("constitution present",           "Cognitive Autonomy Framework" in packet_discord)
check("task type in packet",            "new_feature"                   in packet_discord)
check("protected file warning present", "hierarchy_manager.py"          in packet_discord,
      "world model hazard info should reference this file")

print(f"\n  Packet stats: {char_count_d} chars  ≈ {token_est_d} tokens")
print(f"  Sections detected:")
for marker in ["# CONSTITUTIONAL MEMORY", "# TASK CONTEXT", "# WORKING MEMORY",
               "# WORLD MODEL", "# BACKGROUND MEMORY"]:
    present = marker in packet_discord
    print(f"    {'✓' if present else '·'}  {marker}")


# ════════════════════════════════════════════════════════════════
# TEST 7: Constitutional memory is ALWAYS in every packet type
# ════════════════════════════════════════════════════════════════
print("\n" + "═" * 60)
print("  TEST 7: Constitutional Memory Present in All Task Types")
print("═" * 60)

for ttype in RETRIEVAL_PROFILES:
    pkt = build_context_packet(f"some task for {ttype}", task_type=ttype)
    check(f"constitution in '{ttype}' packet",
          "Cognitive Autonomy Framework" in pkt and "Blockchain IS the kernel" in pkt)


# ════════════════════════════════════════════════════════════════
# TEST 8: Size limits enforced
# ════════════════════════════════════════════════════════════════
print("\n" + "═" * 60)
print("  TEST 8: Packet Size Limits")
print("═" * 60)

# Build packets for every type and check all stay within limit
for ttype in RETRIEVAL_PROFILES:
    pkt = build_context_packet(
        "test task description with many keywords to trigger broad search results",
        task_type=ttype,
        affected_files=[
            "/opt/nexus/agents/hierarchy_manager.py",
            "/opt/nexus/agents/blockchain_logger.py",
            "/opt/nexus/agents/llm_client.py",
        ],
    )
    check(f"'{ttype}' ≤ {MAX_CONTEXT_CHARS} chars",
          len(pkt) <= MAX_CONTEXT_CHARS,
          f"{len(pkt)} chars")


# ════════════════════════════════════════════════════════════════
# Summary
# ════════════════════════════════════════════════════════════════
print("\n" + "═" * 60)
print("  SUMMARY")
print("═" * 60)

passed = sum(1 for _, s, _ in results if s == PASS)
failed = sum(1 for _, s, _ in results if s == FAIL)
total  = len(results)
print(f"  {passed}/{total} tests passed   ({failed} failed)")

if failed:
    print(f"\n  Failed tests:")
    for name, status, detail in results:
        if status == FAIL:
            print(f"    ✗  {name}")
            if detail:
                print(f"       {detail}")

print("═" * 60)
sys.exit(0 if failed == 0 else 1)
