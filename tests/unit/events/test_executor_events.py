"""Tests for DAGExecutor event bus integration."""

import pytest

from cemaf.context.context import Context
from cemaf.core.enums import NodeType, RunStatus
from cemaf.core.types import NodeID, RunID
from cemaf.events.mock import MockEventBus
from cemaf.events.protocols import EventType
from cemaf.orchestration.dag import DAG, Edge, Node
from cemaf.orchestration.executor import DAGExecutor, NodeResult


class _StubNodeExecutor:
    """Stub executor returning configurable results per node."""

    def __init__(self, results: dict[str, NodeResult] | None = None) -> None:
        self._results = results or {}

    async def execute_node(self, node: Node, context: Context) -> NodeResult:
        if str(node.id) in self._results:
            return self._results[str(node.id)]
        return NodeResult(
            node_id=node.id,
            success=True,
            output="ok",
            metadata={"cost_usd": 0.0, "tokens_used": 0},
        )


def _linear_dag(*, retry_on_failure: bool = True) -> DAG:
    """A -> B linear DAG."""
    dag = DAG(name="test-dag")
    dag = dag.add_node(
        Node(
            id=NodeID("a"),
            type=NodeType.TOOL,
            name="A",
            ref_id="t1",
            output_key="a_out",
            retry_on_failure=retry_on_failure,
        )
    )
    dag = dag.add_node(
        Node(
            id=NodeID("b"),
            type=NodeType.TOOL,
            name="B",
            ref_id="t2",
            output_key="b_out",
            retry_on_failure=retry_on_failure,
        )
    )
    dag = dag.add_edge(Edge(source=NodeID("a"), target=NodeID("b")))
    return dag


@pytest.mark.asyncio
async def test_dag_executor_emits_dag_started() -> None:
    """DAG_STARTED is published after run begins."""
    bus = MockEventBus()
    executor = DAGExecutor(
        node_executor=_StubNodeExecutor(),
        event_bus=bus,
    )

    await executor.run(dag=_linear_dag(), run_id=RunID("run-1"))

    started = bus.get_events_by_type(EventType.DAG_STARTED)
    assert len(started) == 1
    assert started[0].payload["dag_name"] == "test-dag"
    assert started[0].payload["run_id"] == "run-1"
    assert started[0].source == "dag_executor"
    assert started[0].correlation_id == "run-1"


@pytest.mark.asyncio
async def test_dag_executor_emits_task_completed_per_node() -> None:
    """TASK_COMPLETED is published for each successful node."""
    bus = MockEventBus()
    executor = DAGExecutor(
        node_executor=_StubNodeExecutor(),
        event_bus=bus,
    )

    await executor.run(dag=_linear_dag())

    completed = bus.get_events_by_type(EventType.TASK_COMPLETED)
    assert len(completed) == 2
    node_ids = {e.payload["node_id"] for e in completed}
    assert node_ids == {"a", "b"}


@pytest.mark.asyncio
async def test_dag_executor_emits_dag_completed() -> None:
    """DAG_COMPLETED is published on successful DAG execution."""
    bus = MockEventBus()
    executor = DAGExecutor(
        node_executor=_StubNodeExecutor(),
        event_bus=bus,
    )

    result = await executor.run(dag=_linear_dag())

    assert result.status == RunStatus.COMPLETED
    dag_completed = bus.get_events_by_type(EventType.DAG_COMPLETED)
    assert len(dag_completed) == 1
    assert dag_completed[0].payload["dag_name"] == "test-dag"
    assert dag_completed[0].payload["num_nodes"] == 2


@pytest.mark.asyncio
async def test_dag_executor_emits_task_failed_on_node_failure() -> None:
    """TASK_FAILED is published when a node fails."""
    bus = MockEventBus()
    failing_results = {
        "a": NodeResult(node_id=NodeID("a"), success=False, error="boom"),
    }
    executor = DAGExecutor(
        node_executor=_StubNodeExecutor(results=failing_results),
        event_bus=bus,
    )

    result = await executor.run(dag=_linear_dag(retry_on_failure=False))

    assert result.status == RunStatus.FAILED
    # One TASK_FAILED from the per-node emit, one from the DAG-level failure
    failed = bus.get_events_by_type(EventType.TASK_FAILED)
    assert len(failed) >= 1
    node_failure = [e for e in failed if e.payload.get("node_id") == "a"]
    assert len(node_failure) == 1
    assert node_failure[0].payload["error"] == "boom"


@pytest.mark.asyncio
async def test_executor_without_event_bus_still_works() -> None:
    """DAGExecutor runs normally when no event bus is provided."""
    executor = DAGExecutor(
        node_executor=_StubNodeExecutor(),
        event_bus=None,
    )

    result = await executor.run(dag=_linear_dag())

    assert result.status == RunStatus.COMPLETED
    assert len(result.node_results) == 2
