"""Phase 3B Integration Tests — LangGraph + LLM + Agent Registry."""
import asyncio
import pytest
import pytest_asyncio

from agent_workflow import NexusAgentWorkflow
from agent_registry import get_agent, AGENT_REGISTRY


# ── Shared fixture: reusable CEO workflow ────────────────────────────

@pytest_asyncio.fixture
async def ceo():
    w = NexusAgentWorkflow("ceo")
    yield w


# ── 1. CEO urgent delegation ────────────────────────────────────────

@pytest.mark.asyncio
async def test_ceo_urgent_delegation(ceo):
    """CEO should detect urgency and delegate to Storage."""
    result = await ceo.process_message(
        "URGENT: nexus-storage is at 95% capacity and growing fast"
    )

    assert result["context"]["urgency_level"] == 5, "Should detect URGENT"
    assert "Storage" in result["context"]["departments"], "Should detect Storage dept"
    assert result["decision"]["priority"] >= 4, f"Priority {result['decision']['priority']} too low"
    assert "Storage" in result["delegates_to"], f"Delegates: {result['delegates_to']}"
    assert result["ect_cost"] >= 20
    assert len(result["reasoning_hash"]) == 64
    assert result["timestamp"].endswith("Z")
    print(f"\n  Priority={result['decision']['priority']} Delegates={result['delegates_to']} ECT={result['ect_cost']}")


# ── 2. CEO multi-department ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_ceo_multi_department(ceo):
    """CEO should delegate to multiple departments when message spans them."""
    result = await ceo.process_message(
        "We need to improve network security and optimize compute resource allocation"
    )

    delegates = result["delegates_to"]
    assert len(delegates) >= 2, f"Expected >=2 departments, got {delegates}"
    # At least two of these should appear
    expected_any = {"Network", "Security", "Compute"}
    found = expected_any & set(delegates)
    assert len(found) >= 2, f"Expected >=2 of {expected_any}, got {found}"
    print(f"\n  Delegates={delegates}")


# ── 3. Director workflow (has analysis step) ─────────────────────────

@pytest.mark.asyncio
async def test_director_workflow():
    """Directors get a 4-node pipeline including analysis."""
    w = NexusAgentWorkflow("compute_director")
    result = await w.process_message(
        "CPU usage is high on nexus-ai. Should we redistribute pods?"
    )

    assert result["analysis"] is not None, "Directors must have analysis"
    assert len(result["analysis"]) > 10, "Analysis too short"
    assert result["decision"]["decision"], "Missing decision"
    assert result["ect_cost"] <= 50
    assert result["reasoning_hash"]
    print(f"\n  Analysis={result['analysis'][:80]}…")
    print(f"  Decision={result['decision']['decision'][:80]}")


# ── 4. Worker workflow (no analysis) ─────────────────────────────────

@pytest.mark.asyncio
async def test_worker_workflow():
    """Workers get a 3-node pipeline, skipping analysis."""
    w = NexusAgentWorkflow("compute_worker_1")
    result = await w.process_message(
        "Schedule this pod on the node with lowest CPU usage"
    )

    assert result["analysis"] is None, "Workers must NOT have analysis"
    assert result["decision"]["decision"], "Missing decision"
    assert result["ect_cost"] <= 30
    assert result["reasoning_hash"]
    print(f"\n  Decision={result['decision']['decision'][:80]}")


# ── 5. Reasoning hash structure ──────────────────────────────────────

@pytest.mark.asyncio
async def test_reasoning_hash_consistency(ceo):
    """Hash should be a valid 64-char hex SHA256."""
    result = await ceo.process_message("Test message for hash check")

    h = result["reasoning_hash"]
    assert len(h) == 64, f"Hash length {len(h)} != 64"
    assert all(c in "0123456789abcdef" for c in h), "Hash not hex"
    assert result["timestamp"].endswith("Z")
    print(f"\n  Hash={h[:16]}…  Timestamp={result['timestamp']}")


# ── 6. JSON parsing robustness ───────────────────────────────────────

@pytest.mark.asyncio
async def test_json_parsing_robustness(ceo):
    """Workflow should never crash, even on odd input."""
    result = await ceo.process_message("@#$% ??? empty gibberish 123")

    assert "decision" in result, "Must always produce decision"
    assert "reasoning_hash" in result, "Must always produce hash"
    assert result["reasoning_hash"], "Hash must not be empty"
    # If LLM returned unparseable JSON the fallback kicks in
    print(f"\n  Decision={result['decision'].get('decision', '?')[:80]}")
    if result.get("error"):
        print(f"  (Fallback used: {result['error'][:60]})")


# ── 7. Context extraction coverage ──────────────────────────────────

@pytest.mark.asyncio
async def test_context_extraction():
    """Keyword extraction should cover all departments, nodes, metrics."""
    w = NexusAgentWorkflow("ceo")

    updates = w._gather_context({
        "message": (
            "The compute cluster on nexus-master and nexus-ai is running "
            "ML training at 92% GPU. Storage on nexus-storage has 1.8TB used. "
            "Quantum simulations are queued. Network latency is 5ms. "
            "Security audit found 0 issues. Blockchain at block 1200. "
            "This is an emergency!"
        ),
        "agent_id": "ceo",
        "agent_config": w.agent_config,
        "context": {},
        "analysis": None,
        "decision": {},
        "reasoning_hash": "",
        "timestamp": "",
        "ect_cost": 0,
        "delegates_to": [],
        "error": None,
    })
    ctx = updates["context"]

    assert set(ctx["departments"]) == {
        "Compute", "Storage", "Network", "Security", "Blockchain", "Ml", "Quantum"
    }, f"Departments: {ctx['departments']}"

    assert "nexus-master" in ctx["nodes"]
    assert "nexus-ai" in ctx["nodes"]
    assert "nexus-storage" in ctx["nodes"]
    assert ctx["urgency_level"] == 5
    assert "92%" in ctx["metrics"]
    print(f"\n  Depts={ctx['departments']}")
    print(f"  Nodes={ctx['nodes']}  Urgency={ctx['urgency_level']}")
    print(f"  Metrics={ctx['metrics']}")


# ── 8. All 30 agents can instantiate workflows ──────────────────────

@pytest.mark.asyncio
async def test_all_agents_instantiate():
    """Every agent in the registry should build a valid workflow graph."""
    errors = []
    for agent_id in AGENT_REGISTRY:
        try:
            w = NexusAgentWorkflow(agent_id)
            cfg = w.agent_config
            role = cfg["role"]
            if role in ("ceo", "coo", "director"):
                assert w.graph is not None, f"{agent_id}: graph is None"
            else:
                assert w.graph is not None, f"{agent_id}: graph is None"
        except Exception as e:
            errors.append(f"{agent_id}: {e}")

    assert not errors, f"Failures:\n" + "\n".join(errors)
    print(f"\n  All {len(AGENT_REGISTRY)} agents instantiated successfully")


# ── CLI runner ───────────────────────────────────────────────────────

if __name__ == "__main__":
    async def main():
        w = NexusAgentWorkflow("ceo")

        print("1. CEO urgent delegation…")
        await test_ceo_urgent_delegation(w)
        print("   PASSED")

        print("2. CEO multi-department…")
        await test_ceo_multi_department(w)
        print("   PASSED")

        print("3. Director workflow…")
        await test_director_workflow()
        print("   PASSED")

        print("4. Worker workflow…")
        await test_worker_workflow()
        print("   PASSED")

        print("5. Reasoning hash…")
        await test_reasoning_hash_consistency(w)
        print("   PASSED")

        print("6. JSON robustness…")
        await test_json_parsing_robustness(w)
        print("   PASSED")

        print("7. Context extraction…")
        await test_context_extraction()
        print("   PASSED")

        print("8. All 30 agents instantiate…")
        await test_all_agents_instantiate()
        print("   PASSED")

        print("\nAll 8 integration tests passed")

    asyncio.run(main())
