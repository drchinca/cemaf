"""Regression tests — LOOP body honors outer halt signals between iterations.

Before the fix, the QualityPolice halt check only fired between DAG nodes,
so a LOOP body would keep iterating after halt fired — wasting N-1 LLM calls.
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


class _TickGoal(BaseModel):
    tick: int = 0


class _TickResult(BaseModel):
    tick: int


class _CountingAgent(Agent[_TickGoal, _TickResult]):
    """Agent that records every call and reports fixed cost so BudgetGuard can halt."""

    def __init__(self, *, cost_per_call: float = 0.4) -> None:
        self.calls = 0
        self._cost = cost_per_call

    @property
    def id(self) -> AgentID:
        return AgentID("Tick")

    @property
    def description(self) -> str:
        return "Counts its invocations; reports cost to BudgetGuard"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _TickGoal, context: AgentContext) -> AgentResult[_TickResult]:
        self.calls += 1
        return AgentResult.ok(
            output=_TickResult(tick=self.calls),
            state=AgentState(),
            metadata={"cost_estimate_usd": self._cost, "tokens_total": 100},
        )


def _loop_dag(max_iterations: int = 10) -> DAG:
    body = Node(
        id=NodeID("body"),
        type=NodeType.AGENT,
        name="body",
        ref_id="Tick",
        input_mapping={"tick": 0},
        output_key="tick_out",
        retry_on_failure=False,
    )
    loop = Node.loop(
        id="loop",
        name="loop",
        body_node_ids=("body",),
        max_iterations=max_iterations,
    )
    return DAG(
        name="loop-halt-test",
        nodes=(loop, body),
        edges=(),
        entry_node=loop.id,
    )


@pytest.mark.asyncio
async def test_loop_halts_mid_body_on_budget_exhaustion() -> None:
    """Regression for P1 #38.

    With 10 max iterations and cost=0.4 per call, a 1.00 budget cap should
    halt after ~3 iterations — not run all 10.
    """
    registry = AgentRegistry()
    agent = _CountingAgent(cost_per_call=0.4)
    registry.register_agent(agent_instance=agent, goal_type=_TickGoal)
    guard = BudgetGuard(max_cost_usd=1.0)
    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(budget_guard=guard),
    )

    await executor.run(dag=_loop_dag(max_iterations=10))

    # Deterministic count: cost 0.4/call, cap 1.0. Halt checked BEFORE each
    # iteration after prior cost was recorded. Iteration 1: cost=0.4, not
    # halted. Iteration 2: 0.8, not halted. Iteration 3: 1.2 > 1.0, halted
    # BEFORE running. Exactly 3 calls.
    assert agent.calls == 3, f"expected exactly 3 iterations before halt, got {agent.calls}"


@pytest.mark.asyncio
async def test_loop_completes_normally_without_halt_signal() -> None:
    """No budget guard, no halt → loop runs to max_iterations."""
    registry = AgentRegistry()
    agent = _CountingAgent()
    registry.register_agent(agent_instance=agent, goal_type=_TickGoal)
    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(),
    )

    result = await executor.run(dag=_loop_dag(max_iterations=5))

    assert result.status == RunStatus.COMPLETED
    assert agent.calls == 5
