"""
Integration tests for DAG Orchestration: Replay, Checkpoints, Self-Healing, and Full Logging.
"""

import pytest

from cemaf.context.context import Context
from cemaf.context.patch import ContextPatch, PatchSource
from cemaf.core.enums import NodeType, RunStatus
from cemaf.core.execution import CancellationToken
from cemaf.core.recovery import AutoHealManager, RecoveryStrategy
from cemaf.core.result import Result
from cemaf.core.types import NodeID, RunID
from cemaf.observability.run_logger import InMemoryRunLogger
from cemaf.orchestration.checkpointer import CheckpointingDAGExecutor, InMemoryCheckpointer
from cemaf.orchestration.dag import DAG, Edge, Node
from cemaf.orchestration.distributed_dag_executor import DistributedDAGExecutor
from cemaf.orchestration.executor import DAGExecutor, NodeExecutor, NodeResult


class MockNodeExecutor(NodeExecutor):
    """Executes nodes by simply echoing their ID or failing if configured."""

    def __init__(self, fail_nodes: set[str] | None = None):
        self.fail_nodes = fail_nodes or set()
        self.execution_count = 0

    async def execute_node(self, node: Node, context: Context) -> NodeResult:
        self.execution_count += 1
        if node.id in self.fail_nodes:
            # Check if we should fail with a specific error for auto-heal
            error_type = "TokenLimitExceeded" if "heal" in node.id else "StandardError"
            return NodeResult(
                node_id=node.id,
                success=False,
                error=f"Node {node.id} failed",
                metadata={"exception_type": error_type},
            )
        return NodeResult(node_id=node.id, success=True, output=f"Output from {node.id}")


class DAGSummarizeRecovery(RecoveryStrategy):
    """Recovery strategy that fixes a failing node by modifying context."""

    def recover(self, error_result: Result, context: Context) -> Result[Context]:
        # Fix the 'heal_node' failure by setting a flag the node might need
        # Use apply() with a patch to ensure it's recorded in the timeline
        patch = ContextPatch.set(
            "recovered_by_auto_heal", True, source=PatchSource.SYSTEM, reason="auto_heal"
        )
        new_ctx = context.apply(patch)
        return Result.ok(new_ctx)


@pytest.mark.asyncio
async def test_distributed_executor_propagates_cancellation_through_checkpointing():
    dag = DAG(name="cancelled_checkpointed").add_node(
        Node(
            id=NodeID("work"),
            type=NodeType.TOOL,
            name="Work",
            ref_id="tool",
            retry_on_failure=False,
        )
    )
    node_exec = MockNodeExecutor()
    checkpointer = InMemoryCheckpointer()
    checkpointed = CheckpointingDAGExecutor(
        base_executor=DAGExecutor(node_executor=node_exec),
        checkpointer=checkpointer,
    )
    distributed = DistributedDAGExecutor(inner=checkpointed, n_workers=1)  # type: ignore[arg-type]
    token = CancellationToken()
    token.cancel("operator request")
    run_id = RunID("cancelled-run")

    await distributed.start_workers()
    try:
        result = await distributed.submit_dag(
            dag=dag,
            run_id=run_id,
            cancellation_token=token,
        )
    finally:
        await distributed.stop_workers()

    assert result.status == RunStatus.CANCELLED
    assert node_exec.execution_count == 0
    checkpoint = await checkpointer.load(run_id)
    assert checkpoint is not None
    assert checkpoint.status == RunStatus.CANCELLED
    assert checkpoint.error == "Execution cancelled: operator request"


@pytest.mark.asyncio
async def test_dag_full_lifecycle_integration():
    """
    Scenario:
    1. Define a DAG with sequential and parallel nodes.
    2. Execute with Checkpointing and Full Logging.
    3. Simulate a failure in the middle.
    4. Verify the log (provenance) and checkpoint.
    5. Resume from checkpoint and verify completion.
    """
    # 1. Setup DAG
    # node1 -> [node2, node3] (parallel) -> node4
    dag = DAG(name="lifecycle_test")
    dag = dag.add_node(Node.tool("node1", "Node 1", "tool1", output_key="res1"))
    dag = dag.add_node(Node.tool("node2", "Node 2", "tool2", output_key="res2"))
    dag = dag.add_node(Node.tool("node3", "Node 3", "tool3", output_key="res3"))
    dag = dag.add_node(
        Node.parallel(
            "parallel_group",
            "Parallel",
            ["node2", "node3"],
            output_key="parallel_res",
        )
    )
    # Disable retry on failure for node4 to ensure it fails immediately and stops the DAG
    dag = dag.add_node(
        Node(
            id=NodeID("node4"),
            type=NodeType.TOOL,
            name="Node 4",
            ref_id="tool4",
            output_key="final_res",
            retry_on_failure=False,
        )
    )

    dag = dag.add_edge(Edge("node1", "parallel_group"))
    dag = dag.add_edge(Edge("parallel_group", "node4"))

    # Ensure topological sort includes node4
    assert "node4" in dag.topological_sort()

    # 2. Setup Infrastructure
    # We'll make node4 fail initially
    node_exec = MockNodeExecutor(fail_nodes={"node4"})
    run_logger = InMemoryRunLogger()
    checkpointer = InMemoryCheckpointer()
    auto_heal_manager = AutoHealManager()

    base_executor = DAGExecutor(
        node_executor=node_exec, run_logger=run_logger, auto_heal_manager=auto_heal_manager
    )

    executor = CheckpointingDAGExecutor(base_executor=base_executor, checkpointer=checkpointer)

    # 3. First Execution (Expect Failure at node4)
    # Note: CheckpointingDAGExecutor generates its own run_id if not provided,
    # but we can pass one to track it.
    run_id = RunID("ckpt_123")

    # We need to manually start the run record because CheckpointingDAGExecutor
    # doesn't call base_executor.run() directly, it calls internal methods.
    run_logger.start_run(str(run_id), dag_name=dag.name)

    result = await executor.run(dag, run_id=run_id)
    actual_run_id = result.run_id

    # End the run record manually as well
    run_logger.end_run(final_context=result.final_context, success=False, error=result.error)

    assert result.status == RunStatus.FAILED
    assert result.error == "Node node4 failed"

    # 4. Verify Logging & Checkpoints
    # The log should contain patches from node1, node2, node3
    # Try different ID formats if str() is weird
    record = run_logger.get_record(str(actual_run_id))
    if record is None:
        # Fallback check for all records
        history = run_logger.get_history()
        print(f"Available runs: {[r.run_id for r in history]}")
        # If still None, we might need to investigate if start_run was called

    assert record is not None
    # Patches: node1 output, node2 output, node3 output, parallel_group output
    # (Note: parallel group also emits a patch if output_key is set)
    patch_paths = [p.path for p in record.patches]
    assert "res1" in patch_paths
    assert "res2" in patch_paths
    assert "res3" in patch_paths

    # Checkpoint should exist and be resumable
    checkpoint = await checkpointer.load(run_id)
    assert checkpoint is not None
    assert checkpoint.status == RunStatus.FAILED
    assert checkpoint.failed_node == "node4"
    assert "res1" in checkpoint.context.data

    # 5. Resume and Complete
    # Fix the executor so node4 succeeds
    node_exec.fail_nodes.remove("node4")

    # Start new run record for resume
    run_logger.start_run(str(actual_run_id) + "_resume", dag_name=dag.name)

    resume_result = await executor.resume(actual_run_id, dag)

    run_logger.end_run(final_context=resume_result.final_context, success=True)

    assert resume_result.status == RunStatus.COMPLETED
    assert "final_res" in resume_result.final_context.data

    # Final log check
    final_record = run_logger.get_record(str(actual_run_id) + "_resume")
    assert "final_res" in [p.path for p in final_record.patches]


@pytest.mark.asyncio
async def test_dag_self_healing_integration():
    """
    Scenario:
    1. DAG node fails with a specific error.
    2. Executor (via AutoHealManager) catches it.
    3. Auto-Heal applies a strategy and retries the node.
    4. DAG completes successfully.
    """
    from cemaf.replay.replayer import Replayer, ReplayMode

    dag = DAG(name="heal_test")
    # node1 -> heal_node
    dag = dag.add_node(Node.tool("node1", "Node 1", "tool1", output_key="res1"))
    dag = dag.add_node(Node.tool("heal_node", "Heal Me", "tool_heal", output_key="healed"))
    dag = dag.add_edge(Edge("node1", "heal_node"))

    node_exec = MockNodeExecutor(fail_nodes={"heal_node"})
    run_logger = InMemoryRunLogger()
    manager = AutoHealManager()
    manager.register("TokenLimitExceeded", DAGSummarizeRecovery())

    executor = DAGExecutor(node_executor=node_exec, run_logger=run_logger, auto_heal_manager=manager)

    # 1. Run DAG - heal_node will fail, but executor will heal and retry
    # We need to make sure MockNodeExecutor stops failing after the first attempt
    # or handle it in the test.

    run_id = RunID("heal_run_123")

    # We'll use a side effect to fix the failure after the first attempt
    original_execute = node_exec.execute_node

    async def side_effect(node, context):
        res = await original_execute(node, context)
        if node.id == "heal_node":
            node_exec.fail_nodes.discard("heal_node")
        return res

    node_exec.execute_node = side_effect

    result = await executor.run(dag, run_id=run_id)

    assert result.status == RunStatus.COMPLETED
    assert result.final_context.get("recovered_by_auto_heal") is True
    assert result.final_context.get("healed") == "Output from heal_node"

    # 2. Verify Replay
    # Replay should be able to reproduce the final state from patches
    record = run_logger.get_record(str(run_id))
    assert record is not None

    replayer = Replayer(record)
    replay_result = await replayer.replay(mode=ReplayMode.PATCH_ONLY)

    assert replay_result.success
    assert replay_result.final_context.data == result.final_context.data

    # Verify provenance: we should see the 'auto_heal' patch
    auto_heal_patches = [p for p in record.patches if p.reason == "auto_heal"]
    assert len(auto_heal_patches) > 0
