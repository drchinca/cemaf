"""Tests for DAG executor — core execution paths."""

import pytest

from cemaf.context.context import Context
from cemaf.core.enums import RunStatus
from cemaf.core.execution import CancellationToken
from cemaf.core.types import NodeID, RunID
from cemaf.observability.budget_guard import BudgetGuard
from cemaf.observability.run_logger import InMemoryRunLogger
from cemaf.orchestration.dag import DAG, Edge, EdgeCondition, Node
from cemaf.orchestration.executor import (
    DAGExecutor,
    ExecutionResult,
    ExecutorConfig,
    NodeExecutor,
    NodeResult,
)


class MockNodeExecutor:
    """Mock executor that returns configurable results."""

    def __init__(self, results: dict[str, NodeResult] | None = None, default_output: str = "ok"):
        self._results = results or {}
        self._default_output = default_output
        self.executed_nodes: list[str] = []

    async def execute_node(self, node: Node, context: Context) -> NodeResult:
        self.executed_nodes.append(str(node.id))
        if str(node.id) in self._results:
            return self._results[str(node.id)]
        return NodeResult(
            node_id=node.id,
            success=True,
            output=self._default_output,
            metadata={"cost_usd": 0.01, "tokens_used": 100},
        )


def _simple_dag() -> DAG:
    """A→B→C linear DAG."""
    dag = DAG(name="test-pipeline")
    dag = dag.add_node(Node.tool(id="a", name="A", tool_id="t1", output_key="a_out"))
    dag = dag.add_node(Node.tool(id="b", name="B", tool_id="t2", output_key="b_out"))
    dag = dag.add_node(Node.tool(id="c", name="C", tool_id="t3", output_key="c_out"))
    dag = dag.add_edge(Edge(source=NodeID("a"), target=NodeID("b")))
    dag = dag.add_edge(Edge(source=NodeID("b"), target=NodeID("c")))
    return dag


def _parallel_dag() -> DAG:
    """A→[B,C]→D parallel DAG."""
    dag = DAG(name="parallel-pipeline")
    dag = dag.add_node(Node.tool(id="a", name="A", tool_id="t1", output_key="a_out"))
    dag = dag.add_node(
        Node.parallel(id="par", name="Parallel", parallel_nodes=["b", "c"], output_key="par_out")
    )
    dag = dag.add_node(Node.tool(id="b", name="B", tool_id="t2", output_key="b_out"))
    dag = dag.add_node(Node.tool(id="c", name="C", tool_id="t3", output_key="c_out"))
    dag = dag.add_node(Node.tool(id="d", name="D", tool_id="t4", output_key="d_out"))
    dag = dag.add_edge(Edge(source=NodeID("a"), target=NodeID("par")))
    dag = dag.add_edge(Edge(source=NodeID("par"), target=NodeID("d")))
    return dag


class TestExecutorConfig:
    def test_defaults(self):
        config = ExecutorConfig()
        assert config.enable_logging is True
        assert config.enable_events is True
        assert config.enable_moderation is False
        assert config.merge_strategy == "last_write_wins"

    def test_frozen(self):
        config = ExecutorConfig()
        with pytest.raises(Exception):
            config.enable_logging = False  # type: ignore[misc]


class TestNodeResult:
    def test_success_result(self):
        result = NodeResult(node_id=NodeID("n1"), success=True, output="data")
        assert result.success is True
        assert result.output == "data"

    def test_failure_result(self):
        result = NodeResult(node_id=NodeID("n1"), success=False, error="boom")
        assert result.success is False
        assert result.error == "boom"


class TestExecutionResult:
    def test_success_property(self):
        result = ExecutionResult(
            run_id=RunID("r1"),
            dag_name="test",
            status=RunStatus.COMPLETED,
        )
        assert result.success is True

    def test_failure_property(self):
        result = ExecutionResult(
            run_id=RunID("r1"),
            dag_name="test",
            status=RunStatus.FAILED,
        )
        assert result.success is False

    def test_duration_ms(self):
        from datetime import timedelta

        from cemaf.core.utils import utc_now

        start = utc_now()
        end = start + timedelta(seconds=1.5)
        result = ExecutionResult(
            run_id=RunID("r1"),
            dag_name="test",
            status=RunStatus.COMPLETED,
            started_at=start,
            completed_at=end,
        )
        assert result.duration_ms == pytest.approx(1500.0, abs=1.0)


class TestNodeExecutorProtocol:
    def test_mock_satisfies_protocol(self):
        executor = MockNodeExecutor()
        assert isinstance(executor, NodeExecutor)


class TestLinearExecution:
    async def test_simple_dag_completes(self):
        mock = MockNodeExecutor()
        executor = DAGExecutor(node_executor=mock)
        result = await executor.run(dag=_simple_dag())

        assert result.success is True
        assert result.status == RunStatus.COMPLETED
        assert len(result.node_results) == 3
        assert mock.executed_nodes == ["a", "b", "c"]

    async def test_with_initial_context(self):
        mock = MockNodeExecutor()
        executor = DAGExecutor(node_executor=mock)
        ctx = Context(data={"query": "test"})
        result = await executor.run(dag=_simple_dag(), initial_context=ctx)

        assert result.success is True
        assert result.final_context.get(key="query") == "test"

    async def test_with_run_id(self):
        mock = MockNodeExecutor()
        executor = DAGExecutor(node_executor=mock)
        result = await executor.run(dag=_simple_dag(), run_id=RunID("custom_run"))

        assert result.run_id == "custom_run"

    async def test_node_failure_stops_execution(self):
        failing_result = NodeResult(node_id=NodeID("b"), success=False, error="node B failed")
        mock = MockNodeExecutor(results={"b": failing_result})
        executor = DAGExecutor(node_executor=mock)

        # Build DAG where node B has retry_on_failure=False so executor stops
        dag = DAG(name="test-pipeline")
        dag = dag.add_node(Node.tool(id="a", name="A", tool_id="t1", output_key="a_out"))
        b_node = Node.tool(id="b", name="B", tool_id="t2", output_key="b_out")
        dag = dag.add_node(
            Node(
                id=b_node.id,
                name=b_node.name,
                type=b_node.type,
                config=b_node.config,
                output_key=b_node.output_key,
                retry_on_failure=False,
            )
        )
        dag = dag.add_node(Node.tool(id="c", name="C", tool_id="t3", output_key="c_out"))
        dag = dag.add_edge(Edge(source=NodeID("a"), target=NodeID("b")))
        dag = dag.add_edge(Edge(source=NodeID("b"), target=NodeID("c")))

        result = await executor.run(dag=dag)

        assert result.success is False
        assert result.status == RunStatus.FAILED
        assert "node B failed" in (result.error or "")
        assert "c" not in mock.executed_nodes


class TestCancellation:
    async def test_cancellation_stops_execution(self):
        token = CancellationToken()
        mock = MockNodeExecutor()

        # Cancel after first node
        original_execute = mock.execute_node

        async def cancel_after_first(node, context):
            result = await original_execute(node, context)
            if str(node.id) == "a":
                token.cancel(reason="User requested stop")
            return result

        mock.execute_node = cancel_after_first

        executor = DAGExecutor(node_executor=mock)
        result = await executor.run(dag=_simple_dag(), cancellation_token=token)

        assert result.success is False
        assert "cancelled" in (result.error or "").lower()


class TestBudgetGuard:
    async def test_budget_exhaustion_halts(self):
        mock = MockNodeExecutor()
        guard = BudgetGuard(max_cost_usd=0.02, max_total_tokens=200)
        executor = DAGExecutor(node_executor=mock, budget_guard=guard)
        result = await executor.run(dag=_simple_dag())

        # Each node costs 0.01 and 100 tokens, budget is 0.02/200
        # After 2 nodes, budget exhausted
        assert result.success is False
        assert "Budget exhausted" in (result.error or "")
        assert "budget_guard" in result.metadata


class TestRunLogger:
    async def test_run_logger_records(self):
        mock = MockNodeExecutor()
        run_logger = InMemoryRunLogger()
        executor = DAGExecutor(node_executor=mock, run_logger=run_logger)
        result = await executor.run(dag=_simple_dag(), run_id=RunID("logged_run"))

        assert result.success is True
        record = run_logger.get_record(run_id="logged_run")
        assert record is not None


class TestRouterNode:
    async def test_router_selects_route(self):
        dag = DAG(name="router-dag")
        dag = dag.add_node(Node.tool(id="start", name="Start", tool_id="t1", output_key="start_out"))
        dag = dag.add_node(
            Node.router(id="router", name="Router", routes={"success": "good_path", "failure": "bad_path"})
        )
        dag = dag.add_node(Node.tool(id="good_path", name="Good", tool_id="t2", output_key="good_out"))
        dag = dag.add_node(Node.tool(id="bad_path", name="Bad", tool_id="t3", output_key="bad_out"))
        dag = dag.add_edge(Edge(source=NodeID("start"), target=NodeID("router")))
        dag = dag.add_edge(Edge(source=NodeID("router"), target=NodeID("good_path")))
        dag = dag.add_edge(Edge(source=NodeID("router"), target=NodeID("bad_path")))

        mock = MockNodeExecutor()
        executor = DAGExecutor(node_executor=mock)
        ctx = Context(data={"route": "success"})
        result = await executor.run(dag=dag, initial_context=ctx)

        assert result.success is True
        # Router should have selected "good_path"
        assert "good_path" in mock.executed_nodes


class TestEdgeConditions:
    async def test_on_success_edge(self):
        dag = DAG(name="cond-dag")
        dag = dag.add_node(Node.tool(id="a", name="A", tool_id="t1", output_key="a_out"))
        dag = dag.add_node(Node.tool(id="b", name="B", tool_id="t2", output_key="b_out"))
        dag = dag.add_edge(Edge(source=NodeID("a"), target=NodeID("b"), condition=EdgeCondition.ON_SUCCESS))

        mock = MockNodeExecutor()
        executor = DAGExecutor(node_executor=mock)
        result = await executor.run(dag=dag)

        assert result.success is True
        assert "b" in mock.executed_nodes

    async def test_on_failure_edge_skipped_on_success(self):
        dag = DAG(name="cond-dag")
        dag = dag.add_node(Node.tool(id="a", name="A", tool_id="t1", output_key="a_out"))
        dag = dag.add_node(Node.tool(id="fallback", name="Fallback", tool_id="t2", output_key="fb_out"))
        dag = dag.add_edge(
            Edge(source=NodeID("a"), target=NodeID("fallback"), condition=EdgeCondition.ON_FAILURE)
        )

        mock = MockNodeExecutor()
        executor = DAGExecutor(node_executor=mock)
        result = await executor.run(dag=dag)

        assert result.success is True
        assert "fallback" not in mock.executed_nodes
