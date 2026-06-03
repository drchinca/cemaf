"""Characterization test: what DAGExecutor.run().success actually means.

Surfaced while writing the state→DAG bridge test (PR #121): a leaf node can
report success=False while the overall run reports success=True. This is NOT a
bug — it's the documented contract, pinned here so no caller mistakes
`result.success` for "every node succeeded".

The contract (executor.py ~line 809 + 902):
- A failed node with retry_on_failure=False (or NodeType-specific hard-stop)
  short-circuits the run to RunStatus.FAILED → result.success is False.
- A failed node with retry_on_failure=True (the Node.tool() DEFAULT) does NOT
  fail the run: downstream traversal stops, but the run reaches
  RunStatus.COMPLETED → result.success is True, with the failed node's
  NodeResult.success=False sitting in result.node_results.

Therefore: callers that need "all nodes succeeded" MUST inspect node_results,
not just result.success. (This is exactly what the engagement onboarding
handler and the state→DAG bridge handler do.)
"""

from __future__ import annotations

import pytest

from cemaf.context.context import Context
from cemaf.core.enums import NodeType
from cemaf.core.types import NodeID
from cemaf.orchestration.dag import DAG, Edge, Node
from cemaf.orchestration.executor import DAGExecutor, NodeResult


class _FailNodes:
    """Node executor that fails a configured set of node ids."""

    def __init__(self, fail: set[str]) -> None:
        self._fail = fail

    async def execute_node(self, node: Node, context: Context) -> NodeResult:
        if node.id in self._fail:
            return NodeResult(node_id=NodeID(node.id), success=False, error="boom")
        return NodeResult(node_id=NodeID(node.id), success=True, output=f"ok_{node.id}")


def _linear_dag(*, retry_on_failure: bool) -> DAG:
    """A→B→C; the middle/leaf nodes carry the given retry_on_failure flag."""
    dag = DAG(name="lin")
    dag = dag.add_node(Node.tool(id="a", name="A", tool_id="t", output_key="a"))
    dag = dag.add_node(
        Node(id=NodeID("b"), type=NodeType.TOOL, name="B", ref_id="t", retry_on_failure=retry_on_failure)
    )
    dag = dag.add_node(Node.tool(id="c", name="C", tool_id="t", output_key="c"))
    dag = dag.add_edge(Edge(source=NodeID("a"), target=NodeID("b")))
    dag = dag.add_edge(Edge(source=NodeID("b"), target=NodeID("c")))
    return dag


@pytest.mark.asyncio
async def test_failed_node_with_retry_default_still_reports_run_success() -> None:
    """DEFAULT retry_on_failure=True: a failed node does NOT fail the run."""
    executor = DAGExecutor(node_executor=_FailNodes(fail={"b"}))
    result = await executor.run(_linear_dag(retry_on_failure=True), initial_context=Context(data={}))

    # The run "completed" — this is the surprising-but-intended part.
    assert result.success is True
    # ...yet a node inside it failed. The truth lives in node_results.
    failed = [nr for nr in result.node_results if not nr.success]
    assert any(nr.node_id == "b" for nr in failed)


@pytest.mark.asyncio
async def test_failed_node_with_retry_disabled_fails_the_run() -> None:
    """retry_on_failure=False: a failed node short-circuits the run to FAILED."""
    executor = DAGExecutor(node_executor=_FailNodes(fail={"b"}))
    result = await executor.run(_linear_dag(retry_on_failure=False), initial_context=Context(data={}))

    assert result.success is False


@pytest.mark.asyncio
async def test_all_nodes_succeed_reports_success_with_no_failed_results() -> None:
    """Sanity baseline: a clean run is success=True AND every node succeeded."""
    executor = DAGExecutor(node_executor=_FailNodes(fail=set()))
    result = await executor.run(_linear_dag(retry_on_failure=True), initial_context=Context(data={}))

    assert result.success is True
    assert all(nr.success for nr in result.node_results)


@pytest.mark.asyncio
async def test_strict_all_nodes_succeeded_predicate_is_the_safe_caller_check() -> None:
    """The predicate callers SHOULD use when they mean 'every node succeeded'."""
    executor = DAGExecutor(node_executor=_FailNodes(fail={"b"}))
    result = await executor.run(_linear_dag(retry_on_failure=True), initial_context=Context(data={}))

    all_nodes_ok = result.success and all(nr.success for nr in result.node_results)
    # result.success alone would be True (misleading); the strict predicate catches it.
    assert all_nodes_ok is False
