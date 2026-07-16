"""Unit tests for PullInterceptor — constructs it directly, calls .pre() with a
hand-built Node/AgentContext, asserts on PreflightDecision. No DAGExecutor."""

from datetime import datetime
from typing import ClassVar

import pytest

from cemaf.agents.base import AgentContext
from cemaf.citation.models import Citation
from cemaf.context.budget import TokenBudget
from cemaf.datasources.entity_extractor import DefaultEntityExtractor
from cemaf.datasources.models import (
    CiteableChunk,
    DataSourceCapability,
    HealthStatus,
    RetrievalQuery,
    SourceKind,
)
from cemaf.datasources.registry import DataSourceRegistry
from cemaf.interceptors.pull import PullInterceptor
from cemaf.interceptors.types import DecisionKind
from cemaf.knowledge.models import KGEntity, KGQueryResult, KGRelation, RelationType
from cemaf.orchestration.dag import Node


def _node(*, node_id: str = "n1", name: str = "lookup", description: str = "") -> Node:
    return Node.agent(id=node_id, name=name, agent_id="fake-agent", description=description)


def _context(*, run_id: str = "run-1") -> AgentContext:
    return AgentContext(run_id=run_id, agent_id="fake-agent")


def _chunk(
    *,
    chunk_id: str,
    source_id: str,
    token_count: int = 10,
    source_kind: SourceKind = SourceKind.DATASOURCE,
    retrieved_at: datetime | None = None,
) -> CiteableChunk:
    citation = Citation(id=chunk_id, source_id=source_id, source_type="document", url="https://example.com")
    kwargs: dict[str, object] = {
        "chunk_id": chunk_id,
        "content": "chunk content",
        "citation": citation,
        "token_count": token_count,
        "source_kind": source_kind,
    }
    if retrieved_at is not None:
        kwargs["retrieved_at"] = retrieved_at
    return CiteableChunk(**kwargs)  # type: ignore[arg-type]


class _FakeKnowledgeGraph:
    """Minimal real (not mocked) KnowledgeGraph — only query_neighbors is exercised."""

    def __init__(self, *, result: KGQueryResult | None = None, raise_error: bool = False) -> None:
        self._result = result or KGQueryResult()
        self._raise_error = raise_error
        self.calls = 0

    async def add_entity(self, entity: KGEntity) -> None:
        raise NotImplementedError

    async def add_relation(self, relation: KGRelation) -> None:
        raise NotImplementedError

    async def get_entity(self, entity_id: str) -> KGEntity | None:
        raise NotImplementedError

    async def query_neighbors(self, entity_id: str, relation_type=None, depth: int = 1) -> KGQueryResult:
        self.calls += 1
        if self._raise_error:
            raise RuntimeError("kg unavailable")
        return self._result

    async def search(self, query: str, entity_type=None, limit: int = 10) -> tuple:
        raise NotImplementedError

    async def remove_entity(self, entity_id: str) -> bool:
        raise NotImplementedError


class _FakeDataSource:
    capabilities: ClassVar[frozenset[DataSourceCapability]] = frozenset({DataSourceCapability.SEARCH})

    def __init__(
        self,
        *,
        source_id: str = "fake-crm",
        chunks: tuple[CiteableChunk, ...] = (),
        health: HealthStatus = HealthStatus.HEALTHY,
    ) -> None:
        self.source_id = source_id
        self._chunks = chunks
        self._health = health
        self.retrieve_calls = 0
        self.last_budget: TokenBudget | None = None

    async def retrieve(self, *, query: RetrievalQuery, budget: TokenBudget) -> tuple[CiteableChunk, ...]:
        self.retrieve_calls += 1
        self.last_budget = budget
        return self._chunks

    async def health(self) -> HealthStatus:
        return self._health


@pytest.mark.asyncio
class TestPullInterceptorNodeMatching:
    async def test_node_pattern_mismatch_is_noop(self) -> None:
        interceptor = PullInterceptor(pull_tokens=1000, node_pattern="other-node")
        decision = await interceptor.pre(node=_node(node_id="n1"), context=_context())
        assert decision.kind is DecisionKind.ACCEPT
        assert decision.enriched_context is None


@pytest.mark.asyncio
class TestPullInterceptorKnowledgeGraph:
    async def test_kg_neighbors_populate_surfaced_sources(self) -> None:
        relation = KGRelation(source_id="order-42", target_id="customer-7", type=RelationType.PRODUCES)
        kg = _FakeKnowledgeGraph(result=KGQueryResult(relations=(relation,)))
        interceptor = PullInterceptor(
            pull_tokens=1000, knowledge_graph=kg, entity_extractor=DefaultEntityExtractor()
        )
        decision = await interceptor.pre(node=_node(name="OrderPipeline lookup"), context=_context())
        assert decision.kind is DecisionKind.ACCEPT
        assert decision.enriched_context is not None
        surfaced = decision.enriched_context.artifacts["surfaced_sources"]
        assert len(surfaced) == 1
        assert surfaced[0].source_kind == SourceKind.KG
        assert surfaced[0].citation.source_id == SourceKind.KG

    async def test_kg_query_failure_is_contained(self) -> None:
        kg = _FakeKnowledgeGraph(raise_error=True)
        interceptor = PullInterceptor(
            pull_tokens=1000, knowledge_graph=kg, entity_extractor=DefaultEntityExtractor()
        )
        decision = await interceptor.pre(node=_node(name="OrderPipeline lookup"), context=_context())
        assert decision.kind is DecisionKind.ACCEPT
        assert decision.enriched_context.artifacts["surfaced_sources"] == ()

    async def test_no_entities_skips_kg_query(self) -> None:
        kg = _FakeKnowledgeGraph()
        interceptor = PullInterceptor(
            pull_tokens=1000, knowledge_graph=kg, entity_extractor=DefaultEntityExtractor()
        )
        await interceptor.pre(node=_node(name="plain text no entities"), context=_context())
        assert kg.calls == 0


@pytest.mark.asyncio
class TestPullInterceptorDataSources:
    async def test_two_healthy_sources_uniform_split(self) -> None:
        registry = DataSourceRegistry()
        source_a = _FakeDataSource(
            source_id="source-a", chunks=(_chunk(chunk_id="a1", source_id="fake-crm"),)
        )
        source_b = _FakeDataSource(
            source_id="source-b", chunks=(_chunk(chunk_id="b1", source_id="fake-crm"),)
        )
        registry.register(source_a)
        registry.register(source_b)

        interceptor = PullInterceptor(pull_tokens=2000, data_source_registry=registry)
        await interceptor.pre(node=_node(), context=_context())

        assert source_a.retrieve_calls == 1
        assert source_b.retrieve_calls == 1
        assert source_a.last_budget.max_tokens == 1000
        assert source_b.last_budget.max_tokens == 1000

    async def test_source_weights_produce_weighted_split(self) -> None:
        registry = DataSourceRegistry()
        source_a = _FakeDataSource(source_id="source-a")
        source_b = _FakeDataSource(source_id="source-b")
        registry.register(source_a)
        registry.register(source_b)

        interceptor = PullInterceptor(
            pull_tokens=2000,
            data_source_registry=registry,
            source_weights={"source-a": 0.75, "source-b": 0.25},
        )
        await interceptor.pre(node=_node(), context=_context())

        assert source_a.last_budget.max_tokens == 1500
        assert source_b.last_budget.max_tokens == 500

    async def test_unhealthy_source_never_called(self) -> None:
        registry = DataSourceRegistry()
        source = _FakeDataSource(health=HealthStatus.UNHEALTHY)
        registry.register(source)

        interceptor = PullInterceptor(pull_tokens=1000, data_source_registry=registry)
        decision = await interceptor.pre(node=_node(), context=_context())

        assert source.retrieve_calls == 0
        assert decision.kind is DecisionKind.ACCEPT
        assert decision.enriched_context.artifacts["surfaced_sources"] == ()

    async def test_timed_out_source_skipped_others_survive(self) -> None:
        import asyncio

        class _SlowSource(_FakeDataSource):
            async def retrieve(self, *, query, budget):
                await asyncio.sleep(10)
                return ()

        registry = DataSourceRegistry()
        slow = _SlowSource(source_id="slow")
        fast = _FakeDataSource(source_id="fast", chunks=(_chunk(chunk_id="fast1", source_id="fake-crm"),))
        registry.register(slow)
        registry.register(fast)

        interceptor = PullInterceptor(pull_tokens=1000, data_source_registry=registry, timeout_ms=50)
        decision = await interceptor.pre(node=_node(), context=_context())

        surfaced = decision.enriched_context.artifacts["surfaced_sources"]
        assert len(surfaced) == 1
        assert surfaced[0].chunk_id == "fast1"


@pytest.mark.asyncio
class TestPullInterceptorGrounding:
    async def test_grounding_required_with_no_candidates_rejects(self) -> None:
        interceptor = PullInterceptor(pull_tokens=1000, grounding_required_nodes=frozenset({"n1"}))
        decision = await interceptor.pre(node=_node(node_id="n1"), context=_context())
        assert decision.kind is DecisionKind.REJECT
        assert decision.reason == "no_grounding_available"

    async def test_grounding_not_required_with_no_candidates_accepts(self) -> None:
        interceptor = PullInterceptor(pull_tokens=1000)
        decision = await interceptor.pre(node=_node(node_id="n1"), context=_context())
        assert decision.kind is DecisionKind.ACCEPT


@pytest.mark.asyncio
class TestPullInterceptorEviction:
    async def test_eviction_deterministic_tiebreak_by_chunk_id(self) -> None:
        """All chunks tied on priority, confidence, and retrieved_at — chunk_id ASC breaks the tie."""
        registry = DataSourceRegistry()
        same_instant = datetime(2026, 1, 1)
        chunks = tuple(
            _chunk(chunk_id=f"c{i}", source_id="fake-crm", token_count=100, retrieved_at=same_instant)
            for i in reversed(range(5))
        )
        source = _FakeDataSource(chunks=chunks)
        registry.register(source)

        interceptor = PullInterceptor(pull_tokens=1000, data_source_registry=registry)
        decision = await interceptor.pre(node=_node(), context=_context())
        surfaced_ids = [c.chunk_id for c in decision.enriched_context.artifacts["surfaced_sources"]]
        assert surfaced_ids == sorted(surfaced_ids)

    async def test_over_budget_truncates(self) -> None:
        registry = DataSourceRegistry()
        chunks = tuple(_chunk(chunk_id=f"c{i}", source_id="fake-crm", token_count=100) for i in range(5))
        source = _FakeDataSource(chunks=chunks)
        registry.register(source)

        interceptor = PullInterceptor(pull_tokens=250, data_source_registry=registry)
        decision = await interceptor.pre(node=_node(), context=_context())
        surfaced = decision.enriched_context.artifacts["surfaced_sources"]
        assert sum(c.token_count for c in surfaced) <= 250

    async def test_repeated_runs_are_byte_identical(self) -> None:
        registry = DataSourceRegistry()
        chunks = tuple(_chunk(chunk_id=f"c{i}", source_id="fake-crm", token_count=50) for i in range(3))
        source = _FakeDataSource(chunks=chunks)
        registry.register(source)

        interceptor = PullInterceptor(pull_tokens=1000, data_source_registry=registry)
        first = await interceptor.pre(node=_node(), context=_context())
        second = await interceptor.pre(node=_node(), context=_context())
        assert (
            first.enriched_context.artifacts["surfaced_sources"]
            == second.enriched_context.artifacts["surfaced_sources"]
        )

    async def test_kg_priority_band_outranks_datasource_when_over_budget(self) -> None:
        """SPEC-02 Inv 11/12: kg (priority 100) SHALL evict a datasource chunk
        (priority 80) when both compete for the same budget — proves the
        priority band actually governs cross-source-kind eviction, not just
        within one source_kind."""
        relation = KGRelation(source_id="order-42", target_id="customer-7", type=RelationType.PRODUCES)
        kg = _FakeKnowledgeGraph(result=KGQueryResult(relations=(relation,)))

        registry = DataSourceRegistry()
        datasource_chunk = _chunk(
            chunk_id="ds1", source_id="fake-crm", token_count=100, retrieved_at=datetime(2026, 1, 1)
        )
        source = _FakeDataSource(chunks=(datasource_chunk,))
        registry.register(source)

        # Budget fits only ONE chunk — kg's real token_count is small (see
        # _pull_kg's estimate), so this asserts against whichever chunk the
        # real interceptor actually produces, not a hand-picked number.
        interceptor = PullInterceptor(
            pull_tokens=5,
            knowledge_graph=kg,
            data_source_registry=registry,
            entity_extractor=DefaultEntityExtractor(),
        )
        decision = await interceptor.pre(node=_node(name="OrderPipeline lookup"), context=_context())
        surfaced = decision.enriched_context.artifacts["surfaced_sources"]

        assert len(surfaced) == 1
        assert surfaced[0].source_kind == SourceKind.KG
        assert datasource_chunk not in surfaced


@pytest.mark.asyncio
class TestPullInterceptorTokenBudgetReconciliation:
    async def test_caps_pull_tokens_against_compiled_context_share(self) -> None:
        """context_node_executor.py stashes compiled_context_tokens alongside
        compiled_context; with a real token_budget configured, PullInterceptor
        must shrink its own contribution so surfaced_sources + compiled_context
        can't together exceed the model window — not just pull_tokens alone."""
        registry = DataSourceRegistry()
        chunks = tuple(_chunk(chunk_id=f"c{i}", source_id="fake-crm", token_count=100) for i in range(5))
        source = _FakeDataSource(chunks=chunks)
        registry.register(source)

        budget = TokenBudget(max_tokens=300, reserved_for_output=0)
        interceptor = PullInterceptor(
            pull_tokens=1000,  # would fit all 5 chunks (500 tokens) on its own
            data_source_registry=registry,
            token_budget=budget,
        )
        context = AgentContext(
            run_id="run-1", agent_id="fake-agent", artifacts={"compiled_context_tokens": 250}
        )

        decision = await interceptor.pre(node=_node(), context=context)
        surfaced = decision.enriched_context.artifacts["surfaced_sources"]

        # available_tokens=300, compiled_context already spent 250 -> only 50
        # tokens left for pulled sources, regardless of pull_tokens=1000.
        assert sum(c.token_count for c in surfaced) <= 50

    async def test_compiled_context_already_over_budget_surfaces_nothing(self) -> None:
        registry = DataSourceRegistry()
        source = _FakeDataSource(chunks=(_chunk(chunk_id="c1", source_id="fake-crm", token_count=10),))
        registry.register(source)

        budget = TokenBudget(max_tokens=100, reserved_for_output=0)
        interceptor = PullInterceptor(
            pull_tokens=1000,
            data_source_registry=registry,
            token_budget=budget,
        )
        context = AgentContext(
            run_id="run-1", agent_id="fake-agent", artifacts={"compiled_context_tokens": 500}
        )

        decision = await interceptor.pre(node=_node(), context=context)
        surfaced = decision.enriched_context.artifacts["surfaced_sources"]
        assert surfaced == ()

    async def test_no_token_budget_configured_behavior_unchanged(self) -> None:
        """Without token_budget, pull_tokens alone still governs — proves the
        reconciliation is opt-in, not a silent behavior change for existing
        callers that never pass token_budget."""
        registry = DataSourceRegistry()
        chunks = tuple(_chunk(chunk_id=f"c{i}", source_id="fake-crm", token_count=100) for i in range(3))
        source = _FakeDataSource(chunks=chunks)
        registry.register(source)

        interceptor = PullInterceptor(pull_tokens=1000, data_source_registry=registry)
        context = AgentContext(
            run_id="run-1", agent_id="fake-agent", artifacts={"compiled_context_tokens": 999_999}
        )

        decision = await interceptor.pre(node=_node(), context=context)
        surfaced = decision.enriched_context.artifacts["surfaced_sources"]
        assert sum(c.token_count for c in surfaced) == 300
