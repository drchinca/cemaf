"""Integration: CitationMembershipEvaluator makes the interceptor spine BLOCK
on a fabricated citation — the enforcement gap flagged against citation/:
CitationTracker records and warns, but nothing rejected a citation pointing
at a source that was never actually retrieved.

Real 2-node DAG (cite → use, ON_SUCCESS) with a GateEvalInterceptor bound to
CitationMembershipEvaluator on `cite`: a citation to an unknown source_id
fails the gate → `use` never runs; a citation to a known source_id passes →
`use` runs. No mocks — real executor, real StaticSourceRegistry.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from cemaf.agents.base import AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.citation.eval import CitationMembershipEvaluator
from cemaf.citation.models import Citation
from cemaf.citation.registry import StaticSourceRegistry
from cemaf.core.enums import RunStatus
from cemaf.core.types import AgentID, NodeID
from cemaf.interceptors import GateEvalInterceptor, create_interceptor_pipeline
from cemaf.orchestration.dag import DAG, Edge, EdgeCondition, Node
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices


class _CiteGoal(BaseModel):
    pass


class _Cite:
    """Emits a citation to a configurable source_id."""

    def __init__(self, source_id: str) -> None:
        self._source_id = source_id

    @property
    def id(self) -> AgentID:
        return AgentID("cite")

    @property
    def description(self) -> str:
        return "citer"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _CiteGoal, context: AgentContext) -> AgentResult[Citation]:
        citation = Citation(
            id="cite-under-test",
            source_id=self._source_id,
            source_type="document",
            title="Under test",
        )
        return AgentResult.ok(output=citation, state=AgentState())


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


def _dag() -> DAG:
    cite = Node.agent(id="cite", name="cite", agent_id="cite", output_key="draft")
    use = Node.agent(id="use", name="use", agent_id="use", output_key="final")
    return DAG(
        name="citation_gated",
        nodes=(cite, use),
        edges=(Edge(source=NodeID("cite"), target=NodeID("use"), condition=EdgeCondition.ON_SUCCESS),),
        entry_node=NodeID("cite"),
    )


def _registry(citer: _Cite, ran: list[str]) -> AgentRegistry:
    reg = AgentRegistry()
    reg.register_agent(agent_instance=citer, goal_type=_CiteGoal)
    reg.register_agent(agent_instance=_Use(ran), goal_type=_UseGoal)
    return reg


def _membership_gate_pipeline():
    registry = StaticSourceRegistry.from_iterable(["doc-001"])
    return create_interceptor_pipeline(
        interceptors=(
            GateEvalInterceptor(
                evaluators=(CitationMembershipEvaluator(registry=registry),),
                node_pattern="cite",
                threshold=0.5,
            ),
        )
    )


@pytest.mark.asyncio
async def test_fabricated_citation_blocks_downstream() -> None:
    citer, ran = _Cite("fabricated-source"), []
    executor = create_executor(
        agent_registry=_registry(citer, ran),
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(interceptor_pipeline=_membership_gate_pipeline()),
    )
    run = await executor.run(dag=_dag())

    cite_result = next(r for r in run.node_results if r.node_id == NodeID("cite"))
    assert cite_result.success is False
    assert cite_result.metadata["interceptors"]["gate_rejected"] is True
    assert ran == []  # downstream 'use' never executed — the fabricated citation was BLOCKED


@pytest.mark.asyncio
async def test_real_citation_lets_downstream_run() -> None:
    citer, ran = _Cite("doc-001"), []
    executor = create_executor(
        agent_registry=_registry(citer, ran),
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(interceptor_pipeline=_membership_gate_pipeline()),
    )
    run = await executor.run(dag=_dag())

    cite_result = next(r for r in run.node_results if r.node_id == NodeID("cite"))
    assert cite_result.success is True
    assert run.status is RunStatus.COMPLETED
    assert ran == ["use"]
