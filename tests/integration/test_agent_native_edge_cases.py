"""
Integration tests for edge cases in Agent-Native features.
Testing the boundaries of Time-Travel, Auto-Heal, and Semantic Caching.
"""

import asyncio

import pytest

from cemaf.context.context import Context
from cemaf.core.enums import NodeType, RunStatus
from cemaf.core.recovery import AutoHealManager, RecoveryStrategy
from cemaf.core.result import Result
from cemaf.core.types import NodeID, RunID
from cemaf.orchestration.checkpointer import CheckpointingDAGExecutor, InMemoryCheckpointer
from cemaf.orchestration.dag import DAG, Edge, Node
from cemaf.orchestration.executor import DAGExecutor, NodeExecutor, NodeResult


class FailAlwaysExecutor(NodeExecutor):
    """Executor that always fails, testing the limits of recovery."""

    async def execute_node(self, node: Node, context: Context) -> NodeResult:
        return NodeResult(
            node_id=node.id,
            success=False,
            error="Infinite failure",
            metadata={"exception_type": "PermanentError"},
        )


class CyclicRecovery(RecoveryStrategy):
    """A recovery strategy that doesn't actually fix the problem, testing for infinite loops."""

    def recover(self, error_result: Result, context: Context) -> Result[Context]:
        # Just add a dummy flag, doesn't fix "PermanentError"
        return Result.ok(context.set("tried_to_heal", True))

    @pytest.mark.asyncio
    async def test_auto_heal_infinite_loop_prevention():
        """
        Edge Case: What if recovery doesn't work and the node keeps failing?
        The executor should eventually give up based on max_retries.
        """
        dag = DAG(name="infinite_fail_test")
        # Set max_retries to something small
        node = Node(
            id=NodeID("fail_node"), type=NodeType.TOOL, name="Fail Node", max_retries=2, retry_on_failure=True
        )
        dag = dag.add_node(node)

        node_exec = FailAlwaysExecutor()
        manager = AutoHealManager()
        manager.register("PermanentError", CyclicRecovery())

        executor = DAGExecutor(node_executor=node_exec, auto_heal_manager=manager)

        # This should NOT run forever. It should fail after 2 attempts + recovery attempts.
        # Note: In the current implementation, 'continue' after heal provides a 'free' retry.
        # We verify that it eventually stops.
        try:
            result = await asyncio.wait_for(executor.run(dag), timeout=2.0)
            assert result.status == RunStatus.FAILED
            assert "Infinite failure" in result.error
        except TimeoutError:
            pytest.fail("Executor ran forever in an infinite auto-heal loop!")


@pytest.mark.asyncio
async def test_time_travel_invalid_patch_id():
    """
    Edge Case: Rolling back to a non-existent patch ID.
    """
    ctx = Context(data={"a": 1})
    with pytest.raises(ValueError, match="Patch ID 'invalid' not found"):
        ctx.rollback_to("invalid")


@pytest.mark.asyncio
async def test_semantic_cache_empty_context():
    """
    Edge Case: Caching and retrieving an empty context.
    """
    from cemaf.cache.semantic import SemanticStateCache
    from cemaf.retrieval.memory_store import InMemoryVectorStore
    from tests.integration.test_agent_native_features import SimpleEmbeddingProvider

    ep = SimpleEmbeddingProvider()
    vs = InMemoryVectorStore(embedding_provider=ep)
    cache = SemanticStateCache(vs, ep)

    ctx = Context()
    await cache.set(ctx)

    hit = await cache.get(Context())
    assert hit is not None
    assert hit.data == {}


@pytest.mark.asyncio
async def test_checkpoint_resume_with_context_mutation():
    """
    Edge Case: Resume a DAG where the context was manually 'tampered' with
    between failure and resume.
    """
    dag = DAG(name="tamper_test")
    dag = dag.add_node(Node.tool("n1", "N1", "t1", output_key="k1"))
    dag = dag.add_node(Node(id=NodeID("n2"), type=NodeType.TOOL, name="N2", retry_on_failure=False))
    dag = dag.add_edge(Edge("n1", "n2"))

    class TamperExecutor(NodeExecutor):
        async def execute_node(self, node: Node, context: Context) -> NodeResult:
            if node.id == "n2" and not context.get("tampered"):
                return NodeResult(node_id=node.id, success=False, error="Fail for tamper")
            return NodeResult(node_id=node.id, success=True, output="ok")

    node_exec = TamperExecutor()
    checkpointer = InMemoryCheckpointer()
    base_executor = DAGExecutor(node_executor=node_exec)
    executor = CheckpointingDAGExecutor(base_executor, checkpointer)

    run_id = RunID("tamper_run")
    await executor.run(dag, run_id=run_id)

    # Manually tamper with the checkpoint context
    ckpt = await checkpointer.load(run_id)
    tampered_ctx = ckpt.context.set("tampered", True)

    from cemaf.orchestration.checkpointer import DAGCheckpoint

    new_ckpt = DAGCheckpoint(
        run_id=ckpt.run_id,
        dag_name=ckpt.dag_name,
        status=ckpt.status,
        completed_nodes=ckpt.completed_nodes,
        pending_nodes=ckpt.pending_nodes,
        context=tampered_ctx,
        failed_node=ckpt.failed_node,
    )
    await checkpointer.save(new_ckpt)

    # Resume - should now succeed because of the tampered context
    result = await executor.resume(run_id, dag)
    assert result.status == RunStatus.COMPLETED
    assert result.final_context.get("tampered") is True
