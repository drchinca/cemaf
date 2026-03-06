"""Contract tests for CancellationToken integration in DAGExecutor."""

import pytest

from cemaf.context.context import Context
from cemaf.core.execution import CancellationToken
from cemaf.orchestration.dag import DAG, Edge, Node
from cemaf.orchestration.executor import DAGExecutor, NodeResult


class MockNodeExecutor:
    """Mock executor that tracks calls and optionally triggers cancellation."""

    def __init__(self, cancel_after: int = -1, token: CancellationToken | None = None) -> None:
        self.calls: list[str] = []
        self._cancel_after = cancel_after
        self._token = token

    async def execute_node(self, node: Node, context: Context) -> NodeResult:
        self.calls.append(str(node.id))
        if self._token and len(self.calls) >= self._cancel_after:
            self._token.cancel(reason="test cancellation")
        return NodeResult(node_id=node.id, success=True, output=f"result-{node.id}")


def _build_3_node_dag() -> DAG:
    """Build a simple A -> B -> C DAG."""
    dag = DAG(name="test-dag")
    dag = dag.add_node(node=Node.agent(id="a", name="A", agent_id="AgentA"))
    dag = dag.add_node(node=Node.agent(id="b", name="B", agent_id="AgentB"))
    dag = dag.add_node(node=Node.agent(id="c", name="C", agent_id="AgentC"))
    dag = dag.add_edge(edge=Edge(source="a", target="b"))
    dag = dag.add_edge(edge=Edge(source="b", target="c"))
    return dag


class TestDAGCancellation:
    """Contract: DAGExecutor must respect CancellationToken."""

    @pytest.mark.asyncio
    async def test_run_accepts_cancellation_token(self) -> None:
        """run() must accept an optional cancellation_token parameter."""
        executor_mock = MockNodeExecutor()
        dag_executor = DAGExecutor(node_executor=executor_mock)
        dag = _build_3_node_dag()

        token = CancellationToken()
        result = await dag_executor.run(
            dag=dag,
            initial_context=Context(),
            cancellation_token=token,
        )
        assert result.status.value == "completed"
        assert len(executor_mock.calls) == 3

    @pytest.mark.asyncio
    async def test_cancelled_token_stops_execution(self) -> None:
        """When token is cancelled mid-run, remaining nodes must not execute."""
        token = CancellationToken()
        executor_mock = MockNodeExecutor(cancel_after=1, token=token)
        dag_executor = DAGExecutor(node_executor=executor_mock)
        dag = _build_3_node_dag()

        result = await dag_executor.run(
            dag=dag,
            initial_context=Context(),
            cancellation_token=token,
        )

        # Node A executed, then token was cancelled, so B and C should be skipped
        assert executor_mock.calls == ["a"]
        assert result.status.value == "failed"
        assert "cancell" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_pre_cancelled_token_skips_all(self) -> None:
        """If token is already cancelled before run(), no nodes execute."""
        token = CancellationToken()
        token.cancel(reason="pre-cancelled")

        executor_mock = MockNodeExecutor()
        dag_executor = DAGExecutor(node_executor=executor_mock)
        dag = _build_3_node_dag()

        result = await dag_executor.run(
            dag=dag,
            initial_context=Context(),
            cancellation_token=token,
        )

        assert executor_mock.calls == []
        assert result.status.value == "failed"

    @pytest.mark.asyncio
    async def test_no_token_runs_normally(self) -> None:
        """Without a cancellation token, execution proceeds normally (backwards compatible)."""
        executor_mock = MockNodeExecutor()
        dag_executor = DAGExecutor(node_executor=executor_mock)
        dag = _build_3_node_dag()

        result = await dag_executor.run(dag=dag, initial_context=Context())
        assert result.status.value == "completed"
        assert len(executor_mock.calls) == 3
