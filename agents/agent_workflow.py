"""NEXUS OS LangGraph Multi-Step Reasoning Workflow.

Leadership (CEO/COO/Directors): gather_context → analyze → decide → finalize
Workers:                        gather_context → decide → finalize

Every decision produces a SHA256 reasoning hash for blockchain logging.
"""
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from agent_registry import get_agent
from llm_router_v2 import LLMRouter

logger = logging.getLogger(__name__)


# ── State schema ─────────────────────────────────────────────────────

class WorkflowState(TypedDict):
    # Inputs
    message: str
    agent_id: str
    agent_config: Dict[str, Any]

    # Intermediate
    context: Dict[str, Any]
    analysis: Optional[str]

    # Decision
    decision: Dict[str, Any]

    # Finalized
    reasoning_hash: str
    timestamp: str
    ect_cost: int
    delegates_to: List[str]
    error: Optional[str]


# ── Keyword sets ─────────────────────────────────────────────────────

_DEPARTMENTS = [
    "compute", "storage", "network", "security",
    "blockchain", "ml", "quantum",
]

_NODE_NAMES = ["master", "ai", "storage", "admin"]

_URGENCY_KEYWORDS = [
    "urgent", "critical", "asap", "emergency",
    "failing", "down", "outage", "immediately",
]

_METRIC_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|[KMGT]B|TOPS|°[CF]|GB|TB|MB)(?=\s|$|[,.\)])",
    re.IGNORECASE,
)


# ── Workflow class ───────────────────────────────────────────────────

class NexusAgentWorkflow:
    """LangGraph reasoning pipeline for a single NEXUS agent."""

    LEADERSHIP_ROLES = {"ceo", "coo", "director"}

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.agent_config = get_agent(agent_id)
        self.router = LLMRouter()
        self.log = logging.getLogger(f"workflow.{agent_id}")

        if self.agent_config["role"] in self.LEADERSHIP_ROLES:
            self.graph = self._build_leadership_graph()
        else:
            self.graph = self._build_worker_graph()

    # ── Node: gather_context ─────────────────────────────────────────

    def _gather_context(self, state: WorkflowState) -> dict:
        """Extract structured context via keyword matching (no LLM)."""
        msg = state["message"].lower()

        departments = [
            d.capitalize() for d in _DEPARTMENTS if d in msg
        ]

        nodes = []
        for n in _NODE_NAMES:
            if n in msg or f"nexus-{n}" in msg:
                nodes.append(f"nexus-{n}")

        found_urgency = [kw for kw in _URGENCY_KEYWORDS if kw in msg]
        urgency_level = 5 if found_urgency else 3

        metrics = _METRIC_PATTERN.findall(msg)

        context = {
            "departments": departments,
            "nodes": nodes,
            "urgency_level": urgency_level,
            "urgency_keywords": found_urgency,
            "metrics": metrics,
            "message_length": len(state["message"]),
        }

        self.log.debug("Context gathered: %s", context)
        return {"context": context}

    # ── Node: analyze (leadership only) ──────────────────────────────

    async def _analyze(self, state: WorkflowState) -> dict:
        """Brief LLM situation analysis for leadership agents."""
        ctx = state["context"]
        prompt = (
            f"Provide a brief 2-3 sentence analysis of this situation.\n\n"
            f"Message: {state['message']}\n"
            f"Departments involved: {ctx['departments'] or 'none detected'}\n"
            f"Nodes mentioned: {ctx['nodes'] or 'none detected'}\n"
            f"Urgency: {ctx['urgency_level']}/5\n"
            f"Metrics found: {ctx['metrics'] or 'none'}\n\n"
            f"Analysis:"
        )

        try:
            result = await self.router.generate(
                self.agent_id,
                [{"role": "user", "content": prompt}],
                task_type="planning",
                max_tokens=200,
                temperature=0.7,
            )
            if result.get("error") or not result.get("content"):
                raise RuntimeError(result.get("error", "Empty response"))
            return {"analysis": result["content"].strip()}
        except Exception as exc:
            self.log.error("Analysis failed: %s", exc)
            return {"analysis": "Analysis unavailable - proceeding with context only."}

    # ── Node: decide ─────────────────────────────────────────────────

    async def _decide(self, state: WorkflowState) -> dict:
        """LLM decision using the agent's full system prompt."""
        ctx_str = json.dumps(state["context"], indent=2)
        analysis_block = ""
        if state.get("analysis"):
            analysis_block = f"\nSituation Analysis: {state['analysis']}\n"

        user_prompt = (
            f"Message: {state['message']}\n\n"
            f"Context:\n{ctx_str}\n"
            f"{analysis_block}\n"
            f"Respond with ONLY valid JSON (no markdown, no explanation):\n"
            f'{{\n'
            f'  "decision": "what to do",\n'
            f'  "reasoning": "why",\n'
            f'  "delegates_to": ["Department"] or [],\n'
            f'  "priority": 1-5,\n'
            f'  "ect_cost": 10-50\n'
            f'}}'
        )

        messages = [
            {"role": "system", "content": self.agent_config["system_prompt"]},
            {"role": "user", "content": user_prompt},
        ]

        try:
            result = await self.router.generate(
                self.agent_id,
                messages,
                max_tokens=512,
                temperature=0.7,
            )
            if result.get("error") or not result.get("content"):
                raise RuntimeError(result.get("error", "Empty response"))

            decision = self._parse_json_response(result["content"])
            self._validate_decision(decision)
            return {"decision": decision}

        except Exception as exc:
            self.log.error("Decision failed: %s", exc)
            return {
                "decision": {
                    "decision": "Unable to parse decision - manual review needed",
                    "reasoning": f"LLM response parsing error: {str(exc)[:100]}",
                    "delegates_to": [],
                    "priority": 3,
                    "ect_cost": 10,
                },
                "error": str(exc),
            }

    # ── Node: finalize ───────────────────────────────────────────────

    def _finalize(self, state: WorkflowState) -> dict:
        """Compute reasoning hash, set timestamp, format output."""
        hash_payload = json.dumps(
            {
                "message": state["message"],
                "context": state["context"],
                "decision": state["decision"],
            },
            sort_keys=True,
        )
        reasoning_hash = hashlib.sha256(hash_payload.encode()).hexdigest()

        decision = state["decision"]
        delegates = decision.get("delegates_to", [])
        if isinstance(delegates, str):
            delegates = [delegates] if delegates else []

        result = {
            "reasoning_hash": reasoning_hash,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ect_cost": int(decision.get("ect_cost", 10)),
            "delegates_to": delegates,
        }

        self.log.info(
            "Finalized: hash=%s… ect=%d delegates=%s",
            reasoning_hash[:16], result["ect_cost"], delegates,
        )
        return result

    # ── Graph builders ───────────────────────────────────────────────

    def _build_leadership_graph(self):
        """4-node graph: gather_context → analyze → decide → finalize."""
        g = StateGraph(WorkflowState)
        g.add_node("gather_context", self._gather_context)
        g.add_node("analyze", self._analyze)
        g.add_node("decide", self._decide)
        g.add_node("finalize", self._finalize)

        g.set_entry_point("gather_context")
        g.add_edge("gather_context", "analyze")
        g.add_edge("analyze", "decide")
        g.add_edge("decide", "finalize")
        g.add_edge("finalize", END)
        return g.compile()

    def _build_worker_graph(self):
        """3-node graph: gather_context → decide → finalize."""
        g = StateGraph(WorkflowState)
        g.add_node("gather_context", self._gather_context)
        g.add_node("decide", self._decide)
        g.add_node("finalize", self._finalize)

        g.set_entry_point("gather_context")
        g.add_edge("gather_context", "decide")
        g.add_edge("decide", "finalize")
        g.add_edge("finalize", END)
        return g.compile()

    # ── Public API ───────────────────────────────────────────────────

    async def process_message(self, message: str) -> WorkflowState:
        """Run the full reasoning workflow on a message."""
        initial_state: WorkflowState = {
            "message": message,
            "agent_id": self.agent_id,
            "agent_config": self.agent_config,
            "context": {},
            "analysis": None,
            "decision": {},
            "reasoning_hash": "",
            "timestamp": "",
            "ect_cost": 0,
            "delegates_to": [],
            "error": None,
        }
        return await self.graph.ainvoke(initial_state)

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_json_response(text: str) -> dict:
        """Extract JSON from LLM response, handling markdown fences."""
        cleaned = text.strip()

        # Strip markdown code fences
        if "```json" in cleaned:
            cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in cleaned:
            cleaned = cleaned.split("```", 1)[1].split("```", 1)[0]

        cleaned = cleaned.strip()

        # Try direct parse
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Try to find the first { ... } block
        match = re.search(r"\{[^{}]*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        # Try nested braces (for delegates_to arrays)
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Could not parse JSON from response: {cleaned[:200]}")

    @staticmethod
    def _validate_decision(decision: dict):
        """Ensure all required fields are present with correct types."""
        required = {
            "decision": str,
            "reasoning": str,
            "delegates_to": list,
            "priority": (int, float),
            "ect_cost": (int, float),
        }
        for field, expected_type in required.items():
            if field not in decision:
                raise ValueError(f"Missing field: {field}")
            if not isinstance(decision[field], expected_type):
                # Try to coerce numbers
                if field in ("priority", "ect_cost"):
                    try:
                        decision[field] = int(decision[field])
                    except (TypeError, ValueError):
                        raise ValueError(
                            f"Field '{field}' must be {expected_type}, "
                            f"got {type(decision[field])}"
                        )

        # Clamp ranges
        decision["priority"] = max(1, min(5, int(decision["priority"])))
        decision["ect_cost"] = max(1, min(100, int(decision["ect_cost"])))
