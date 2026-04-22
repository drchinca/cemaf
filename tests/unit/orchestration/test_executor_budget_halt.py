"""Regression tests — BudgetGuard must read the telemetry keys and halt the DAG.

Before the fix, executor read `cost_usd`/`tokens_used` from NodeResult.metadata
but telemetry writes `cost_estimate_usd`/`tokens_total`, so every node recorded
zero cost and the cap never fired.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.core.enums import NodeType, RunStatus
from cemaf.core.types import AgentID, NodeID
from cemaf.observability.budget_guard import BudgetGuard
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices


class _EchoGoal(BaseModel):
    text: str = "hi"


class _EchoResult(BaseModel):
    text: str


class _CostlyAgent(Agent[_EchoGoal, _EchoResult]):
    """Agent that reports a fixed cost/token usage in the telemetry format."""

    def __init__(self, *, cost_usd: float, tokens: int, key_style: str = "telemetry") -> None:
        self._cost = cost_usd
        self._tokens = tokens
        self._key_style = key_style

    @property
    def id(self) -> AgentID:
        return AgentID("Costly")

    @property
    def description(self) -> str:
        return "Reports fixed cost/tokens to exercise BudgetGuard"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _EchoGoal, context: AgentContext) -> AgentResult[_EchoResult]:
        if self._key_style == "telemetry":
            metadata = {"cost_estimate_usd": self._cost, "tokens_total": self._tokens}
        else:
            metadata = {"cost_usd": self._cost, "tokens_used": self._tokens}
        return AgentResult.ok(
            output=_EchoResult(text=goal.text),
            state=AgentState(),
            metadata=metadata,
        )


def _linear_dag(node_count: int) -> DAG:
    nodes = tuple(
        Node(
            id=NodeID(f"n{i}"),
            type=NodeType.AGENT,
            name=f"n{i}",
            ref_id="Costly",
            input_mapping={"text": f"call-{i}"},
            output_key=f"out_{i}",
            retry_on_failure=False,
        )
        for i in range(node_count)
    )
    return DAG(name="budget-test", nodes=nodes, edges=(), entry_node=nodes[0].id)


@pytest.mark.asyncio
async def test_budget_halts_on_telemetry_keys() -> None:
    """Regression for P0 #27: cost_estimate_usd must be summed, not ignored."""
    registry = AgentRegistry()
    registry.register_agent(
        agent_instance=_CostlyAgent(cost_usd=0.4, tokens=100, key_style="telemetry"),
        goal_type=_EchoGoal,
    )
    guard = BudgetGuard(max_cost_usd=1.0)
    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(budget_guard=guard),
    )

    # Each node costs 0.40 USD; cap is 1.00. Third node trips the halt.
    result = await executor.run(dag=_linear_dag(node_count=5))

    assert result.status == RunStatus.FAILED
    assert "udget" in (result.error or "")
    # Two successful nodes × 0.40 = 0.80 recorded before the third triggers halt;
    # the third node's cost is also recorded before should_halt() is checked.
    assert guard.accumulated_cost_usd >= 1.0


@pytest.mark.asyncio
async def test_budget_accepts_legacy_keys() -> None:
    """Back-compat: handwritten metadata using `cost_usd`/`tokens_used` still counts."""
    registry = AgentRegistry()
    registry.register_agent(
        agent_instance=_CostlyAgent(cost_usd=0.6, tokens=50, key_style="legacy"),
        goal_type=_EchoGoal,
    )
    guard = BudgetGuard(max_cost_usd=1.0)
    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(budget_guard=guard),
    )
    result = await executor.run(dag=_linear_dag(node_count=3))
    assert result.status == RunStatus.FAILED
    assert guard.accumulated_cost_usd >= 1.0


@pytest.mark.asyncio
async def test_budget_does_not_halt_under_cap() -> None:
    registry = AgentRegistry()
    registry.register_agent(
        agent_instance=_CostlyAgent(cost_usd=0.1, tokens=10, key_style="telemetry"),
        goal_type=_EchoGoal,
    )
    guard = BudgetGuard(max_cost_usd=1.0)
    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(budget_guard=guard),
    )
    result = await executor.run(dag=_linear_dag(node_count=3))
    assert result.status == RunStatus.COMPLETED
    assert guard.accumulated_cost_usd == pytest.approx(0.3)
