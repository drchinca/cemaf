"""Concurrent DAG execution stress tests.

Tests parallel node execution for concurrency correctness,
failure isolation, context isolation, and scale behavior.
"""

import pytest

from cemaf.context.context import Context
from cemaf.core.enums import NodeType
from cemaf.core.types import NodeID
from cemaf.orchestration.dag import DAG, Edge, Node
from cemaf.orchestration.executor import DAGExecutor, NodeResult
from tests.conftest import MockNodeExecutor


def _build_parallel_dag(
    parallel_node_ids: list[str],
    parallel_id: str = "parallel",
    post_node_id: str | None = None,
    retry_on_failure: bool = True,
) -> DAG:
    """Build a DAG with a PARALLEL node fanning out to child nodes."""
    dag = DAG(name="parallel_test")
    dag = dag.add_node(
        Node(
            id=NodeID(parallel_id),
            type=NodeType.PARALLEL,
            name="Parallel",
            parallel_nodes=parallel_node_ids,
            output_key="parallel_results",
            retry_on_failure=retry_on_failure,
        )
    )
    for nid in parallel_node_ids:
        dag = dag.add_node(
            Node.tool(
                id=nid,
                name=f"Node {nid}",
                tool_id="t",
                output_key=f"{nid}_out",
            )
        )
    if post_node_id:
        dag = dag.add_node(
            Node.tool(
                id=post_node_id,
                name="Post",
                tool_id="t",
                output_key=f"{post_node_id}_out",
            )
        )
        dag = dag.add_edge(
            Edge(
                source=NodeID(parallel_id),
                target=NodeID(post_node_id),
            )
        )
    return dag


class TestParallelNodesExecuteConcurrently:
    """Verify parallel nodes actually run and produce results."""

    @pytest.mark.asyncio
    async def test_parallel_nodes_execute_concurrently(self) -> None:
        """DAG with PARALLEL node runs both branches and merges results."""
        mock = MockNodeExecutor()
        dag = _build_parallel_dag(
            parallel_node_ids=["branch_a", "branch_b"],
            post_node_id="collector",
        )

        executor = DAGExecutor(node_executor=mock)
        result = await executor.run(
            dag,
            initial_context=Context(data={"seed": 42}),
        )

        assert result.success
        assert "branch_a" in mock.executed
        assert "branch_b" in mock.executed
        assert "collector" in mock.executed
        assert result.final_context.get("branch_a_out") == "success_branch_a"
        assert result.final_context.get("branch_b_out") == "success_branch_b"
        assert result.final_context.get("seed") == 42


class TestParallelNodeFailureIsolation:
    """One branch failing does not prevent other branches from executing."""

    @pytest.mark.asyncio
    async def test_parallel_node_failure_isolation(self) -> None:
        """One branch fails, other succeeds; both execute, good output preserved."""
        mock = MockNodeExecutor(
            node_results={
                "good_branch": NodeResult(
                    node_id=NodeID("good_branch"),
                    success=True,
                    output="good_result",
                ),
                "bad_branch": NodeResult(
                    node_id=NodeID("bad_branch"),
                    success=False,
                    error="Simulated failure",
                ),
            }
        )

        dag = _build_parallel_dag(parallel_node_ids=["good_branch", "bad_branch"])
        executor = DAGExecutor(node_executor=mock)
        result = await executor.run(dag)

        # Both branches were attempted
        assert "good_branch" in mock.executed
        assert "bad_branch" in mock.executed

        # The good branch output is in context
        assert result.final_context.get("good_branch_out") == "good_result"

        # The parallel node itself recorded the failure
        parallel_node_result = next(r for r in result.node_results if r.node_id == NodeID("parallel"))
        assert parallel_node_result.success is False
        assert "bad_branch" in (parallel_node_result.error or "")

    @pytest.mark.asyncio
    async def test_parallel_failure_halts_dag_when_retry_disabled(self) -> None:
        """With retry_on_failure=False, partial parallel failure stops the DAG."""
        mock = MockNodeExecutor(
            node_results={
                "ok": NodeResult(node_id=NodeID("ok"), success=True, output="ok"),
                "fail": NodeResult(node_id=NodeID("fail"), success=False, error="boom"),
            }
        )

        dag = _build_parallel_dag(
            parallel_node_ids=["ok", "fail"],
            retry_on_failure=False,
        )
        executor = DAGExecutor(node_executor=mock)
        result = await executor.run(dag)

        assert not result.success


class TestParallelContextIsolation:
    """Parallel branches must not corrupt each other's context."""

    @pytest.mark.asyncio
    async def test_parallel_context_isolation(self) -> None:
        """Parallel branches writing to different keys don't interfere."""
        mock = MockNodeExecutor(
            node_results={
                "writer_a": NodeResult(
                    node_id=NodeID("writer_a"),
                    success=True,
                    output={"key_a": "value_a"},
                ),
                "writer_b": NodeResult(
                    node_id=NodeID("writer_b"),
                    success=True,
                    output={"key_b": "value_b"},
                ),
            }
        )

        dag = _build_parallel_dag(
            parallel_node_ids=["writer_a", "writer_b"],
            post_node_id="verifier",
        )
        executor = DAGExecutor(node_executor=mock)
        result = await executor.run(
            dag,
            initial_context=Context(data={"shared_key": "original"}),
        )

        assert result.success
        # Original context preserved
        assert result.final_context.get("shared_key") == "original"
        # Each branch's output present via output_key
        assert result.final_context.get("writer_a_out") == {"key_a": "value_a"}
        assert result.final_context.get("writer_b_out") == {"key_b": "value_b"}


class TestManyParallelNodes:
    """Stress test with 10+ parallel nodes."""

    @pytest.mark.asyncio
    async def test_many_parallel_nodes(self) -> None:
        """Stress test: 15 parallel nodes all execute and merge correctly."""
        node_ids = [f"node_{i}" for i in range(15)]
        mock = MockNodeExecutor()

        dag = _build_parallel_dag(
            parallel_node_ids=node_ids,
            post_node_id="aggregator",
        )
        executor = DAGExecutor(node_executor=mock)
        result = await executor.run(
            dag,
            initial_context=Context(data={"test": "stress"}),
        )

        assert result.success

        # All 15 child nodes + aggregator executed
        for nid in node_ids:
            assert nid in mock.executed, f"{nid} was not executed"
            assert result.final_context.get(f"{nid}_out") == f"success_{nid}"

        assert "aggregator" in mock.executed
        assert result.final_context.get("test") == "stress"

        # Parallel results dict should have all 15 entries
        parallel_results = result.final_context.get("parallel_results")
        assert parallel_results is not None
        assert len(parallel_results) == 15

    @pytest.mark.asyncio
    async def test_many_parallel_with_mixed_failures(self) -> None:
        """Stress test: some of many parallel nodes fail, others succeed."""
        node_ids = [f"node_{i}" for i in range(10)]
        failing_ids = {"node_2", "node_5", "node_8"}

        node_results = {}
        for nid in node_ids:
            if nid in failing_ids:
                node_results[nid] = NodeResult(
                    node_id=NodeID(nid),
                    success=False,
                    error=f"{nid} failed",
                )
            else:
                node_results[nid] = NodeResult(
                    node_id=NodeID(nid),
                    success=True,
                    output=f"output_{nid}",
                )

        mock = MockNodeExecutor(node_results=node_results)
        dag = _build_parallel_dag(parallel_node_ids=node_ids)
        executor = DAGExecutor(node_executor=mock)
        result = await executor.run(dag)

        # All 10 nodes were attempted
        for nid in node_ids:
            assert nid in mock.executed

        # The parallel node records its failures even if DAG continues
        parallel_node_result = next(r for r in result.node_results if r.node_id == NodeID("parallel"))
        assert parallel_node_result.success is False
        for fid in failing_ids:
            assert fid in (parallel_node_result.error or "")

        # Successful branches still produced output
        for nid in node_ids:
            if nid not in failing_ids:
                assert result.final_context.get(f"{nid}_out") == f"output_{nid}"
