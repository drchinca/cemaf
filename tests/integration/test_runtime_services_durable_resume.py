"""Native RuntimeServices checkpoint/resume survives replacement without bypassing gates."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from enum import StrEnum
from pathlib import Path

import pytest
from pydantic import BaseModel

from cemaf.agents.base import AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.context.context import Context
from cemaf.context.patch import SecurityLevel
from cemaf.core.enums import RunStatus
from cemaf.core.execution import CancellationToken
from cemaf.core.types import AgentID, NodeID, RunID
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType
from cemaf.interceptors import GateValidationInterceptor, create_interceptor_pipeline
from cemaf.moderation.factories import create_keyword_moderation_pipeline
from cemaf.observability.budget_guard import BudgetGuard
from cemaf.observability.otel_tracer import OTelTracer
from cemaf.observability.run_logger import InMemoryRunLogger
from cemaf.orchestration.dag import DAG, Condition, ConditionOperator, Edge, EdgeCondition, Node
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
        clearance=SecurityLevel.CONFIDENTIAL,
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
        clearance=SecurityLevel.CONFIDENTIAL,
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


class FlakyOutcome(StrEnum):
    """How the 'flaky' node behaves for one worker."""

    FAILS = "fails"
    SUCCEEDS = "succeeds"
    WORKER_DIES = "worker_dies"


class _OutcomeNodeExecutor:
    """Node executor whose 'broken' node always fails and whose 'flaky' node behaves as told."""

    def __init__(self, *, flaky: FlakyOutcome) -> None:
        self.flaky = flaky
        self.executed: list[str] = []

    async def execute_node(self, node: Node, context: Context) -> NodeResult:
        self.executed.append(str(node.id))
        if str(node.id) == "flaky" and self.flaky == FlakyOutcome.WORKER_DIES:
            raise asyncio.CancelledError("simulated worker termination")
        if str(node.id) == "broken" or (str(node.id) == "flaky" and self.flaky == FlakyOutcome.FAILS):
            return NodeResult(node_id=node.id, success=False, error=f"{node.id} failed")
        return NodeResult(node_id=node.id, success=True, output=f"ran:{node.id}")


@pytest.mark.asyncio
async def test_resume_keeps_a_failed_node_that_let_the_run_continue_failed(tmp_path: Path) -> None:
    """A node that failed but let the run continue must not look successful after resume."""
    checkpointer = FileCheckpointer(tmp_path / "outcome-checkpoints", max_checkpoints=0)
    dag = _failed_outcome_dag()
    run_id = RunID("failed-outcome-resume")

    first_worker = _OutcomeNodeExecutor(flaky=FlakyOutcome.FAILS)
    first = DAGExecutor(
        node_executor=first_worker,
        services=RuntimeServices(checkpointer=checkpointer, checkpoint_interval=1),
    )
    halted = await first.run(dag, run_id=run_id)
    checkpoint = await checkpointer.load(run_id)

    replacement_worker = _OutcomeNodeExecutor(flaky=FlakyOutcome.SUCCEEDS)
    replacement = DAGExecutor(
        node_executor=replacement_worker,
        services=RuntimeServices(checkpointer=checkpointer, checkpoint_interval=1),
    )
    resumed = await replacement.resume(run_id=run_id, dag=dag)

    assert halted.status is RunStatus.FAILED
    assert first_worker.executed == ["broken", "flaky"]
    assert checkpoint is not None
    assert NodeID("broken") in checkpoint.unsuccessful_nodes
    assert resumed.status is RunStatus.COMPLETED
    assert replacement_worker.executed == ["flaky"]


def _failed_outcome_dag() -> DAG:
    """broken fails but the run continues; after_broken needs broken to succeed and flaky to finish."""
    broken = replace(
        Node.tool(id="broken", name="broken", tool_id="worker", output_key="broken_result"),
        retry_on_failure=True,
        max_retries=0,
    )
    flaky = replace(
        Node.tool(id="flaky", name="flaky", tool_id="worker", output_key="flaky_result"),
        retry_on_failure=False,
    )
    after_broken = Node.tool(
        id="after_broken", name="after broken", tool_id="worker", output_key="after_result"
    )
    return DAG(
        name="durable-failed-outcome",
        nodes=(broken, flaky, after_broken),
        edges=(
            Edge(source=broken.id, target=flaky.id, condition=EdgeCondition.ALWAYS),
            Edge(source=broken.id, target=after_broken.id, condition=EdgeCondition.ON_SUCCESS),
            Edge(source=flaky.id, target=after_broken.id, condition=EdgeCondition.ALWAYS),
        ),
        entry_node=broken.id,
    )


def _executor_for(*, worker: _OutcomeNodeExecutor, checkpointer: FileCheckpointer) -> DAGExecutor:
    """DAGExecutor that checkpoints after every node."""
    return DAGExecutor(
        node_executor=worker,
        services=RuntimeServices(checkpointer=checkpointer, checkpoint_interval=1),
    )


@pytest.mark.asyncio
async def test_a_continued_failure_is_not_the_failed_node_when_the_worker_dies(tmp_path: Path) -> None:
    """The worker dies right after a failure that let the run continue: resume must not re-run that node."""
    checkpointer = FileCheckpointer(tmp_path / "died-checkpoints", max_checkpoints=0)
    dag = _failed_outcome_dag()
    run_id = RunID("continued-failure-worker-dies")

    with pytest.raises(asyncio.CancelledError):
        await _executor_for(
            worker=_OutcomeNodeExecutor(flaky=FlakyOutcome.WORKER_DIES), checkpointer=checkpointer
        ).run(dag, run_id=run_id)
    checkpoint = await checkpointer.load(run_id)
    replacement_worker = _OutcomeNodeExecutor(flaky=FlakyOutcome.SUCCEEDS)
    resumed = await _executor_for(worker=replacement_worker, checkpointer=checkpointer).resume(
        run_id=run_id, dag=dag
    )

    assert checkpoint is not None
    assert checkpoint.failed_node is None
    assert checkpoint.unsuccessful_nodes == (NodeID("broken"),)
    assert resumed.status is RunStatus.COMPLETED
    assert replacement_worker.executed == ["flaky"]


@pytest.mark.asyncio
async def test_exception_during_a_resumed_run_keeps_restored_nodes(tmp_path: Path) -> None:
    """An exception outside node execution on a resumed run must checkpoint the restored nodes too."""
    checkpointer = FileCheckpointer(tmp_path / "raise-checkpoints", max_checkpoints=0)
    dag = _failed_outcome_dag()
    run_id = RunID("resumed-run-raises")
    bus = InMemoryEventBus()

    async def crash_after_flaky(event: Event) -> None:
        if event.payload.get("node_id") == "flaky":
            raise RuntimeError("audit sink offline")

    bus.subscribe(event_type=EventType.TASK_COMPLETED, handler=crash_after_flaky)

    await _executor_for(worker=_OutcomeNodeExecutor(flaky=FlakyOutcome.FAILS), checkpointer=checkpointer).run(
        dag, run_id=run_id
    )
    resumed = await DAGExecutor(
        node_executor=_OutcomeNodeExecutor(flaky=FlakyOutcome.SUCCEEDS),
        services=RuntimeServices(checkpointer=checkpointer, checkpoint_interval=1, event_bus=bus),
    ).resume(run_id=run_id, dag=dag)
    checkpoint = await checkpointer.load(run_id)

    assert resumed.status is RunStatus.FAILED
    assert "audit sink offline" in (resumed.error or "")
    assert checkpoint is not None
    assert NodeID("broken") in checkpoint.completed_nodes
    assert checkpoint.unsuccessful_nodes == (NodeID("broken"),)


class _BilledNodeExecutor:
    """Every node succeeds and bills a fixed cost; optionally cancels the run after one node."""

    def __init__(self, *, cost_per_node: float = 0.0, cancel_after: str | None = None) -> None:
        self.cost_per_node = cost_per_node
        self.cancel_after = cancel_after
        self.token = CancellationToken()

    async def execute_node(self, node: Node, context: Context) -> NodeResult:
        if str(node.id) == self.cancel_after:
            self.token.cancel(reason="operator stopped the run")
        return NodeResult(
            node_id=node.id,
            success=True,
            output=f"ran:{node.id}",
            metadata={"cost_estimate_usd": self.cost_per_node},
        )


def _chain_dag(*, name: str) -> DAG:
    """a -> b -> c, every node a plain tool node."""
    nodes = tuple(
        Node.tool(id=node_id, name=node_id, tool_id="worker", output_key=f"{node_id}_out")
        for node_id in "abc"
    )
    return DAG(
        name=name,
        nodes=nodes,
        edges=(Edge(source=NodeID("a"), target=NodeID("b")), Edge(source=NodeID("b"), target=NodeID("c"))),
        entry_node=NodeID("a"),
    )


@pytest.mark.asyncio
async def test_runs_started_together_get_different_ids() -> None:
    """Run ids must not depend on start time, or concurrent runs overwrite each other's checkpoints."""
    executor = DAGExecutor(node_executor=_BilledNodeExecutor())
    dag = _chain_dag(name="many-runs")

    results = await asyncio.gather(*(executor.run(dag) for _ in range(50)))

    assert len({result.run_id for result in results}) == 50


@pytest.mark.asyncio
async def test_a_budget_halt_saves_a_current_checkpoint(tmp_path: Path) -> None:
    """With a sparse checkpoint interval, a halt still leaves a checkpoint listing every completed node."""
    checkpointer = FileCheckpointer(tmp_path / "halt-checkpoints", max_checkpoints=0)
    executor = DAGExecutor(
        node_executor=_BilledNodeExecutor(cost_per_node=1.0),
        services=RuntimeServices(
            checkpointer=checkpointer,
            checkpoint_interval=10,
            budget_guard=BudgetGuard(max_cost_usd=1.5),
        ),
    )

    halted = await executor.run(_chain_dag(name="budget-halt"), run_id=RunID("budget-halted"))
    checkpoint = await checkpointer.load(RunID("budget-halted"))

    assert halted.status is RunStatus.FAILED
    assert checkpoint is not None
    assert checkpoint.status is RunStatus.FAILED
    assert checkpoint.completed_nodes == (NodeID("a"), NodeID("b"))


@pytest.mark.asyncio
async def test_a_cancelled_run_saves_a_current_checkpoint(tmp_path: Path) -> None:
    """Cancellation between nodes leaves a checkpoint listing the nodes that finished."""
    checkpointer = FileCheckpointer(tmp_path / "cancel-checkpoints", max_checkpoints=0)
    worker = _BilledNodeExecutor(cancel_after="a")
    executor = DAGExecutor(
        node_executor=worker,
        services=RuntimeServices(checkpointer=checkpointer, checkpoint_interval=10),
    )

    stopped = await executor.run(
        _chain_dag(name="cancelled"), run_id=RunID("cancelled-run"), cancellation_token=worker.token
    )
    checkpoint = await checkpointer.load(RunID("cancelled-run"))

    assert stopped.status is RunStatus.FAILED
    assert checkpoint is not None
    assert checkpoint.status is RunStatus.FAILED
    assert checkpoint.completed_nodes == (NodeID("a"),)
