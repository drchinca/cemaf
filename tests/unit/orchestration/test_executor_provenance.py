"""Tests for provenance-aware DAG executor with budget guard."""

import pytest

from cemaf.context.context import Context
from cemaf.core.enums import NodeType, RunStatus
from cemaf.core.types import NodeID
from cemaf.observability.budget_guard import BudgetGuard
from cemaf.observability.run_logger import InMemoryRunLogger
from cemaf.orchestration.dag import DAG, Edge, Node
from cemaf.orchestration.executor import DAGExecutor, NodeResult


class MockNodeExecutor:
    """Mock node executor that returns configurable results."""

    def __init__(self, results: dict[str, NodeResult] | None = None) -> None:
        self._results = results or {}
        self._default_result = NodeResult(
            node_id=NodeID("default"),
            success=True,
            output="mock output",
            metadata={"cost_usd": 0.1, "tokens_used": 1000},
        )

    async def execute_node(self, node: Node, context: Context) -> NodeResult:
        if str(node.id) in self._results:
            return self._results[str(node.id)]
        return NodeResult(
            node_id=node.id,
            success=True,
            output=f"output_{node.id}",
            metadata={"cost_usd": 0.1, "tokens_used": 1000},
        )


def _build_linear_dag(num_nodes: int = 3) -> DAG:
    """Build a simple linear DAG with N nodes."""
    dag = DAG(name="test_dag")
    prev_id: NodeID | None = None
    for i in range(num_nodes):
        node = Node(
            id=NodeID(f"step_{i}"),
            type=NodeType.TOOL,
            name=f"Step {i}",
            ref_id=f"tool_{i}",
            output_key=f"step_{i}_output",
        )
        dag = dag.add_node(node)
        if prev_id:
            dag = dag.add_edge(Edge(source=prev_id, target=node.id))
        prev_id = node.id
    return dag


class TestExecutorWithBudgetGuard:
    """Tests for DAGExecutor budget guard integration."""

    @pytest.mark.asyncio
    async def test_execution_succeeds_within_budget(self) -> None:
        guard = BudgetGuard(max_cost_usd=10.0, max_total_tokens=100_000)
        executor = DAGExecutor(
            node_executor=MockNodeExecutor(),
            budget_guard=guard,
        )
        dag = _build_linear_dag(num_nodes=3)
        result = await executor.run(dag=dag)
        assert result.success
        assert result.status == RunStatus.COMPLETED
        assert guard.accumulated_tokens == 3000  # 3 nodes * 1000 tokens

    @pytest.mark.asyncio
    async def test_execution_halts_when_budget_exhausted(self) -> None:
        # Budget only allows 1 node worth of cost
        guard = BudgetGuard(max_cost_usd=0.15, max_total_tokens=100_000)
        executor = DAGExecutor(
            node_executor=MockNodeExecutor(),
            budget_guard=guard,
        )
        dag = _build_linear_dag(num_nodes=3)
        result = await executor.run(dag=dag)
        assert not result.success
        assert result.status == RunStatus.FAILED
        assert "Budget exhausted" in (result.error or "")
        assert result.metadata.get("budget_guard") is not None

    @pytest.mark.asyncio
    async def test_execution_without_budget_guard(self) -> None:
        executor = DAGExecutor(node_executor=MockNodeExecutor())
        dag = _build_linear_dag(num_nodes=3)
        result = await executor.run(dag=dag)
        assert result.success

    @pytest.mark.asyncio
    async def test_budget_guard_with_run_logger(self) -> None:
        guard = BudgetGuard(max_cost_usd=0.15, max_total_tokens=100_000)
        run_logger = InMemoryRunLogger()
        executor = DAGExecutor(
            node_executor=MockNodeExecutor(),
            budget_guard=guard,
            run_logger=run_logger,
        )
        dag = _build_linear_dag(num_nodes=3)
        result = await executor.run(dag=dag)
        assert not result.success
        # end_run moves record to history and clears current
        history = run_logger.get_history()
        assert len(history) == 1
        assert not history[0].success

    @pytest.mark.asyncio
    async def test_budget_guard_tracks_cumulative_cost(self) -> None:
        guard = BudgetGuard(max_cost_usd=1.0, max_total_tokens=100_000)
        executor = DAGExecutor(
            node_executor=MockNodeExecutor(),
            budget_guard=guard,
        )
        dag = _build_linear_dag(num_nodes=5)
        await executor.run(dag=dag)
        assert guard.accumulated_cost_usd == 0.5  # 5 * 0.1
        assert guard.accumulated_tokens == 5000  # 5 * 1000

    @pytest.mark.asyncio
    async def test_failed_nodes_dont_update_budget(self) -> None:
        """Budget guard only records usage for successful nodes."""
        results = {
            "step_0": NodeResult(
                node_id=NodeID("step_0"),
                success=True,
                output="ok",
                metadata={"cost_usd": 0.1, "tokens_used": 1000},
            ),
            "step_1": NodeResult(
                node_id=NodeID("step_1"),
                success=False,
                error="test failure",
                metadata={"cost_usd": 0.5, "tokens_used": 5000},
            ),
        }
        guard = BudgetGuard(max_cost_usd=10.0, max_total_tokens=100_000)
        executor = DAGExecutor(
            node_executor=MockNodeExecutor(results=results),
            budget_guard=guard,
        )
        dag = _build_linear_dag(num_nodes=2)
        await executor.run(dag=dag)
        # Only the successful node's cost should be tracked
        assert guard.accumulated_cost_usd == 0.1
        assert guard.accumulated_tokens == 1000
