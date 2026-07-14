"""Native RuntimeServices checkpoint/resume survives replacement without bypassing gates."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import BaseModel

from cemaf.agents.base import AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.context.context import Context
from cemaf.core.types import AgentID, NodeID, RunID
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType
from cemaf.interceptors import GateValidationInterceptor, create_interceptor_pipeline
from cemaf.moderation.factories import create_keyword_moderation_pipeline
from cemaf.observability.otel_tracer import OTelTracer
from cemaf.observability.run_logger import InMemoryRunLogger
from cemaf.orchestration.dag import DAG, Condition, ConditionOperator, Edge, Node
from cemaf.orchestration.executor import DAGExecutor, ExecutorConfig
from cemaf.orchestration.file_checkpointer import FileCheckpointer
from cemaf.orchestration.results import NodeResult
from cemaf.orchestration.services import RuntimeServices
from cemaf.replay.replayer import Replayer, ReplayMode
from cemaf.validation.factories import create_validation_pipeline
from cemaf.validation.rules import RequiredFieldsRule


class _Goal(BaseModel):
    stage: str
    prior: str = ""


class _WorkerAgent:
    def __init__(self, *, die_on_second: bool) -> None:
        self._die_on_second = die_on_second

    @property
    def id(self) -> AgentID:
        return AgentID("DurableWorker")

    @property
    def description(self) -> str:
        return "Disposable worker used for native durable-resume proof"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _Goal, context: AgentContext) -> AgentResult[dict[str, str]]:
        if self._die_on_second and goal.stage == "second":
            raise asyncio.CancelledError("simulated worker termination")
        return AgentResult.ok(
            output={"stage": goal.stage, "value": f"completed:{goal.stage}", "prior": goal.prior},
            state=AgentState(),
            metadata={"cost_estimate_usd": 0.001, "tokens_total": 10},
        )


class _RoutingNodeExecutor:
    def __init__(self, *, die_on: str | None = None) -> None:
        self.die_on = die_on
        self.executed: list[str] = []

    async def execute_node(self, node: Node, context: Context) -> NodeResult:
        self.executed.append(str(node.id))
        if str(node.id) == self.die_on:
            raise asyncio.CancelledError("simulated termination after route selection")
        return NodeResult(node_id=node.id, success=True, output=f"ran:{node.id}")


def _registry(*, die_on_second: bool) -> AgentRegistry:
    registry = AgentRegistry()
    registry.register_agent(
        agent_instance=_WorkerAgent(die_on_second=die_on_second),
        goal_type=_Goal,
    )
    return registry


def _dag() -> DAG:
    first = Node.agent(
        id="first",
        name="first",
        agent_id="DurableWorker",
        input_mapping={"stage": "first"},
        output_key="first_result",
    )
    second = Node.agent(
        id="second",
        name="second",
        agent_id="DurableWorker",
        input_mapping={"stage": "second", "prior": "$$first_result$$"},
        output_key="second_result",
    )
    return DAG(
        name="native-runtime-durable",
        nodes=(first, second),
        edges=(Edge(source=first.id, target=second.id),),
        entry_node=NodeID("first"),
    )


@pytest.mark.asyncio
async def test_replacement_root_resumes_file_checkpoint_with_gates_events_trace_and_replay(
    tmp_path: Path,
) -> None:
    otel_trace = pytest.importorskip("opentelemetry.sdk.trace")
    export_module = pytest.importorskip("opentelemetry.sdk.trace.export")
    memory_exporter_module = pytest.importorskip("opentelemetry.sdk.trace.export.in_memory_span_exporter")
    exporter = memory_exporter_module.InMemorySpanExporter()
    provider = otel_trace.TracerProvider()
    provider.add_span_processor(export_module.SimpleSpanProcessor(exporter))
    tracer = OTelTracer(provider.get_tracer("cemaf.durable-runtime"))

    checkpointer = FileCheckpointer(tmp_path / "checkpoints", max_checkpoints=0)
    validator = create_validation_pipeline(rules=[RequiredFieldsRule(fields=("stage", "value", "prior"))])
    interceptor = create_interceptor_pipeline(interceptors=(GateValidationInterceptor(validator=validator),))
    run_id = RunID("native-runtime-replacement")
    dag = _dag()

    doomed = create_executor(
        agent_registry=_registry(die_on_second=True),
        config=ExecutorConfig(enable_events=False, enable_moderation=True),
        services=RuntimeServices(
            checkpointer=checkpointer,
            checkpoint_interval=1,
            tracer=tracer,
            interceptor_pipeline=interceptor,
            moderation_pipeline=create_keyword_moderation_pipeline(blocked_words=("FORBIDDEN",)),
        ),
    )
    with pytest.raises(asyncio.CancelledError):
        await doomed.run(dag=dag, run_id=run_id)

    interrupted = await checkpointer.load(run_id)
    assert interrupted is not None
    assert interrupted.status.value == "running"
    assert interrupted.completed_nodes == (NodeID("first"),)
    assert interrupted.pending_nodes == (NodeID("second"),)
    assert interrupted.context.get("first_result") is not None
    assert interrupted.context.get("second_result") is None

    events: list[Event] = []
    bus = InMemoryEventBus()

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe_all(capture)
    logger = InMemoryRunLogger()
    replacement = create_executor(
        agent_registry=_registry(die_on_second=False),
        config=ExecutorConfig(enable_events=True, enable_logging=True, enable_moderation=True),
        services=RuntimeServices(
            checkpointer=checkpointer,
            checkpoint_interval=1,
            tracer=tracer,
            run_logger=logger,
            event_bus=bus,
            interceptor_pipeline=interceptor,
            moderation_pipeline=create_keyword_moderation_pipeline(
                blocked_words=("FORBIDDEN",), event_bus=bus
            ),
            context_compiler=PriorityContextCompiler(
                token_estimator=SimpleTokenEstimator(chars_per_token=3.5)
            ),
            token_budget=TokenBudget(max_tokens=120, reserved_for_output=30),
        ),
    )

    resumed = await replacement.resume(run_id=run_id, dag=dag)

    assert resumed.success
    assert [result.node_id for result in resumed.node_results] == [NodeID("second")]
    assert resumed.final_context is not None
    assert resumed.final_context.get("first_result") is not None
    assert resumed.final_context.get("second_result") is not None
    second = resumed.node_results[0]
    assert second.metadata["_moderation_checked"] is True
    assert second.metadata["interceptors"]["gate_validation:*"]["gate"] == "passed"

    completed = await checkpointer.load(run_id)
    assert completed is not None
    assert completed.status.value == "completed"
    assert completed.pending_nodes == ()
    assert completed.completed_nodes == (NodeID("first"), NodeID("second"))

    task_completed = [event for event in events if event.type == EventType.TASK_COMPLETED]
    assert [event.payload["node_id"] for event in task_completed] == ["second"]
    record = logger.get_record(str(run_id))
    assert record is not None
    replay = await Replayer(record).replay(mode=ReplayMode.PATCH_ONLY)
    assert replay.success
    assert replay.final_context.data == resumed.final_context.data

    spans = exporter.get_finished_spans()
    assert any(span.name == "cemaf.dag.resume" for span in spans)
    resumed_node_spans = [
        span
        for span in spans
        if span.name == "cemaf.node.attempt"
        and span.attributes.get("cemaf.run.id") == str(run_id)
        and span.attributes.get("cemaf.node.id") == "second"
    ]
    assert resumed_node_spans


@pytest.mark.asyncio
async def test_resume_preserves_conditional_route_and_never_executes_rejected_branch(
    tmp_path: Path,
) -> None:
    checkpointer = FileCheckpointer(tmp_path / "conditional-checkpoints", max_checkpoints=0)
    condition = Node.conditional(
        id="route",
        name="choose branch",
        condition=Condition(field="proceed", operator=ConditionOperator.EQUALS, value=True),
        routes={True: "selected", False: "rejected"},
        output_key="route_result",
    )
    selected = Node.tool(id="selected", name="selected", tool_id="worker", output_key="selected_result")
    rejected = Node.tool(id="rejected", name="rejected", tool_id="worker", output_key="rejected_result")
    dag = DAG(
        name="durable-conditional-route",
        nodes=(condition, selected, rejected),
        edges=(
            Edge(source=condition.id, target=selected.id),
            Edge(source=condition.id, target=rejected.id),
        ),
        entry_node=condition.id,
    )
    run_id = RunID("conditional-route-takeover")

    doomed_worker = _RoutingNodeExecutor(die_on="selected")
    doomed = DAGExecutor(
        node_executor=doomed_worker,
        services=RuntimeServices(checkpointer=checkpointer, checkpoint_interval=1),
    )
    with pytest.raises(asyncio.CancelledError):
        await doomed.run(dag, initial_context=Context(data={"proceed": True}), run_id=run_id)

    interrupted = await checkpointer.load(run_id)
    assert interrupted is not None
    assert interrupted.completed_nodes == (NodeID("route"),)
    assert interrupted.route_choices == {"route": ["selected"]}

    replacement_worker = _RoutingNodeExecutor()
    replacement = DAGExecutor(
        node_executor=replacement_worker,
        services=RuntimeServices(checkpointer=checkpointer, checkpoint_interval=1),
    )
    result = await replacement.resume(run_id=run_id, dag=dag)

    assert result.success
    assert replacement_worker.executed == ["selected"]
    assert result.final_context is not None
    assert result.final_context.get("selected_result") == "ran:selected"
    assert result.final_context.get("rejected_result") is None
    completed = await checkpointer.load(run_id)
    assert completed is not None
    assert completed.status.value == "completed"
    assert completed.pending_nodes == ()
