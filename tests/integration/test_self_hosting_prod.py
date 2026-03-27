"""Production integration tests for CEMAF self-hosting engine.

These tests exercise the full execution path: create_meta_executor →
DAGExecutor.run(dag) → agent resolution → tool execution → context
propagation. They prove CEMAF can use itself in production scenarios.
"""

from __future__ import annotations

import ast
import json

import pytest

from cemaf.agents.base import AgentContext
from cemaf.agents.registry import AgentRegistry
from cemaf.audit.factories import create_audit_system
from cemaf.context.context import Context
from cemaf.core.enums import MemoryScope
from cemaf.core.types import JSON, Confidence, NodeID
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType
from cemaf.knowledge.factories import create_knowledge_graph
from cemaf.memory.base import MemoryItem
from cemaf.memory.episodic import Episode, EpisodicEvent
from cemaf.memory.semantic import MemoryQuery, MemorySearchResult
from cemaf.meta.bootstrap import MetaServices, create_meta_executor
from cemaf.meta.dags import (
    create_knowledge_refresh_dag,
    create_self_audit_dag,
)
from cemaf.meta.goals import (
    ArchitectGoal,
)
from cemaf.orchestration.dag import DAG, Edge, Node
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices
from cemaf.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Shared test infrastructure
# ---------------------------------------------------------------------------


class FakeMemoryManager:
    """In-memory MemoryManager for production integration testing."""

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

    async def get_recent_history(
        self,
        session_id: str,
        *,
        limit: int = 20,
    ) -> tuple[EpisodicEvent, ...]:
        raise NotImplementedError

    async def cleanup(self) -> int:
        return 0


def _create_test_infra(
    *,
    seed_events: int = 0,
    seed_score_base: float = 0.8,
    seed_score_step: float = 0.02,
) -> tuple[
    InMemoryEventBus,
    FakeMemoryManager,
    AgentRegistry,
    ToolRegistry,
    MetaServices,
    RuntimeServices,
]:
    """Create fully-wired test infrastructure."""
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
    services = RuntimeServices(
        event_bus=event_bus,
        memory_manager=memory_manager,  # type: ignore[arg-type]
    )

    return event_bus, memory_manager, agent_registry, tool_registry, meta_services, services


async def _seed_events(
    event_bus: InMemoryEventBus,
    *,
    count: int = 5,
    score_base: float = 0.8,
    score_step: float = 0.02,
    run_id: str = "prior_run",
) -> None:
    """Seed execution events to simulate prior runs."""
    for i in range(count):
        await event_bus.publish(
            event=Event.create(
                type=EventType.EVAL_COMPLETED,
                payload={
                    "run_id": run_id,
                    "score": score_base + i * score_step,
                    "output": f"test_output_{i}",
                },
                source="test_harness",
                correlation_id=run_id,
            )
        )


# ---------------------------------------------------------------------------
# Use Case 1: Self-Audit Loop (end-to-end DAG execution)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_audit_dag_execution() -> None:
    """DAGExecutor runs self_audit_dag, MetaAuditor executes, output in context."""
    event_bus, _mm, agent_registry, tool_registry, meta_services, services = _create_test_infra()

    # Seed 10 execution events
    await _seed_events(event_bus, count=10, score_base=0.75, score_step=0.02)

    # Create meta-executor with events enabled so DAG events also flow
    executor = create_meta_executor(
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        config=ExecutorConfig(enable_events=False),
        services=services,
        meta_services=meta_services,
    )

    # Run the self-audit DAG
    dag = create_self_audit_dag()
    result = await executor.run(dag=dag, initial_context=Context())

    # Verify execution succeeded
    assert result.success, f"Self-audit DAG failed: {result.error}"
    assert result.status.value == "completed"

    # Verify the audit node executed
    assert len(result.node_results) == 1
    audit_node_result = result.node_results[0]
    assert audit_node_result.success is True
    assert str(audit_node_result.node_id) == "audit"

    # Verify output contains audit report data
    output = audit_node_result.output
    assert output is not None
    report_data = json.loads(output)
    assert "report" in report_data
    assert "summary" in report_data

    # Verify the report captured quality trend data
    report = report_data["report"]
    assert "quality_trend" in report

    # Verify output landed in final context
    audit_report = result.final_context.get("audit_report")
    assert audit_report is not None


# ---------------------------------------------------------------------------
# Use Case 2: Feature Synthesis Pipeline (agent chaining)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_feature_synthesis_agent_chaining() -> None:
    """ArchitectAgent output flows to AgentSynthesizer through context."""
    event_bus, _mm, agent_registry, tool_registry, meta_services, services = _create_test_infra()
    await _seed_events(event_bus, count=3)

    executor = create_meta_executor(
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        config=ExecutorConfig(enable_events=False),
        services=services,
        meta_services=meta_services,
    )

    # Build a custom DAG with input_mapping for required goal fields
    dag = DAG(name="feature_synthesis_test", description="Test agent chaining")
    dag = dag.add_node(
        node=Node.agent(
            id="architect",
            name="Architect",
            agent_id="MetaArchitect",
            input_mapping={"feature_description": "Build an audit pipeline"},
            output_key="dag_spec",
        )
    )
    dag = dag.add_node(
        node=Node.agent(
            id="synthesize",
            name="Synthesizer",
            agent_id="MetaSynthesizer",
            input_mapping={
                "agent_name": "AuditPipelineAgent",
                "description": "An agent that runs audit pipelines",
                "goal_fields": {},
                "result_fields": {},
            },
            output_key="agent_code",
        )
    )
    dag = dag.add_edge(edge=Edge(source=NodeID("architect"), target=NodeID("synthesize")))

    result = await executor.run(dag=dag, initial_context=Context())

    # Both nodes should succeed
    assert result.success, f"Feature synthesis DAG failed: {result.error}"
    assert len(result.node_results) == 2

    # Architect produced a DAG spec
    architect_result = result.node_results[0]
    assert architect_result.success is True
    architect_output = json.loads(architect_result.output)
    assert "dag_spec" in architect_output
    assert "rationale" in architect_output

    # Synthesizer produced Python code
    synth_result = result.node_results[1]
    assert synth_result.success is True
    synth_output = json.loads(synth_result.output)
    assert "agent_code" in synth_output

    # Verify generated code is valid Python (AST parse)
    code = synth_output["agent_code"]
    ast.parse(code)  # Raises SyntaxError if invalid

    # Verify the generated code contains the right class
    assert "AuditPipelineAgent" in code
    assert "class AuditPipelineAgentGoal" in code
    assert "class AuditPipelineAgentResult" in code


# ---------------------------------------------------------------------------
# Use Case 3: Knowledge Refresh Cycle (audit → KG enrichment)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_knowledge_refresh_dag_execution() -> None:
    """MetaAuditor extracts data, KnowledgeGraphAgent indexes into KG."""
    event_bus, memory_manager, agent_registry, tool_registry, meta_services, services = _create_test_infra()

    # Seed substantial execution history
    await _seed_events(event_bus, count=8, run_id="run_alpha")
    await _seed_events(event_bus, count=5, run_id="run_beta", score_base=0.9)

    executor = create_meta_executor(
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        config=ExecutorConfig(enable_events=False),
        services=services,
        meta_services=meta_services,
    )

    # Run the knowledge refresh DAG
    dag = create_knowledge_refresh_dag()
    result = await executor.run(dag=dag, initial_context=Context())

    assert result.success, f"Knowledge refresh DAG failed: {result.error}"
    assert len(result.node_results) == 2

    # Audit node produced data
    audit_result = result.node_results[0]
    assert audit_result.success is True

    # KG node processed the data
    kg_result = result.node_results[1]
    assert kg_result.success is True
    kg_output = json.loads(kg_result.output)
    assert "stats" in kg_output

    # Verify the final context has both outputs
    assert result.final_context.get("audit_data") is not None
    assert result.final_context.get("kg_result") is not None


# ---------------------------------------------------------------------------
# Use Case 4: Quality Degradation Detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quality_degradation_detection() -> None:
    """When quality drops, the audit trail catches and reports the anomaly."""
    event_bus, _mm, agent_registry, tool_registry, meta_services, services = _create_test_infra()

    # Seed 8 good events, then 1 bad event (quality drop)
    await _seed_events(event_bus, count=8, score_base=0.85, score_step=0.01)
    await event_bus.publish(
        event=Event.create(
            type=EventType.EVAL_COMPLETED,
            payload={"run_id": "bad_run", "score": 0.2, "output": "degraded"},
            source="test_harness",
            correlation_id="bad_run",
        )
    )

    executor = create_meta_executor(
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        config=ExecutorConfig(enable_events=False),
        services=services,
        meta_services=meta_services,
    )

    # Run the self-audit DAG
    dag = create_self_audit_dag()
    result = await executor.run(dag=dag, initial_context=Context())

    assert result.success, f"Self-audit failed: {result.error}"

    # Parse the audit report
    audit_output = json.loads(result.node_results[0].output)
    report = audit_output["report"]

    # Quality trend should show the degradation
    assert "quality_trend" in report
    trend_data = report["quality_trend"]
    trend = trend_data.get("trend", [])
    assert len(trend) > 0
    # The low score (0.2) should be in the trend
    assert any(score < 0.5 for score in trend), f"Expected degraded score in trend: {trend}"

    # Anomalies should detect the outlier
    assert "anomalies" in report
    anomaly_data = report["anomalies"]
    anomalies = anomaly_data.get("anomalies", [])
    assert len(anomalies) > 0, "Expected at least one anomaly from the 0.2 score drop"

    # Summary should mention anomalies
    summary = audit_output["summary"]
    assert "Anomalies detected" in summary


# ---------------------------------------------------------------------------
# Use Case 5: Registry Introspection Round-Trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_introspection_round_trip() -> None:
    """Meta-agents discover and reference each other through introspection."""
    event_bus, _mm, agent_registry, tool_registry, meta_services, services = _create_test_infra()
    await _seed_events(event_bus, count=3)

    create_meta_executor(
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        config=ExecutorConfig(enable_events=False),
        services=services,
        meta_services=meta_services,
    )

    # Run ArchitectAgent directly — executor created for registration side effect
    architect = agent_registry.get("MetaArchitect")
    assert architect is not None

    goal = ArchitectGoal(feature_description="build an audit pipeline")
    context = AgentContext(
        run_id="introspection_test",
        agent_id="MetaArchitect",
    )
    result = await architect.run(goal=goal, context=context)

    assert result.success, f"ArchitectAgent failed: {result.error}"
    assert result.output is not None

    dag_spec = result.output.dag_spec
    assert "nodes" in dag_spec
    nodes = dag_spec["nodes"]

    # The architect discovered meta-agents through introspection
    # and included them in the generated DAG
    node_ref_ids = [n.get("ref_id", "") for n in nodes]
    assert len(node_ref_ids) > 0, "Architect should generate at least one node"

    # At least one node should reference a meta-agent
    meta_agent_ids = {"MetaArchitect", "MetaSynthesizer", "MetaAuditor", "MetaKnowledgeGraph"}
    found_meta = any(ref_id in meta_agent_ids for ref_id in node_ref_ids)
    assert found_meta, f"Expected meta-agent in DAG nodes, got ref_ids: {node_ref_ids}"

    # The generated DAG should be valid
    assert "name" in dag_spec
    assert "edges" in dag_spec

    # Verify the introspection tool itself works
    introspect_tool = tool_registry.get("meta_introspect_registry")
    assert introspect_tool is not None
    introspect_result = await introspect_tool.execute(registry_type="agents")
    assert introspect_result.success
    agent_list = introspect_result.data["agents"]
    agent_ids = [a["id"] for a in agent_list]
    # All 4 meta-agents should be discoverable
    for meta_id in meta_agent_ids:
        assert meta_id in agent_ids, f"{meta_id} not found in registry"
