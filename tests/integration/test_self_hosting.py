"""Integration test proving CEMAF can use itself to audit itself."""

from __future__ import annotations

from datetime import timedelta

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
from cemaf.meta.agents import DreamAgent
from cemaf.meta.bootstrap import MetaServices, create_meta_executor
from cemaf.meta.dags import create_dream_dag, create_self_audit_dag
from cemaf.meta.goals import DreamGoal
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices
from cemaf.scheduler.gates import LockGate, SessionCountGate, TimeGate
from cemaf.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Fake MemoryManager (same pattern as knowledge/test_graph.py)
# ---------------------------------------------------------------------------


class FakeMemoryManager:
    """In-memory MemoryManager for integration testing."""

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
        """Store item keyed by scope:key."""
        item = MemoryItem(
            scope=scope,
            key=key,
            value=value,
            confidence=Confidence(confidence),
        )
        self._store[f"{scope.value}:{key}"] = item
        return item

    async def recall(self, query: MemoryQuery) -> tuple[MemorySearchResult, ...]:
        """Simple text search across stored items."""
        results: list[MemorySearchResult] = []
        search_text = (query.text or "").lower()
        for item in self._store.values():
            if query.scope is not None and item.scope != query.scope:
                continue
            text_repr = f"{item.key} {str(item.value)}".lower()
            if search_text and search_text not in text_repr:
                continue
            results.append(
                MemorySearchResult(
                    item=item,
                    similarity=0.9,
                    combined_score=0.9,
                    rank=len(results),
                )
            )
            if len(results) >= query.limit:
                break
        return tuple(results)

    async def recall_by_key(self, scope: MemoryScope, key: str) -> MemoryItem | None:
        """Direct key lookup."""
        return self._store.get(f"{scope.value}:{key}")

    async def forget(self, scope: MemoryScope, key: str) -> bool:
        """Remove an item."""
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

    async def get_recent_history(
        self,
        session_id: str,
        *,
        limit: int = 20,
    ) -> tuple[EpisodicEvent, ...]:
        raise NotImplementedError

    async def cleanup(self) -> int:
        return 0


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_audit_loop() -> None:
    """CEMAF audits its own execution using its own agent framework."""
    # 1. Create infrastructure
    event_bus = InMemoryEventBus()
    memory_manager = FakeMemoryManager()

    # 2. Create audit + KG
    audit_log, audit_trail = create_audit_system(event_bus=event_bus)
    kg = create_knowledge_graph(memory_manager=memory_manager)  # type: ignore[arg-type]

    # 3. Seed events (simulate prior execution with scores for quality trend)
    for i in range(5):
        await event_bus.publish(
            event=Event.create(
                type=EventType.EVAL_COMPLETED,
                payload={"run_id": "prior_run", "score": 0.8 + i * 0.02, "output": "test"},
                source="test",
                correlation_id="prior_run",
            )
        )

    # 4. Create meta-executor
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

    _executor = create_meta_executor(
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        config=ExecutorConfig(enable_events=False),
        services=services,
        meta_services=meta_services,
    )

    # 5. Verify meta-agents were registered
    assert agent_registry.get("MetaAuditor") is not None
    assert agent_registry.get("MetaArchitect") is not None
    assert agent_registry.get("MetaSynthesizer") is not None
    assert agent_registry.get("MetaKnowledgeGraph") is not None

    # 6. Verify meta-tools were registered
    assert tool_registry.get("meta_introspect_registry") is not None
    assert tool_registry.get("meta_generate_dag") is not None
    assert tool_registry.get("meta_trace_analyzer") is not None
    assert tool_registry.get("meta_knowledge_graph") is not None

    # 7. Verify audit log captured events
    count = await audit_log.count()
    assert count >= 5

    # 8. Verify quality trend is available from audit trail
    trend = await audit_trail.get_quality_trend(window=10)
    assert len(trend) == 5
    assert all(0.7 < score < 1.0 for score in trend)

    # 9. Verify the self-audit DAG is structurally valid AND actually runs
    # (regression: previously this test only called validate_structure without
    # ever invoking executor.run, so a broken executor would pass silently)
    dag = create_self_audit_dag()
    assert dag.validate_structure() is True
    assert dag.nodes[0].ref_id == "MetaAuditor"
    run_result = await _executor.run(dag=dag)
    assert run_result is not None
    assert len(run_result.node_results) >= 1, "self_audit DAG must execute the MetaAuditor node"


@pytest.mark.asyncio
async def test_meta_executor_graceful_degradation() -> None:
    """Without event_bus/memory_manager, still returns a valid executor."""
    agent_registry = AgentRegistry()
    _executor = create_meta_executor(agent_registry=agent_registry)
    assert _executor is not None
    # No meta-agents registered (no services to build them)
    assert agent_registry.get("MetaAuditor") is None


@pytest.mark.asyncio
async def test_audit_to_knowledge_graph_wiring() -> None:
    """Audit system events flow through to knowledge graph dependencies."""
    event_bus = InMemoryEventBus()
    memory_manager = FakeMemoryManager()

    audit_log, audit_trail = create_audit_system(event_bus=event_bus)
    kg = create_knowledge_graph(memory_manager=memory_manager)  # type: ignore[arg-type]

    agent_registry = AgentRegistry()
    tool_registry = ToolRegistry()
    meta_services = MetaServices(
        audit_log=audit_log,
        audit_trail=audit_trail,
        knowledge_graph=kg,
    )
    services = RuntimeServices(event_bus=event_bus, memory_manager=memory_manager)  # type: ignore[arg-type]

    create_meta_executor(
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        services=services,
        meta_services=meta_services,
    )

    # Publish events AFTER meta-executor creation
    await event_bus.publish(
        event=Event.create(
            type=EventType.EVAL_COMPLETED,
            payload={"run_id": "new_run", "score": 0.95, "output": "result"},
            source="integration_test",
            correlation_id="new_run",
        )
    )

    # Audit log captured the new event
    count = await audit_log.count()
    assert count >= 1

    # The MetaAuditor agent can use the trace analyzer to read these
    auditor = agent_registry.get("MetaAuditor")
    assert auditor is not None

    # The KG agent can manage knowledge
    kg_agent = agent_registry.get("MetaKnowledgeGraph")
    assert kg_agent is not None

    # Verify the tools are wired to the same underlying services
    trace_tool = tool_registry.get("meta_trace_analyzer")
    assert trace_tool is not None
    result = await trace_tool.execute(analysis_type="quality_trend", window=10)
    assert result.success is True
    assert len(result.data["trend"]) >= 1


# ---------------------------------------------------------------------------
# DreamAgent integration — gates + memory wired together
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dream_agent_three_gate_trigger() -> None:
    """DreamAgent with three-gate system: time + session + lock."""
    mm = FakeMemoryManager()
    await mm.remember(
        scope=MemoryScope.PROJECT,
        key="fact1",
        value={"data": "important context"},
    )
    await mm.remember(
        scope=MemoryScope.PROJECT,
        key="fact2",
        value={"data": "another signal"},
    )

    # All gates pass
    gates = (
        TimeGate(min_interval=timedelta(hours=24)),  # never run = pass
        SessionCountGate(min_sessions=3, current_count=5),  # pass
        LockGate(),  # not locked = pass
    )
    agent = DreamAgent(memory_manager=mm, gates=gates)  # type: ignore[arg-type]
    ctx = AgentContext(run_id="dream-integration", agent_id="MetaDream")
    goal = DreamGoal()

    result = await agent.run(goal=goal, context=ctx)

    assert result.success
    assert result.output.consolidated_count == 2
    assert "Dream complete" in result.output.summary


@pytest.mark.asyncio
async def test_dream_agent_blocked_by_session_gate() -> None:
    """DreamAgent defers when session count gate fails."""
    mm = FakeMemoryManager()
    await mm.remember(scope=MemoryScope.PROJECT, key="fact1", value={"data": "x"})

    gates = (
        SessionCountGate(min_sessions=10, current_count=2),  # fail
    )
    agent = DreamAgent(memory_manager=mm, gates=gates)  # type: ignore[arg-type]
    ctx = AgentContext(run_id="dream-blocked", agent_id="MetaDream")
    goal = DreamGoal()

    result = await agent.run(goal=goal, context=ctx)

    assert result.success
    assert result.output.consolidated_count == 0
    assert "gate" in result.output.summary.lower()


@pytest.mark.asyncio
async def test_dream_dag_valid_structure() -> None:
    """Dream DAG is structurally valid and references MetaDream."""
    dag = create_dream_dag()
    assert dag.validate_structure() is True
    assert dag.nodes[0].ref_id == "MetaDream"
    assert dag.nodes[0].output_key == "dream_result"
