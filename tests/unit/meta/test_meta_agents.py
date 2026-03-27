"""Unit tests for meta-agents — ArchitectAgent, AgentSynthesizer, AuditAgent, KnowledgeGraphAgent."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel

from cemaf.agents.base import Agent, AgentContext
from cemaf.audit.models import AuditEntry, AuditEntryType
from cemaf.core.result import Result
from cemaf.knowledge.models import EntityType, KGEntity, KGQueryResult, KGRelation, RelationType
from cemaf.meta.agents import (
    AgentSynthesizer,
    ArchitectAgent,
    AuditAgent,
    KnowledgeGraphAgent,
)
from cemaf.meta.goals import (
    ArchitectGoal,
    ArchitectResult,
    AuditGoal,
    AuditResult,
    KnowledgeGraphGoal,
    KnowledgeGraphResult,
    SynthesizerGoal,
    SynthesizerResult,
)
from cemaf.meta.tools import (
    GenerateDAGTool,
    IntrospectRegistryTool,
    KnowledgeGraphTool,
    TraceAnalyzerTool,
)
from cemaf.tools.base import Tool, ToolSchema

# ---------------------------------------------------------------------------
# Fakes (reused patterns from test_meta_tools.py)
# ---------------------------------------------------------------------------


class _FakeGoal(BaseModel):
    topic: str
    depth: int = 3


class _FakeAgent:
    """Minimal Agent-like object for registry."""

    def __init__(self, *, agent_id: str, description: str = "A fake agent") -> None:
        self._id = agent_id
        self._description = description

    @property
    def id(self) -> str:
        return self._id

    @property
    def description(self) -> str:
        return self._description

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: Any, context: Any) -> Any:
        return None


class _FakeTool(Tool):
    """Minimal Tool for registry population."""

    def __init__(self, *, name: str) -> None:
        self._name = name

    @property
    def id(self) -> str:  # type: ignore[override]
        return self._name

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self._name,
            description=f"Fake tool {self._name}",
            parameters={"type": "object", "properties": {"x": {"type": "string"}}},
            required=("x",),
        )

    async def execute(self, **kwargs: Any) -> Result[Any]:
        return Result.ok(data="ok")


class FakeAgentRegistry:
    """Minimal stand-in for AgentRegistry."""

    def __init__(self) -> None:
        self._agents: dict[str, _FakeAgent] = {}
        self._goal_types: dict[str, type[BaseModel]] = {}

    def register(self, *, agent: _FakeAgent, goal_type: type[BaseModel] | None = None) -> None:
        self._agents[agent.id] = agent
        if goal_type is not None:
            self._goal_types[agent.id] = goal_type

    def list_agents(self) -> list[str]:
        return list(self._agents.keys())

    def get(self, agent_name: str) -> _FakeAgent | None:
        return self._agents.get(agent_name)

    def get_goal_type(self, agent_name: str) -> type[BaseModel] | None:
        return self._goal_types.get(agent_name)

    def get_capabilities_description(self) -> str:
        if not self._agents:
            return "No agents registered."
        lines = [f"- {aid}" for aid in self._agents]
        return "\n".join(lines)


class FakeToolRegistry:
    """Minimal stand-in for ToolRegistry."""

    def __init__(self) -> None:
        self._tools: dict[str, _FakeTool] = {}

    def register(self, *, tool: _FakeTool) -> None:
        self._tools[tool.id] = tool

    def list_tools(self) -> list[_FakeTool]:
        return list(self._tools.values())

    def to_schemas(self) -> list[ToolSchema]:
        return [t.schema for t in self._tools.values()]


_TS = datetime(2025, 1, 1, tzinfo=UTC)


def _make_entry(
    *,
    entry_id: str = "e1",
    run_id: str = "run-1",
    entry_type: AuditEntryType = AuditEntryType.NODE_EXECUTED,
) -> AuditEntry:
    return AuditEntry(
        id=entry_id,
        type=entry_type,
        timestamp=_TS,
        run_id=run_id,
        source="test",
    )


class FakeAuditTrail:
    """Minimal AuditTrail implementation."""

    def __init__(
        self,
        *,
        timeline: tuple[AuditEntry, ...] = (),
        trend: tuple[float, ...] = (),
        anomalies: tuple[AuditEntry, ...] = (),
    ) -> None:
        self._timeline = timeline
        self._trend = trend
        self._anomalies = anomalies

    async def get_run_timeline(self, run_id: str) -> tuple[AuditEntry, ...]:
        return self._timeline

    async def get_quality_trend(self, *, window: int = 20) -> tuple[float, ...]:
        return self._trend

    async def get_anomalies(self, *, threshold: float = 2.0) -> tuple[AuditEntry, ...]:
        return self._anomalies


_ENTITY_A = KGEntity(
    id="ent-1",
    type=EntityType.AGENT,
    name="Research Agent",
    description="Does research",
)
_ENTITY_B = KGEntity(
    id="ent-2",
    type=EntityType.TOOL,
    name="Search Tool",
)


class FakeKnowledgeGraph:
    """In-memory KnowledgeGraph implementation."""

    def __init__(self) -> None:
        self._entities: dict[str, KGEntity] = {}
        self._relations: list[KGRelation] = []

    async def add_entity(self, entity: KGEntity) -> None:
        self._entities[entity.id] = entity

    async def add_relation(self, relation: KGRelation) -> None:
        self._relations.append(relation)

    async def get_entity(self, entity_id: str) -> KGEntity | None:
        return self._entities.get(entity_id)

    async def query_neighbors(
        self,
        entity_id: str,
        relation_type: RelationType | None = None,
        depth: int = 1,
    ) -> KGQueryResult:
        neighbors: list[KGEntity] = []
        matched_rels: list[KGRelation] = []
        for rel in self._relations:
            if rel.source_id == entity_id:
                if relation_type is not None and rel.type != relation_type:
                    continue
                matched_rels.append(rel)
                target = self._entities.get(rel.target_id)
                if target is not None:
                    neighbors.append(target)
        return KGQueryResult(
            entities=tuple(neighbors),
            relations=tuple(matched_rels),
        )

    async def search(
        self,
        query: str,
        entity_type: EntityType | None = None,
        limit: int = 10,
    ) -> tuple[KGEntity, ...]:
        results: list[KGEntity] = []
        for ent in self._entities.values():
            if entity_type is not None and ent.type != entity_type:
                continue
            if query.lower() in ent.name.lower() or not query:
                results.append(ent)
        return tuple(results[:limit])

    async def remove_entity(self, entity_id: str) -> bool:
        if entity_id in self._entities:
            del self._entities[entity_id]
            return True
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(*, run_id: str = "test-run", agent_id: str = "test") -> AgentContext:
    return AgentContext(run_id=run_id, agent_id=agent_id)


def _make_introspect_tool(
    *,
    agent_registry: FakeAgentRegistry | None = None,
    tool_registry: FakeToolRegistry | None = None,
) -> IntrospectRegistryTool:
    ar = agent_registry or FakeAgentRegistry()
    tr = tool_registry or FakeToolRegistry()
    return IntrospectRegistryTool(
        agent_registry=ar,  # type: ignore[arg-type]
        tool_registry=tr,  # type: ignore[arg-type]
    )


def _make_trace_analyzer_tool(**kwargs: Any) -> TraceAnalyzerTool:
    trail = FakeAuditTrail(**kwargs)
    return TraceAnalyzerTool(audit_trail=trail)  # type: ignore[arg-type]


def _make_kg_tool(*, graph: FakeKnowledgeGraph | None = None) -> KnowledgeGraphTool:
    kg = graph or FakeKnowledgeGraph()
    return KnowledgeGraphTool(knowledge_graph=kg)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ArchitectAgent
# ---------------------------------------------------------------------------


class TestArchitectAgent:
    def _make_agent(
        self,
        *,
        agent_registry: FakeAgentRegistry | None = None,
    ) -> ArchitectAgent:
        if agent_registry is None:
            ar = FakeAgentRegistry()
            ar.register(agent=_FakeAgent(agent_id="Researcher"), goal_type=_FakeGoal)
            ar.register(agent=_FakeAgent(agent_id="Writer"))
        else:
            ar = agent_registry
        introspect = _make_introspect_tool(agent_registry=ar)
        dag_tool = GenerateDAGTool()
        return ArchitectAgent(
            introspect_tool=introspect,
            generate_dag_tool=dag_tool,
        )

    def test_is_agent_instance(self) -> None:
        agent = self._make_agent()
        assert isinstance(agent, Agent)

    def test_id(self) -> None:
        agent = self._make_agent()
        assert agent.id == "MetaArchitect"

    def test_description(self) -> None:
        agent = self._make_agent()
        assert "DAG" in agent.description

    def test_skills_empty(self) -> None:
        agent = self._make_agent()
        assert agent.skills == ()

    @pytest.mark.asyncio
    async def test_run_produces_dag_spec(self) -> None:
        agent = self._make_agent()
        ctx = _make_context()
        goal = ArchitectGoal(feature_description="Research and write a report")

        result = await agent.run(goal=goal, context=ctx)

        assert result.success
        assert isinstance(result.output, ArchitectResult)
        assert "nodes" in result.output.dag_spec
        assert "edges" in result.output.dag_spec
        assert len(result.output.dag_spec["nodes"]) == 2
        assert len(result.output.dag_spec["edges"]) == 1
        assert result.output.rationale

    @pytest.mark.asyncio
    async def test_run_fails_when_no_agents_in_registry(self) -> None:
        empty_registry = FakeAgentRegistry()
        agent = self._make_agent(agent_registry=empty_registry)
        ctx = _make_context()
        goal = ArchitectGoal(feature_description="Do something")

        result = await agent.run(goal=goal, context=ctx)

        assert not result.success
        assert "No agents discovered" in result.error

    @pytest.mark.asyncio
    async def test_run_single_agent_produces_no_edges(self) -> None:
        registry = FakeAgentRegistry()
        registry.register(agent=_FakeAgent(agent_id="Solo"))
        agent = self._make_agent(agent_registry=registry)
        ctx = _make_context()
        goal = ArchitectGoal(feature_description="Solo operation")

        result = await agent.run(goal=goal, context=ctx)

        assert result.success
        assert len(result.output.dag_spec["nodes"]) == 1
        assert len(result.output.dag_spec["edges"]) == 0


# ---------------------------------------------------------------------------
# AgentSynthesizer
# ---------------------------------------------------------------------------


class TestAgentSynthesizer:
    def _make_agent(self) -> AgentSynthesizer:
        return AgentSynthesizer()

    def test_is_agent_instance(self) -> None:
        agent = self._make_agent()
        assert isinstance(agent, Agent)

    def test_id(self) -> None:
        agent = self._make_agent()
        assert agent.id == "MetaSynthesizer"

    def test_description(self) -> None:
        agent = self._make_agent()
        assert "source code" in agent.description.lower() or "Python" in agent.description

    def test_skills_empty(self) -> None:
        agent = self._make_agent()
        assert agent.skills == ()

    @pytest.mark.asyncio
    async def test_run_generates_valid_code(self) -> None:
        agent = self._make_agent()
        ctx = _make_context()
        goal = SynthesizerGoal(
            agent_name="Analyzer",
            description="Analyze documents",
            goal_fields={"document_text": "str", "max_tokens": "int"},
            result_fields={"analysis": "str", "confidence": "float"},
        )

        result = await agent.run(goal=goal, context=ctx)

        assert result.success
        assert isinstance(result.output, SynthesizerResult)
        code = result.output.agent_code
        assert "class AnalyzerGoal" in code
        assert "class AnalyzerResult" in code
        assert "class AnalyzerAgent" in code
        assert "async def run" in code

    @pytest.mark.asyncio
    async def test_generated_code_contains_correct_class_name(self) -> None:
        agent = self._make_agent()
        ctx = _make_context()
        goal = SynthesizerGoal(
            agent_name="DataMiner",
            description="Mine data from sources",
        )

        result = await agent.run(goal=goal, context=ctx)

        assert result.success
        assert 'AgentID("DataMiner")' in result.output.agent_code

    @pytest.mark.asyncio
    async def test_generated_code_includes_goal_fields(self) -> None:
        agent = self._make_agent()
        ctx = _make_context()
        goal = SynthesizerGoal(
            agent_name="Fetcher",
            description="Fetch resources",
            goal_fields={"url": "str", "timeout": "int"},
            result_fields={},
        )

        result = await agent.run(goal=goal, context=ctx)

        assert result.success
        code = result.output.agent_code
        assert "url: str" in code
        assert "timeout: int" in code

    @pytest.mark.asyncio
    async def test_validation_notes_pass(self) -> None:
        agent = self._make_agent()
        ctx = _make_context()
        goal = SynthesizerGoal(
            agent_name="Valid",
            description="A valid agent",
        )

        result = await agent.run(goal=goal, context=ctx)

        assert result.success
        assert "passed" in result.output.validation_notes.lower()

    @pytest.mark.asyncio
    async def test_empty_fields_produce_pass_keyword(self) -> None:
        agent = self._make_agent()
        ctx = _make_context()
        goal = SynthesizerGoal(
            agent_name="Minimal",
            description="Minimal agent",
            goal_fields={},
            result_fields={},
        )

        result = await agent.run(goal=goal, context=ctx)

        assert result.success
        assert "pass" in result.output.agent_code


# ---------------------------------------------------------------------------
# AuditAgent
# ---------------------------------------------------------------------------


class TestAuditAgent:
    def _make_agent(self, **kwargs: Any) -> AuditAgent:
        tool = _make_trace_analyzer_tool(**kwargs)
        return AuditAgent(trace_analyzer_tool=tool)

    def test_is_agent_instance(self) -> None:
        agent = self._make_agent()
        assert isinstance(agent, Agent)

    def test_id(self) -> None:
        agent = self._make_agent()
        assert agent.id == "MetaAuditor"

    def test_description(self) -> None:
        agent = self._make_agent()
        assert "trace" in agent.description.lower()

    def test_skills_empty(self) -> None:
        agent = self._make_agent()
        assert agent.skills == ()

    @pytest.mark.asyncio
    async def test_full_analysis_returns_complete_report(self) -> None:
        entry = _make_entry(entry_id="t1", run_id="run-full")
        agent = self._make_agent(
            timeline=(entry,),
            trend=(0.9, 0.85),
            anomalies=(entry,),
        )
        ctx = _make_context()
        goal = AuditGoal(analysis_type="full", run_id="run-full")

        result = await agent.run(goal=goal, context=ctx)

        assert result.success
        assert isinstance(result.output, AuditResult)
        assert "quality_trend" in result.output.report
        assert "anomalies" in result.output.report
        assert "timeline" in result.output.report
        assert result.output.summary

    @pytest.mark.asyncio
    async def test_quality_analysis_returns_trend(self) -> None:
        agent = self._make_agent(trend=(0.9, 0.85, 0.92))
        ctx = _make_context()
        goal = AuditGoal(analysis_type="quality")

        result = await agent.run(goal=goal, context=ctx)

        assert result.success
        assert "quality_trend" in result.output.report
        assert "anomalies" not in result.output.report

    @pytest.mark.asyncio
    async def test_anomalies_analysis_returns_anomalies(self) -> None:
        entry = _make_entry(entry_id="a1")
        agent = self._make_agent(anomalies=(entry,))
        ctx = _make_context()
        goal = AuditGoal(analysis_type="anomalies")

        result = await agent.run(goal=goal, context=ctx)

        assert result.success
        assert "anomalies" in result.output.report
        assert "quality_trend" not in result.output.report

    @pytest.mark.asyncio
    async def test_unknown_analysis_type_fails(self) -> None:
        agent = self._make_agent()
        ctx = _make_context()
        goal = AuditGoal(analysis_type="unknown_type")

        result = await agent.run(goal=goal, context=ctx)

        assert not result.success
        assert "unknown_type" in result.error.lower()

    @pytest.mark.asyncio
    async def test_full_without_run_id_skips_timeline(self) -> None:
        agent = self._make_agent(trend=(0.8,), anomalies=())
        ctx = _make_context()
        goal = AuditGoal(analysis_type="full", run_id=None)

        result = await agent.run(goal=goal, context=ctx)

        assert result.success
        assert "timeline" not in result.output.report


# ---------------------------------------------------------------------------
# KnowledgeGraphAgent
# ---------------------------------------------------------------------------


class TestKnowledgeGraphAgent:
    def _make_agent(
        self,
        *,
        graph: FakeKnowledgeGraph | None = None,
    ) -> KnowledgeGraphAgent:
        kg = graph or FakeKnowledgeGraph()
        tool = _make_kg_tool(graph=kg)
        return KnowledgeGraphAgent(kg_tool=tool)

    def test_is_agent_instance(self) -> None:
        agent = self._make_agent()
        assert isinstance(agent, Agent)

    def test_id(self) -> None:
        agent = self._make_agent()
        assert agent.id == "MetaKnowledgeGraph"

    def test_description(self) -> None:
        agent = self._make_agent()
        assert "knowledge graph" in agent.description.lower()

    def test_skills_empty(self) -> None:
        agent = self._make_agent()
        assert agent.skills == ()

    @pytest.mark.asyncio
    async def test_query_returns_matching_entities(self) -> None:
        graph = FakeKnowledgeGraph()
        await graph.add_entity(entity=_ENTITY_A)
        await graph.add_entity(entity=_ENTITY_B)
        agent = self._make_agent(graph=graph)
        ctx = _make_context()
        goal = KnowledgeGraphGoal(operation="query", query="Research")

        result = await agent.run(goal=goal, context=ctx)

        assert result.success
        assert isinstance(result.output, KnowledgeGraphResult)
        assert len(result.output.entities) == 1
        assert result.output.entities[0]["name"] == "Research Agent"

    @pytest.mark.asyncio
    async def test_query_with_entity_type_filter(self) -> None:
        graph = FakeKnowledgeGraph()
        await graph.add_entity(entity=_ENTITY_A)
        await graph.add_entity(entity=_ENTITY_B)
        agent = self._make_agent(graph=graph)
        ctx = _make_context()
        goal = KnowledgeGraphGoal(
            operation="query",
            query="Tool",
            entity_type="tool",
        )

        result = await agent.run(goal=goal, context=ctx)

        assert result.success
        assert len(result.output.entities) == 1
        assert result.output.entities[0]["type"] == "tool"

    @pytest.mark.asyncio
    async def test_query_without_query_text_fails(self) -> None:
        agent = self._make_agent()
        ctx = _make_context()
        goal = KnowledgeGraphGoal(operation="query", query="")

        result = await agent.run(goal=goal, context=ctx)

        # KG tool itself fails for empty query on search op
        assert not result.success

    @pytest.mark.asyncio
    async def test_stats_returns_entity_count(self) -> None:
        graph = FakeKnowledgeGraph()
        await graph.add_entity(entity=_ENTITY_A)
        await graph.add_entity(entity=_ENTITY_B)
        agent = self._make_agent(graph=graph)
        ctx = _make_context()
        goal = KnowledgeGraphGoal(operation="stats")

        result = await agent.run(goal=goal, context=ctx)

        assert result.success
        assert result.output.stats["total_entities"] == 2
        assert result.output.entities == ()

    @pytest.mark.asyncio
    async def test_refresh_returns_entities_and_stats(self) -> None:
        graph = FakeKnowledgeGraph()
        await graph.add_entity(entity=_ENTITY_A)
        agent = self._make_agent(graph=graph)
        ctx = _make_context()
        goal = KnowledgeGraphGoal(operation="refresh", query="Research")

        result = await agent.run(goal=goal, context=ctx)

        assert result.success
        assert result.output.stats["refreshed"] is True
        assert result.output.stats["entity_count"] == 1

    @pytest.mark.asyncio
    async def test_unknown_operation_fails(self) -> None:
        agent = self._make_agent()
        ctx = _make_context()
        goal = KnowledgeGraphGoal(operation="destroy")

        result = await agent.run(goal=goal, context=ctx)

        assert not result.success
        assert "destroy" in result.error.lower()
