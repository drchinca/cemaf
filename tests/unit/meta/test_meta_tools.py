"""Unit tests for meta-tools — introspection, DAG gen, trace analysis, knowledge graph."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel

from cemaf.audit.models import AuditEntry, AuditEntryType
from cemaf.core.result import Result
from cemaf.knowledge.models import (
    EntityType,
    KGEntity,
    KGQueryResult,
    KGRelation,
    RelationType,
)
from cemaf.meta.tools import (
    GenerateDAGTool,
    IntrospectRegistryTool,
    KnowledgeGraphTool,
    TraceAnalyzerTool,
)
from cemaf.tools.base import Tool, ToolSchema

# ---------------------------------------------------------------------------
# Fakes
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
_RELATION_AB = KGRelation(
    source_id="ent-1",
    target_id="ent-2",
    type=RelationType.USES,
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
            if query.lower() in ent.name.lower():
                results.append(ent)
        return tuple(results[:limit])

    async def remove_entity(self, entity_id: str) -> bool:
        if entity_id in self._entities:
            del self._entities[entity_id]
            return True
        return False


# ---------------------------------------------------------------------------
# IntrospectRegistryTool
# ---------------------------------------------------------------------------


class TestIntrospectRegistryTool:
    def _make_tool(
        self,
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

    def test_is_tool_instance(self) -> None:
        tool = self._make_tool()
        assert isinstance(tool, Tool)

    def test_id(self) -> None:
        tool = self._make_tool()
        assert tool.id == "meta_introspect_registry"

    def test_schema_name_and_params(self) -> None:
        tool = self._make_tool()
        assert tool.schema.name == "meta_introspect_registry"
        assert "registry_type" in tool.schema.parameters["properties"]

    @pytest.mark.asyncio
    async def test_execute_agents_only(self) -> None:
        ar = FakeAgentRegistry()
        ar.register(agent=_FakeAgent(agent_id="alpha"), goal_type=_FakeGoal)
        tool = self._make_tool(agent_registry=ar)

        result = await tool.execute(registry_type="agents")

        assert result.success
        assert "agents" in result.data
        assert len(result.data["agents"]) == 1
        assert result.data["agents"][0]["id"] == "alpha"
        assert "tools" not in result.data

    @pytest.mark.asyncio
    async def test_execute_tools_only(self) -> None:
        tr = FakeToolRegistry()
        tr.register(tool=_FakeTool(name="web_search"))
        tool = self._make_tool(tool_registry=tr)

        result = await tool.execute(registry_type="tools")

        assert result.success
        assert "tools" in result.data
        assert len(result.data["tools"]) == 1
        assert result.data["tools"][0]["name"] == "web_search"
        assert "agents" not in result.data

    @pytest.mark.asyncio
    async def test_execute_both(self) -> None:
        ar = FakeAgentRegistry()
        ar.register(agent=_FakeAgent(agent_id="beta"))
        tr = FakeToolRegistry()
        tr.register(tool=_FakeTool(name="calc"))
        tool = self._make_tool(agent_registry=ar, tool_registry=tr)

        result = await tool.execute(registry_type="both")

        assert result.success
        assert "agents" in result.data
        assert "tools" in result.data

    @pytest.mark.asyncio
    async def test_query_filter_agents(self) -> None:
        ar = FakeAgentRegistry()
        ar.register(agent=_FakeAgent(agent_id="ResearchBot"))
        ar.register(agent=_FakeAgent(agent_id="WriterBot"))
        tool = self._make_tool(agent_registry=ar)

        result = await tool.execute(registry_type="agents", query="research")

        assert result.success
        assert len(result.data["agents"]) == 1
        assert result.data["agents"][0]["id"] == "ResearchBot"

    @pytest.mark.asyncio
    async def test_query_filter_tools(self) -> None:
        tr = FakeToolRegistry()
        tr.register(tool=_FakeTool(name="web_search"))
        tr.register(tool=_FakeTool(name="calculator"))
        tool = self._make_tool(tool_registry=tr)

        result = await tool.execute(registry_type="tools", query="calc")

        assert result.success
        assert len(result.data["tools"]) == 1
        assert result.data["tools"][0]["name"] == "calculator"

    def test_safety_flags_read_only_and_concurrent_safe(self) -> None:
        """IntrospectRegistryTool is read-only and concurrent-safe."""
        tool = self._make_tool()
        assert tool.is_read_only is True
        assert tool.is_concurrent_safe is True
        assert tool.is_destructive is False

    @pytest.mark.asyncio
    async def test_tool_entries_include_safety_metadata(self) -> None:
        """Introspection results include safety flags per tool."""
        tr = FakeToolRegistry()
        tr.register(tool=_FakeTool(name="search"))
        tool = self._make_tool(tool_registry=tr)

        result = await tool.execute(registry_type="tools")

        assert result.success
        tool_entry = result.data["tools"][0]
        assert "safety" in tool_entry
        assert "is_concurrent_safe" in tool_entry["safety"]
        assert "is_read_only" in tool_entry["safety"]
        assert "is_destructive" in tool_entry["safety"]


# ---------------------------------------------------------------------------
# GenerateDAGTool
# ---------------------------------------------------------------------------


class TestGenerateDAGTool:
    def _make_tool(self) -> GenerateDAGTool:
        return GenerateDAGTool()

    def test_is_tool_instance(self) -> None:
        assert isinstance(self._make_tool(), Tool)

    def test_id(self) -> None:
        assert self._make_tool().id == "meta_generate_dag"

    @pytest.mark.asyncio
    async def test_execute_valid_dag(self) -> None:
        tool = self._make_tool()
        result = await tool.execute(
            name="test_pipeline",
            description="A test pipeline",
            nodes=[
                {
                    "id": "n1",
                    "type": "agent",
                    "name": "Researcher",
                    "ref_id": "researcher",
                    "output_key": "research",
                },
                {
                    "id": "n2",
                    "type": "tool",
                    "name": "Summarize",
                    "ref_id": "summarizer",
                    "output_key": "summary",
                },
            ],
            edges=[
                {"source": "n1", "target": "n2"},
            ],
        )

        assert result.success
        dag_dict = result.data
        assert dag_dict["name"] == "test_pipeline"
        assert len(dag_dict["nodes"]) == 2
        assert len(dag_dict["edges"]) == 1

    @pytest.mark.asyncio
    async def test_execute_cyclic_dag_fails(self) -> None:
        tool = self._make_tool()
        result = await tool.execute(
            name="cyclic",
            nodes=[
                {"id": "a", "type": "tool", "name": "A", "ref_id": "t1"},
                {"id": "b", "type": "tool", "name": "B", "ref_id": "t2"},
            ],
            edges=[
                {"source": "a", "target": "b"},
                {"source": "b", "target": "a"},
            ],
        )

        assert not result.success
        assert "Cycle" in result.error

    @pytest.mark.asyncio
    async def test_execute_missing_name_fails(self) -> None:
        tool = self._make_tool()
        result = await tool.execute(
            name="",
            nodes=[{"id": "a", "type": "tool", "name": "A", "ref_id": "t1"}],
            edges=[],
        )

        assert not result.success
        assert "name" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_missing_node_fields_fails(self) -> None:
        tool = self._make_tool()
        result = await tool.execute(
            name="bad",
            nodes=[{"id": "a", "type": "tool", "name": "", "ref_id": "t1"}],
            edges=[],
        )

        assert not result.success
        assert "missing" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_unknown_node_type_fails(self) -> None:
        tool = self._make_tool()
        result = await tool.execute(
            name="bad_type",
            nodes=[{"id": "a", "type": "magic", "name": "Magic", "ref_id": "m1"}],
            edges=[],
        )

        assert not result.success
        assert "magic" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_no_nodes_fails(self) -> None:
        tool = self._make_tool()
        result = await tool.execute(name="empty", nodes=[], edges=[])

        assert not result.success

    def test_safety_flags_concurrent_safe(self) -> None:
        """GenerateDAGTool is concurrent-safe (stateless, no side effects)."""
        tool = self._make_tool()
        assert tool.is_concurrent_safe is True
        assert tool.is_read_only is False
        assert tool.is_destructive is False


# ---------------------------------------------------------------------------
# TraceAnalyzerTool
# ---------------------------------------------------------------------------


class TestTraceAnalyzerTool:
    def _make_tool(self, **kwargs: Any) -> TraceAnalyzerTool:
        trail = FakeAuditTrail(**kwargs)
        return TraceAnalyzerTool(audit_trail=trail)  # type: ignore[arg-type]

    def test_is_tool_instance(self) -> None:
        assert isinstance(self._make_tool(), Tool)

    def test_id(self) -> None:
        assert self._make_tool().id == "meta_trace_analyzer"

    @pytest.mark.asyncio
    async def test_timeline(self) -> None:
        entry = _make_entry(entry_id="t1", run_id="run-abc")
        tool = self._make_tool(timeline=(entry,))

        result = await tool.execute(analysis_type="timeline", run_id="run-abc")

        assert result.success
        assert len(result.data) == 1
        assert result.data[0]["id"] == "t1"

    @pytest.mark.asyncio
    async def test_timeline_requires_run_id(self) -> None:
        tool = self._make_tool()
        result = await tool.execute(analysis_type="timeline")

        assert not result.success
        assert "run_id" in result.error.lower()

    @pytest.mark.asyncio
    async def test_quality_trend(self) -> None:
        tool = self._make_tool(trend=(0.9, 0.85, 0.92))
        result = await tool.execute(analysis_type="quality_trend", window=10)

        assert result.success
        assert result.data["trend"] == [0.9, 0.85, 0.92]
        assert result.data["window"] == 10

    @pytest.mark.asyncio
    async def test_anomalies(self) -> None:
        entry = _make_entry(entry_id="anomaly-1")
        tool = self._make_tool(anomalies=(entry,))

        result = await tool.execute(analysis_type="anomalies", threshold=1.5)

        assert result.success
        assert len(result.data["anomalies"]) == 1
        assert result.data["threshold"] == 1.5

    @pytest.mark.asyncio
    async def test_unknown_analysis_type_fails(self) -> None:
        tool = self._make_tool()
        result = await tool.execute(analysis_type="unknown")

        assert not result.success
        assert "unknown" in result.error.lower()

    def test_safety_flags_read_only_and_concurrent_safe(self) -> None:
        """TraceAnalyzerTool is read-only and concurrent-safe."""
        tool = self._make_tool()
        assert tool.is_read_only is True
        assert tool.is_concurrent_safe is True
        assert tool.is_destructive is False


# ---------------------------------------------------------------------------
# KnowledgeGraphTool
# ---------------------------------------------------------------------------


class TestKnowledgeGraphTool:
    def _make_tool(self, *, graph: FakeKnowledgeGraph | None = None) -> KnowledgeGraphTool:
        kg = graph or FakeKnowledgeGraph()
        return KnowledgeGraphTool(knowledge_graph=kg)  # type: ignore[arg-type]

    def test_is_tool_instance(self) -> None:
        assert isinstance(self._make_tool(), Tool)

    def test_id(self) -> None:
        assert self._make_tool().id == "meta_knowledge_graph"

    @pytest.mark.asyncio
    async def test_add_entity(self) -> None:
        graph = FakeKnowledgeGraph()
        tool = self._make_tool(graph=graph)

        result = await tool.execute(
            operation="add_entity",
            entity={
                "id": "ent-new",
                "type": "agent",
                "name": "New Agent",
                "description": "Brand new",
            },
        )

        assert result.success
        assert result.data["id"] == "ent-new"
        assert result.data["type"] == "agent"
        assert graph._entities["ent-new"].name == "New Agent"

    @pytest.mark.asyncio
    async def test_add_entity_invalid_type_fails(self) -> None:
        tool = self._make_tool()
        result = await tool.execute(
            operation="add_entity",
            entity={"id": "e1", "type": "invalid_type", "name": "Bad"},
        )

        assert not result.success
        assert "invalid_type" in result.error.lower()

    @pytest.mark.asyncio
    async def test_add_entity_missing_fields_fails(self) -> None:
        tool = self._make_tool()
        result = await tool.execute(
            operation="add_entity",
            entity={"id": "e1"},
        )

        assert not result.success
        assert "requires" in result.error.lower()

    @pytest.mark.asyncio
    async def test_add_relation(self) -> None:
        graph = FakeKnowledgeGraph()
        tool = self._make_tool(graph=graph)

        result = await tool.execute(
            operation="add_relation",
            relation={
                "source_id": "ent-1",
                "target_id": "ent-2",
                "type": "uses",
            },
        )

        assert result.success
        assert result.data["source_id"] == "ent-1"
        assert len(graph._relations) == 1

    @pytest.mark.asyncio
    async def test_get_entity_found(self) -> None:
        graph = FakeKnowledgeGraph()
        await graph.add_entity(entity=_ENTITY_A)
        tool = self._make_tool(graph=graph)

        result = await tool.execute(operation="get_entity", entity_id="ent-1")

        assert result.success
        assert result.data["name"] == "Research Agent"
        assert result.metadata["found"] is True

    @pytest.mark.asyncio
    async def test_get_entity_not_found(self) -> None:
        tool = self._make_tool()
        result = await tool.execute(operation="get_entity", entity_id="nonexistent")

        assert result.success
        assert result.data is None
        assert result.metadata["found"] is False

    @pytest.mark.asyncio
    async def test_search(self) -> None:
        graph = FakeKnowledgeGraph()
        await graph.add_entity(entity=_ENTITY_A)
        await graph.add_entity(entity=_ENTITY_B)
        tool = self._make_tool(graph=graph)

        result = await tool.execute(operation="search", query="Research")

        assert result.success
        assert len(result.data) == 1
        assert result.data[0]["name"] == "Research Agent"

    @pytest.mark.asyncio
    async def test_search_with_entity_type_filter(self) -> None:
        graph = FakeKnowledgeGraph()
        await graph.add_entity(entity=_ENTITY_A)
        await graph.add_entity(entity=_ENTITY_B)
        tool = self._make_tool(graph=graph)

        result = await tool.execute(operation="search", query="Search", entity_type="tool")

        assert result.success
        assert len(result.data) == 1
        assert result.data[0]["type"] == "tool"

    @pytest.mark.asyncio
    async def test_query_neighbors(self) -> None:
        graph = FakeKnowledgeGraph()
        await graph.add_entity(entity=_ENTITY_A)
        await graph.add_entity(entity=_ENTITY_B)
        await graph.add_relation(relation=_RELATION_AB)
        tool = self._make_tool(graph=graph)

        result = await tool.execute(operation="query_neighbors", entity_id="ent-1")

        assert result.success
        assert len(result.data["entities"]) == 1
        assert result.data["entities"][0]["id"] == "ent-2"
        assert len(result.data["relations"]) == 1

    @pytest.mark.asyncio
    async def test_remove_entity(self) -> None:
        graph = FakeKnowledgeGraph()
        await graph.add_entity(entity=_ENTITY_A)
        tool = self._make_tool(graph=graph)

        result = await tool.execute(operation="remove_entity", entity_id="ent-1")

        assert result.success
        assert result.data["removed"] is True
        assert "ent-1" not in graph._entities

    @pytest.mark.asyncio
    async def test_remove_nonexistent_entity(self) -> None:
        tool = self._make_tool()
        result = await tool.execute(operation="remove_entity", entity_id="ghost")

        assert result.success
        assert result.data["removed"] is False

    @pytest.mark.asyncio
    async def test_unknown_operation_fails(self) -> None:
        tool = self._make_tool()
        result = await tool.execute(operation="destroy_all")

        assert not result.success
        assert "destroy_all" in result.error.lower()

    @pytest.mark.asyncio
    async def test_get_entity_missing_id_fails(self) -> None:
        tool = self._make_tool()
        result = await tool.execute(operation="get_entity")

        assert not result.success
        assert "entity_id" in result.error.lower()

    def test_safety_flags_destructive(self) -> None:
        """KnowledgeGraphTool is destructive (remove_entity)."""
        tool = self._make_tool()
        assert tool.is_destructive is True
        assert tool.is_read_only is False
        assert tool.is_concurrent_safe is False
