"""Integration: PullInterceptor genuinely hydrates a real agent's context.

Closes the "unconsumed infrastructure" gap: a real DataSource → real
PullInterceptor.pre() → AgentContext.artifacts["surfaced_sources"] → a real
agent's run() reads it → NodeResult.output proves the chunk actually
travelled end to end. No mocks — real DAGExecutor, real DataSourceRegistry.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from pydantic import BaseModel

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.citation.models import Citation
from cemaf.context.budget import TokenBudget
from cemaf.core.enums import RunStatus
from cemaf.core.types import AgentID, NodeID
from cemaf.datasources.models import CiteableChunk, DataSourceCapability, HealthStatus, RetrievalQuery
from cemaf.datasources.registry import DataSourceRegistry, source_registry_from_data_sources
from cemaf.interceptors import PullInterceptor, create_interceptor_pipeline
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.services import RuntimeServices


class _FakeCRM:
    """A real (not mocked) DataSource — tracks how many times it was called."""

    source_id: ClassVar[str] = "fake_crm"
    capabilities: ClassVar[frozenset[DataSourceCapability]] = frozenset({DataSourceCapability.SEARCH})

    def __init__(
        self, *, chunks: tuple[CiteableChunk, ...], health: HealthStatus = HealthStatus.HEALTHY
    ) -> None:
        self._chunks = chunks
        self._health = health
        self.retrieve_calls = 0

    async def retrieve(self, *, query: RetrievalQuery, budget: TokenBudget) -> tuple[CiteableChunk, ...]:
        self.retrieve_calls += 1
        return self._chunks

    async def health(self) -> HealthStatus:
        return self._health


class _EchoGoal(BaseModel):
    pass


class _EchoAgent(Agent[_EchoGoal, list]):
    """Real agent — reads context.artifacts['surfaced_sources'] and returns
    the source_ids so the test can assert without reaching into executor internals."""

    @property
    def id(self) -> AgentID:
        return AgentID("echo")

    @property
    def description(self) -> str:
        return "echoes surfaced source_ids"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _EchoGoal, context: AgentContext) -> AgentResult[list]:
        surfaced = context.artifacts.get("surfaced_sources", ())
        return AgentResult.ok([chunk.citation.source_id for chunk in surfaced], AgentState())


def _chunk(*, chunk_id: str, source_id: str) -> CiteableChunk:
    citation = Citation(id=chunk_id, source_id=source_id, source_type="document", url="https://example.com/x")
    return CiteableChunk(
        chunk_id=chunk_id, content="crm record", citation=citation, token_count=10, source_kind="datasource"
    )


def _dag() -> DAG:
    node = Node.agent(id="echo_node", name="lookup account", agent_id="echo", output_key="result")
    return DAG(name="pull_dag", nodes=(node,), edges=(), entry_node=NodeID("echo_node"))


def _registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register_agent(agent_instance=_EchoAgent(), goal_type=_EchoGoal)
    return reg


@pytest.mark.asyncio
async def test_data_source_chunk_reaches_the_agent() -> None:
    crm = _FakeCRM(chunks=(_chunk(chunk_id="c1", source_id="fake_crm"),))
    data_sources = DataSourceRegistry()
    data_sources.register(crm)

    pipeline = create_interceptor_pipeline(
        interceptors=(PullInterceptor(pull_tokens=500, data_source_registry=data_sources),)
    )
    executor = create_executor(
        agent_registry=_registry(),
        services=RuntimeServices(interceptor_pipeline=pipeline, data_source_registry=data_sources),
    )

    run = await executor.run(dag=_dag())

    assert run.status is RunStatus.COMPLETED
    assert crm.retrieve_calls == 1
    node_result = next(r for r in run.node_results if r.node_id == NodeID("echo_node"))
    assert node_result.success is True
    assert "fake_crm" in node_result.output


@pytest.mark.asyncio
async def test_unhealthy_source_never_called_and_run_still_completes() -> None:
    crm = _FakeCRM(chunks=(_chunk(chunk_id="c1", source_id="fake_crm"),), health=HealthStatus.UNHEALTHY)
    data_sources = DataSourceRegistry()
    data_sources.register(crm)

    pipeline = create_interceptor_pipeline(
        interceptors=(PullInterceptor(pull_tokens=500, data_source_registry=data_sources),)
    )
    executor = create_executor(
        agent_registry=_registry(),
        services=RuntimeServices(interceptor_pipeline=pipeline, data_source_registry=data_sources),
    )

    run = await executor.run(dag=_dag())

    assert run.status is RunStatus.COMPLETED
    assert crm.retrieve_calls == 0
    node_result = next(r for r in run.node_results if r.node_id == NodeID("echo_node"))
    assert node_result.output == "[]"


@pytest.mark.asyncio
async def test_source_registry_adapter_reflects_real_registered_source() -> None:
    """Proves the DataSourceRegistry -> citation-membership adapter is wired
    to REAL registered sources, not a hand-maintained static allow-list."""
    crm = _FakeCRM(chunks=())
    data_sources = DataSourceRegistry()
    data_sources.register(crm)

    source_registry = source_registry_from_data_sources(data_sources)

    assert source_registry.is_known("fake_crm")
    assert not source_registry.is_known("fabricated_source")
