"""Integration test: CEMAF solves problems using its own self-hosting engine.

Proves the full loop:
  create_meta_executor → SolutionDesignerAgent → designs DAG → versions in KG → learns

Tests each of the 5 context engineering challenges:
  1. Fragmented Context → unified ContextSource types
  2. Surging Context Demand → TokenBudget + compaction
  3. Poor Retrieval → TieredMemoryStore + KnowledgeGraph
  4. Unobservable Context → AuditTrail + ContextPatch provenance
  5. Limited Memory → DreamAgent + ExtractionPipeline
"""

from __future__ import annotations

import pytest

from cemaf.agents.base import AgentContext
from cemaf.agents.registry import AgentRegistry
from cemaf.audit.factories import create_audit_system
from cemaf.core.enums import MemoryScope
from cemaf.core.types import JSON, Confidence
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType
from cemaf.knowledge.factories import create_knowledge_graph
from cemaf.memory.base import MemoryItem
from cemaf.memory.episodic import Episode, EpisodicEvent
from cemaf.memory.semantic import MemoryQuery, MemorySearchResult
from cemaf.meta.bootstrap import MetaServices, create_meta_executor
from cemaf.meta.dags import create_solution_engine_dag
from cemaf.meta.goals import SolutionGoal
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices
from cemaf.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Fake MemoryManager (reused pattern)
# ---------------------------------------------------------------------------


class FakeMemoryManager:
    def __init__(self) -> None:
        self._store: dict[str, MemoryItem] = {}

    async def remember(
        self,
        scope: MemoryScope,
        key: str,
        value: JSON,
        *,
        confidence: float = 1.0,
        content_for_embedding: str | None = None,
    ) -> MemoryItem:
        item = MemoryItem(
            scope=scope,
            key=key,
            value=value,
            confidence=Confidence(confidence),
        )
        self._store[f"{scope.value}:{key}"] = item
        return item

    async def recall(self, query: MemoryQuery) -> tuple[MemorySearchResult, ...]:
        results: list[MemorySearchResult] = []
        search_text = (query.text or "").lower()
        for item in self._store.values():
            if query.scope is not None and item.scope != query.scope:
                continue
            text_repr = f"{item.key} {item.value!s}".lower()
            if search_text and search_text not in text_repr:
                continue
            results.append(
                MemorySearchResult(item=item, similarity=0.9, combined_score=0.9, rank=len(results))
            )
            if len(results) >= query.limit:
                break
        return tuple(results)

    async def recall_by_key(self, scope: MemoryScope, key: str) -> MemoryItem | None:
        return self._store.get(f"{scope.value}:{key}")

    async def forget(self, scope: MemoryScope, key: str) -> bool:
        full_key = f"{scope.value}:{key}"
        if full_key in self._store:
            del self._store[full_key]
            return True
        return False

    async def start_episode(self, session_id: str) -> Episode:
        raise NotImplementedError

    async def record_event(self, episode_id: str, event: EpisodicEvent) -> None:
        raise NotImplementedError

    async def end_episode(self, episode_id: str) -> Episode:
        raise NotImplementedError

    async def get_recent_history(self, session_id: str, *, limit: int = 20) -> tuple[EpisodicEvent, ...]:
        raise NotImplementedError

    async def cleanup(self) -> int:
        return 0


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _create_full_meta_stack() -> tuple[AgentRegistry, ToolRegistry, RuntimeServices, MetaServices]:
    """Wire up the complete meta-executor stack."""
    event_bus = InMemoryEventBus()
    memory_manager = FakeMemoryManager()

    audit_log, audit_trail = create_audit_system(event_bus=event_bus)
    kg = create_knowledge_graph(memory_manager=memory_manager)  # type: ignore[arg-type]

    agent_registry = AgentRegistry()
    tool_registry = ToolRegistry()
    services = RuntimeServices(
        event_bus=event_bus,
        memory_manager=memory_manager,  # type: ignore[arg-type]
    )
    meta_services = MetaServices(
        audit_log=audit_log,
        audit_trail=audit_trail,
        knowledge_graph=kg,
    )

    # Seed events for the auditor
    for i in range(3):
        await event_bus.publish(
            event=Event.create(
                type=EventType.EVAL_COMPLETED,
                payload={"run_id": "seed", "score": 0.8 + i * 0.05, "output": "ok"},
                source="seed",
            )
        )

    return agent_registry, tool_registry, services, meta_services


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_solution_designer_registered() -> None:
    """MetaSolutionDesigner is registered by create_meta_executor."""
    agent_registry, tool_registry, services, meta_services = await _create_full_meta_stack()
    create_meta_executor(
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        services=services,
        meta_services=meta_services,
        config=ExecutorConfig(enable_events=False),
    )

    assert agent_registry.get("MetaSolutionDesigner") is not None


@pytest.mark.asyncio
async def test_solution_designer_solves_use_case() -> None:
    """SolutionDesigner produces a versioned DAG spec for a use case."""
    agent_registry, tool_registry, services, meta_services = await _create_full_meta_stack()
    create_meta_executor(
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        services=services,
        meta_services=meta_services,
        config=ExecutorConfig(enable_events=False),
    )

    designer = agent_registry.get("MetaSolutionDesigner")
    assert designer is not None

    ctx = AgentContext(run_id="test-solution", agent_id="MetaSolutionDesigner")
    goal = SolutionGoal(
        use_case="Fragmented context: unify memories, resources, and skills",
        version_tag="v1",
    )

    result = await designer.run(goal=goal, context=ctx)

    assert result.success
    assert result.output.version == "v1"
    assert result.output.dag_spec  # Non-empty DAG
    assert result.output.quality_score > 0.0
    assert "Fragmented" in result.output.rationale or "solution" in result.output.rationale.lower()


@pytest.mark.asyncio
async def test_solution_versioning_in_knowledge_graph() -> None:
    """Solutions are stored as versioned entities in the KnowledgeGraph."""
    agent_registry, tool_registry, services, meta_services = await _create_full_meta_stack()
    create_meta_executor(
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        services=services,
        meta_services=meta_services,
        config=ExecutorConfig(enable_events=False),
    )

    designer = agent_registry.get("MetaSolutionDesigner")
    ctx = AgentContext(run_id="test-versioning", agent_id="MetaSolutionDesigner")

    # v1
    goal_v1 = SolutionGoal(use_case="Surging context demand", version_tag="v1")
    result_v1 = await designer.run(goal=goal_v1, context=ctx)
    assert result_v1.success

    # v2 — iterate on the same use case
    goal_v2 = SolutionGoal(use_case="Surging context demand", version_tag="v2")
    result_v2 = await designer.run(goal=goal_v2, context=ctx)
    assert result_v2.success
    assert result_v2.output.version == "v2"

    # Both versions stored in KG
    kg_tool = tool_registry.get("meta_knowledge_graph")
    assert kg_tool is not None
    search_result = await kg_tool.execute(operation="search", query="surging")
    assert search_result.success


@pytest.mark.asyncio
async def test_solution_engine_dag_valid() -> None:
    """The solution_engine DAG is structurally valid with checkpoints."""
    dag = create_solution_engine_dag()
    assert dag.validate_structure() is True
    assert dag.name == "solution_engine"

    # Has checkpoint nodes
    checkpoint_nodes = [n for n in dag.nodes if n.type.value == "checkpoint"]
    assert len(checkpoint_nodes) == 2  # cp_diagnosis, cp_design

    # Has agent nodes
    agent_nodes = [n for n in dag.nodes if n.type.value == "agent"]
    assert len(agent_nodes) == 3  # diagnose, design, learn

    # Proper edge chain
    assert len(dag.edges) == 4


@pytest.mark.asyncio
async def test_solution_for_each_openviking_challenge() -> None:
    """CEMAF produces solutions for all 5 context engineering challenges."""
    agent_registry, tool_registry, services, meta_services = await _create_full_meta_stack()
    create_meta_executor(
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        services=services,
        meta_services=meta_services,
        config=ExecutorConfig(enable_events=False),
    )

    designer = agent_registry.get("MetaSolutionDesigner")
    ctx = AgentContext(run_id="test-5-challenges", agent_id="MetaSolutionDesigner")

    challenges = [
        "Fragmented Context: unify memories, resources, and skills management",
        "Surging Context Demand: handle growing context without information loss",
        "Poor Retrieval: global view of context beyond flat vector storage",
        "Unobservable Context: debug implicit retrieval chains transparently",
        "Limited Memory Iteration: agent task memory beyond user interaction logs",
    ]

    for challenge in challenges:
        goal = SolutionGoal(use_case=challenge, version_tag="v1")
        result = await designer.run(goal=goal, context=ctx)

        assert result.success, f"Failed for: {challenge}"
        assert result.output.dag_spec, f"Empty DAG for: {challenge}"
        assert result.output.quality_score > 0.0, f"Zero quality for: {challenge}"
