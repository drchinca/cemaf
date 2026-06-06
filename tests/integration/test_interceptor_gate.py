"""Integration: the interceptor spine makes a GATE eval genuinely BLOCK downstream.

Closes the standing audit P0 (GATE evaluators only emitted an event; nothing
blocked). A real 2-node DAG (gen → use, ON_SUCCESS) with a GateEvalInterceptor on
`gen`: short output fails the gate → `use` never runs; long output passes → `use`
runs. Plus: empty pipeline is a no-op, and a gate-reject does not burn retries.
No mocks — real executor, real LengthEvaluator.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from cemaf.agents.base import AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.core.enums import RunStatus
from cemaf.core.types import AgentID, NodeID
from cemaf.evals.evaluators import LengthEvaluator
from cemaf.interceptors import GateEvalInterceptor, create_interceptor_pipeline
from cemaf.orchestration.dag import DAG, Edge, EdgeCondition, Node
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices


class _GenGoal(BaseModel):
    pass


class _Gen:
    """Emits a configurable-length output; tracks run count to prove no retry-burn."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.runs = 0

    @property
    def id(self) -> AgentID:
        return AgentID("gen")

    @property
    def description(self) -> str:
        return "generator"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _GenGoal, context: AgentContext) -> AgentResult[str]:
        self.runs += 1
        return AgentResult.ok(output=self._text, state=AgentState())


class _UseGoal(BaseModel):
    pass


class _Use:
    """Downstream node — appends to a shared ledger when it actually runs."""

    def __init__(self, ran: list[str]) -> None:
        self._ran = ran

    @property
    def id(self) -> AgentID:
        return AgentID("use")

    @property
    def description(self) -> str:
        return "consumer"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _UseGoal, context: AgentContext) -> AgentResult[str]:
        self._ran.append("use")
        return AgentResult.ok(output="used", state=AgentState())


def _dag(*, gen_retry: bool = False) -> DAG:
    gen = Node(
        id=NodeID("gen"),
        type=Node.agent(id="gen", name="gen", agent_id="gen").type,
        name="gen",
        ref_id="gen",
        output_key="draft",
        retry_on_failure=gen_retry,
        max_retries=3,
    )
    use = Node.agent(id="use", name="use", agent_id="use", output_key="final")
    return DAG(
        name="gated",
        nodes=(gen, use),
        edges=(Edge(source=NodeID("gen"), target=NodeID("use"), condition=EdgeCondition.ON_SUCCESS),),
        entry_node=NodeID("gen"),
    )


def _registry(gen: _Gen, ran: list[str]) -> AgentRegistry:
    reg = AgentRegistry()
    reg.register_agent(agent_instance=gen, goal_type=_GenGoal)
    reg.register_agent(agent_instance=_Use(ran), goal_type=_UseGoal)
    return reg


def _gate_pipeline(min_length: int = 100):
    return create_interceptor_pipeline(
        interceptors=(
            GateEvalInterceptor(
                evaluators=(LengthEvaluator(min_length=min_length),),
                node_pattern="gen",
                threshold=0.5,
            ),
        )
    )


@pytest.mark.asyncio
async def test_gate_failure_blocks_downstream() -> None:
    gen, ran = _Gen("short"), []  # 5 chars < 100 → fails the gate
    executor = create_executor(
        agent_registry=_registry(gen, ran),
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(interceptor_pipeline=_gate_pipeline()),
    )
    run = await executor.run(dag=_dag())

    gen_result = next(r for r in run.node_results if r.node_id == NodeID("gen"))
    assert gen_result.success is False
    assert gen_result.metadata["interceptors"]["gate_rejected"] is True
    assert ran == []  # downstream 'use' never executed — the gate BLOCKED


@pytest.mark.asyncio
async def test_gate_pass_lets_downstream_run() -> None:
    gen, ran = _Gen("x" * 200), []  # 200 chars >= 100 → passes
    executor = create_executor(
        agent_registry=_registry(gen, ran),
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(interceptor_pipeline=_gate_pipeline()),
    )
    run = await executor.run(dag=_dag())

    gen_result = next(r for r in run.node_results if r.node_id == NodeID("gen"))
    assert gen_result.success is True
    assert gen_result.metadata["interceptors"]["gate_eval:gen"] == {"gate": "passed", "evaluators": 1}
    assert ran == ["use"]  # downstream ran


@pytest.mark.asyncio
async def test_empty_pipeline_is_noop() -> None:
    gen, ran = _Gen("short"), []
    executor = create_executor(
        agent_registry=_registry(gen, ran),
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(interceptor_pipeline=create_interceptor_pipeline()),
    )
    run = await executor.run(dag=_dag())

    # No gate → 'short' is a perfectly successful node → downstream runs.
    assert run.status is RunStatus.COMPLETED
    gen_result = next(r for r in run.node_results if r.node_id == NodeID("gen"))
    assert gen_result.success is True
    assert "interceptors" not in gen_result.metadata
    assert ran == ["use"]


@pytest.mark.asyncio
async def test_gate_reject_does_not_burn_retries() -> None:
    gen, ran = _Gen("short"), []  # deterministically fails the gate
    executor = create_executor(
        agent_registry=_registry(gen, ran),
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(interceptor_pipeline=_gate_pipeline()),
    )
    await executor.run(dag=_dag(gen_retry=True))  # retry_on_failure=True, max_retries=3

    # A deterministic gate reject must NOT re-run the agent 3x.
    assert gen.runs == 1
