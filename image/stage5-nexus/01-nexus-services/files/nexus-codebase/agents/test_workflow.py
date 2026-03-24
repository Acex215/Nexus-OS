"""Test NEXUS OS LangGraph agent workflows."""
import asyncio
import json
import sys

from agent_workflow import NexusAgentWorkflow


async def test_ceo_workflow():
    print("=" * 60)
    print("TEST 1: CEO Leadership Workflow (4 nodes)")
    print("=" * 60)

    workflow = NexusAgentWorkflow("ceo")
    result = await workflow.process_message(
        "Storage is at 85% capacity on nexus-storage. "
        "We need to implement cleanup policies urgently."
    )

    print(f"\n  Context:")
    print(f"    Departments: {result['context']['departments']}")
    print(f"    Nodes:       {result['context']['nodes']}")
    print(f"    Urgency:     {result['context']['urgency_level']}/5")
    print(f"    Metrics:     {result['context']['metrics']}")

    if result.get("analysis"):
        print(f"\n  Analysis: {result['analysis'][:150]}...")

    d = result["decision"]
    print(f"\n  Decision:    {d['decision']}")
    print(f"  Reasoning:   {d['reasoning']}")
    print(f"  Delegates:   {result['delegates_to']}")
    print(f"  Priority:    {d['priority']}")
    print(f"  ECT cost:    {result['ect_cost']}")
    print(f"  Hash:        {result['reasoning_hash'][:16]}...")
    print(f"  Timestamp:   {result['timestamp']}")

    if result.get("error"):
        print(f"  Error:       {result['error']}")

    # Assertions
    assert result["context"]["urgency_level"] == 5, "Should detect urgency"
    assert "Storage" in result["context"]["departments"], "Should detect Storage dept"
    assert result["reasoning_hash"], "Should have hash"
    assert result["timestamp"], "Should have timestamp"
    assert len(result["reasoning_hash"]) == 64, "SHA256 should be 64 hex chars"

    print("\n  CEO workflow test PASSED")


async def test_worker_workflow():
    print("\n" + "=" * 60)
    print("TEST 2: Worker Workflow (3 nodes, no analyze)")
    print("=" * 60)

    workflow = NexusAgentWorkflow("compute_worker_1")
    result = await workflow.process_message(
        "Schedule the new ML training pod on a node with available GPU resources"
    )

    d = result["decision"]
    print(f"\n  Context:")
    print(f"    Departments: {result['context']['departments']}")
    print(f"    Nodes:       {result['context']['nodes']}")

    print(f"\n  Decision:    {d['decision'][:100]}")
    print(f"  Reasoning:   {d['reasoning'][:100]}")
    print(f"  ECT cost:    {result['ect_cost']}")
    print(f"  Hash:        {result['reasoning_hash'][:16]}...")

    # Workers should NOT have an analysis step
    assert result.get("analysis") is None, "Workers should not have analysis"
    assert result["reasoning_hash"], "Should have hash"

    print("\n  Worker workflow test PASSED")


async def test_director_workflow():
    print("\n" + "=" * 60)
    print("TEST 3: Director Leadership Workflow")
    print("=" * 60)

    workflow = NexusAgentWorkflow("security_director")
    result = await workflow.process_message(
        "Anomaly detected: 15 failed SSH attempts on nexus-master in the last 5 minutes. "
        "Source IP is not in our known range. This is critical."
    )

    d = result["decision"]
    print(f"\n  Context:")
    print(f"    Departments: {result['context']['departments']}")
    print(f"    Urgency:     {result['context']['urgency_level']}/5")

    if result.get("analysis"):
        print(f"\n  Analysis: {result['analysis'][:150]}...")

    print(f"\n  Decision:    {d['decision'][:100]}")
    print(f"  Priority:    {d['priority']}")
    print(f"  Delegates:   {result['delegates_to']}")
    print(f"  Hash:        {result['reasoning_hash'][:16]}...")

    assert result["context"]["urgency_level"] == 5, "Should detect critical"
    assert result.get("analysis") is not None, "Directors should have analysis"

    print("\n  Director workflow test PASSED")


async def test_context_extraction():
    print("\n" + "=" * 60)
    print("TEST 4: Context Extraction (no LLM)")
    print("=" * 60)

    workflow = NexusAgentWorkflow("ceo")

    # Manually test gather_context
    state = {
        "message": "The compute and network departments report nexus-ai is at 95% CPU. "
                   "Blockchain sync is failing on nexus-master. This is an emergency!",
        "agent_id": "ceo",
        "agent_config": workflow.agent_config,
        "context": {},
        "analysis": None,
        "decision": {},
        "reasoning_hash": "",
        "timestamp": "",
        "ect_cost": 0,
        "delegates_to": [],
        "error": None,
    }

    updates = workflow._gather_context(state)
    ctx = updates["context"]

    print(f"  Departments: {ctx['departments']}")
    print(f"  Nodes:       {ctx['nodes']}")
    print(f"  Urgency:     {ctx['urgency_level']}/5")
    print(f"  Keywords:    {ctx['urgency_keywords']}")
    print(f"  Metrics:     {ctx['metrics']}")

    assert "Compute" in ctx["departments"], "Should detect Compute"
    assert "Network" in ctx["departments"], "Should detect Network"
    assert "Blockchain" in ctx["departments"], "Should detect Blockchain"
    assert "nexus-ai" in ctx["nodes"], "Should detect nexus-ai"
    assert "nexus-master" in ctx["nodes"], "Should detect nexus-master"
    assert ctx["urgency_level"] == 5, "Should detect emergency"
    assert "95%" in ctx["metrics"], "Should extract 95%"

    print("\n  Context extraction test PASSED")


async def main():
    # Test 4 runs without LLM - run first
    await test_context_extraction()

    # Tests with LLM calls
    await test_ceo_workflow()
    await test_worker_workflow()
    await test_director_workflow()

    print("\n" + "=" * 60)
    print("ALL WORKFLOW TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
