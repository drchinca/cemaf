"""Integration test: auction-based agent selection through the real executor (SPEC-09).

Two real agents both advertise WRITE with different loads; an `auction` node runs
through a real ContextNodeExecutor + DefaultAgentSelector + AgentRegistry +
BudgetGuard. Proves the budget/load-aware winner actually executes and is recorded
in provenance metadata — and that a static `Node.agent` node is unaffected by a
wired selector. No mocks.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from cemaf.agents.base import AgentContext, AgentResult, AgentState
from cemaf.agents.protocols import Agent
from cemaf.agents.registry import AgentRegistry
from cemaf.agents.selection import Capability, DefaultAgentSelector
from cemaf.context.context import Context
from cemaf.core.types import AgentID, NodeID
from cemaf.observability.budget_guard import BudgetGuard
from cemaf.orchestration.context_node_executor import ContextNodeExecutor
from cemaf.orchestration.dag import Node, NodeType


class _WriteGoal(BaseModel):
    objective: str = "write something"


class _WriteResult(BaseModel):
    article: str


class _WriteAgent(Agent[_WriteGoal, _WriteResult]):
    """A WRITE-capable agent that records which agent ran via its output."""

    def __init__(self, agent_id: str, load: float) -> None:
        self._id = AgentID(agent_id)
        self._load = load

    @property
    def id(self) -> AgentID:
        return self._id

    @property
    def description(self) -> str:
        return f"writer {self._id}"

    @property
    def skills(self) -> tuple[()]:
        return ()

    @property
    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.WRITE})

    @property
    def current_load(self) -> float:
        return self._load

    async def run(self, goal: _WriteGoal, context: AgentContext) -> AgentResult[_WriteResult]:
        return AgentResult.ok(
            output=_WriteResult(article=f"written-by:{self._id}"),
            state=AgentState(),
        )


def _registry_with_two_writers() -> AgentRegistry:
    registry = AgentRegistry()
    registry.register_agent(
        agent_instance=_WriteAgent("WriterBusy", load=0.9),
        goal_type=_WriteGoal,
        capabilities=frozenset({Capability.WRITE}),
    )
    registry.register_agent(
        agent_instance=_WriteAgent("WriterIdle", load=0.1),
        goal_type=_WriteGoal,
        capabilities=frozenset({Capability.WRITE}),
    )
    return registry


@pytest.mark.asyncio
async def test_auction_selects_low_load_winner() -> None:
    registry = _registry_with_two_writers()
    executor = ContextNodeExecutor(
        agent_registry=registry,
        agent_selector=DefaultAgentSelector(),
        budget_guard=BudgetGuard(max_cost_usd=10.0, max_total_tokens=100_000),
    )
    node = Node.auction(id="w", name="write", capability=Capability.WRITE.value)

    result = await executor.execute_node(node, Context())

    assert result.success
    assert result.output is not None and "WriterIdle" in result.output
    assert result.metadata["selection"]["agent_id"] == "WriterIdle"
    assert result.metadata["selection"]["capability_match"] == 1.0


@pytest.mark.asyncio
async def test_registry_get_candidates_returns_both() -> None:
    registry = _registry_with_two_writers()
    candidates = registry.get_candidates(capability=Capability.WRITE)
    assert {str(a.id) for a in candidates} == {"WriterBusy", "WriterIdle"}


@pytest.mark.asyncio
async def test_no_candidates_with_ref_id_falls_through_to_static() -> None:
    """Auction with an unmatched capability but a set ref_id → static resolution runs."""
    registry = _registry_with_two_writers()
    executor = ContextNodeExecutor(
        agent_registry=registry,
        agent_selector=DefaultAgentSelector(),
    )
    # capability RESEARCH has no candidates; ref_id names a real WRITE agent.
    node = Node(
        id=NodeID("n"),
        type=NodeType.AGENT,
        name="fallthrough",
        ref_id="WriterIdle",
        config={"capability": Capability.RESEARCH.value},
    )
    result = await executor.execute_node(node, Context())

    assert result.success
    assert "WriterIdle" in (result.output or "")
    assert "selection" not in result.metadata  # no auction winner recorded


@pytest.mark.asyncio
async def test_no_candidates_empty_ref_id_errors_cleanly() -> None:
    registry = _registry_with_two_writers()
    executor = ContextNodeExecutor(
        agent_registry=registry,
        agent_selector=DefaultAgentSelector(),
    )
    node = Node.auction(id="n", name="x", capability=Capability.RESEARCH.value)  # no RESEARCH agents
    result = await executor.execute_node(node, Context())

    assert not result.success
    assert "no ref_id" in (result.error or "")


@pytest.mark.asyncio
async def test_static_node_unaffected_by_wired_selector() -> None:
    """A Node.agent with a wired selector still resolves statically — no auction."""
    registry = _registry_with_two_writers()
    executor = ContextNodeExecutor(
        agent_registry=registry,
        agent_selector=DefaultAgentSelector(),
    )
    node = Node.agent(id="w", name="write", agent_id="WriterBusy")

    result = await executor.execute_node(node, Context())

    assert result.success
    assert "WriterBusy" in (result.output or "")  # named agent ran, not the auction winner
    assert "selection" not in result.metadata
