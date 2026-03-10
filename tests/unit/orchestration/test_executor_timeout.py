"""Tests for per-node timeout in DAGExecutor."""

import asyncio

import pytest

from cemaf.context.context import Context
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.executor import DAGExecutor, ExecutorConfig, NodeResult


class SlowNodeExecutor:
    """Node executor that hangs for a configurable duration."""

    def __init__(self, delay_seconds: float = 10.0) -> None:
        self._delay = delay_seconds

    async def execute_node(self, node: Node, context: Context) -> NodeResult:
        """Simulate a slow/hanging node."""
        await asyncio.sleep(self._delay)
        return NodeResult(node_id=node.id, success=True, output="done")


class TestNodeTimeout:
    """Tests for per-node execution timeout."""

    @pytest.mark.asyncio
    async def test_node_timeout_triggers(self) -> None:
        """A node that exceeds the timeout produces a failure NodeResult."""
        slow_executor = SlowNodeExecutor(delay_seconds=10.0)
        dag_executor = DAGExecutor(
            node_executor=slow_executor,
            node_timeout_seconds=0.05,
        )

        dag = DAG(name="timeout-dag")
        dag = dag.add_node(Node.tool(id="slow", name="Slow", tool_id="t"))

        result = await dag_executor.run(dag=dag, initial_context=Context())

        assert len(result.node_results) == 1
        node_result = result.node_results[0]
        assert not node_result.success
        assert "timed out" in (node_result.error or "")
        assert "0.05s" in (node_result.error or "")

    @pytest.mark.asyncio
    async def test_node_timeout_default(self) -> None:
        """Default timeout is 300 seconds."""
        executor = DAGExecutor(
            node_executor=SlowNodeExecutor(),
        )
        assert executor._node_timeout == 300.0

    def test_timeout_in_config(self) -> None:
        """ExecutorConfig accepts node_timeout_seconds."""
        config = ExecutorConfig(node_timeout_seconds=60.0)
        assert config.node_timeout_seconds == 60.0

        default_config = ExecutorConfig()
        assert default_config.node_timeout_seconds == 300.0

    @pytest.mark.asyncio
    async def test_node_completes_within_timeout(self) -> None:
        """A node that finishes before the timeout succeeds normally."""
        fast_executor = SlowNodeExecutor(delay_seconds=0.01)
        dag_executor = DAGExecutor(
            node_executor=fast_executor,
            node_timeout_seconds=5.0,
        )

        dag = DAG(name="fast-dag")
        dag = dag.add_node(Node.tool(id="fast", name="Fast", tool_id="t"))

        result = await dag_executor.run(dag=dag, initial_context=Context())

        assert len(result.node_results) == 1
        assert result.node_results[0].success
