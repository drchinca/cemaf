"""
Checkpointing - State persistence and recovery for DAG workflows.

Simplified design:
- DAGCheckpoint captures state at any point
- Checkpointer protocol for storage backends
- CheckpointingDAGExecutor wraps execution with checkpointing
"""

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from cemaf.context.context import Context  # New import
from cemaf.core.enums import RunStatus
from cemaf.core.storage import InMemoryStorage
from cemaf.core.types import NodeID, RunID
from cemaf.core.utils import generate_id


@dataclass(frozen=True)
class DAGCheckpoint:
    """
    Checkpoint for DAG execution state.

    Captures everything needed to resume execution.
    """

    run_id: RunID
    dag_name: str
    status: RunStatus
    completed_nodes: tuple[NodeID, ...] = ()
    pending_nodes: tuple[NodeID, ...] = ()
    context: Context = field(default_factory=Context)  # Updated to Context
    error: str | None = None
    failed_node: NodeID | None = None

    def can_resume(self) -> bool:
        """Check if this checkpoint can be resumed."""
        return self.status in (RunStatus.RUNNING, RunStatus.PENDING, RunStatus.FAILED)


@runtime_checkable
class Checkpointer(Protocol):
    """Protocol for checkpoint storage backends."""

    async def save(self, checkpoint: DAGCheckpoint) -> None:
        """Save a checkpoint."""
        ...

    async def load(self, run_id: RunID) -> DAGCheckpoint | None:
        """Load a checkpoint by run ID."""
        ...

    async def delete(self, run_id: RunID) -> bool:
        """Delete a checkpoint."""
        ...


class InMemoryCheckpointer:
    """In-memory checkpointer using generic storage."""

    def __init__(self) -> None:
        self._store: InMemoryStorage[RunID, DAGCheckpoint] = InMemoryStorage()

    async def save(self, checkpoint: DAGCheckpoint) -> None:
        await self._store.set(checkpoint.run_id, checkpoint)

    async def load(self, run_id: RunID) -> DAGCheckpoint | None:
        return await self._store.get(run_id)

    async def delete(self, run_id: RunID) -> bool:
        return await self._store.delete(run_id)

    async def clear(self) -> None:
        await self._store.clear()


class CheckpointingDAGExecutor:
    """
    DAG executor with checkpointing.

    Wraps a base executor to add checkpoint save/resume capability.

    Usage:
        executor = CheckpointingDAGExecutor(base_executor, checkpointer)
        result = await executor.run(dag, context)

        # Later, resume from failure
        result = await executor.resume(run_id, dag)
    """

    def __init__(
        self,
        base_executor: Any,
        checkpointer: Checkpointer,
        checkpoint_interval: int = 1,
        checkpoint_on_failure: bool = True,
    ) -> None:
        self._executor = base_executor
        self._checkpointer = checkpointer
        self._interval = checkpoint_interval
        self._checkpoint_on_failure = checkpoint_on_failure

    async def run(
        self,
        dag: Any,
        initial_context: Context | None = None,  # Updated to Context
        run_id: RunID | None = None,
    ) -> Any:
        """Run DAG with checkpointing."""
        dag.validate()
        order = dag.topological_sort()
        run_id = run_id or RunID(generate_id("ckpt"))

        context = initial_context or Context()  # Initialize Context

        # Save initial checkpoint
        await self._checkpointer.save(
            DAGCheckpoint(
                run_id=run_id,
                dag_name=dag.name,
                status=RunStatus.RUNNING,
                pending_nodes=order,
                context=context,  # Pass Context object
            )
        )

        return await self._execute_nodes(
            dag=dag,
            run_id=run_id,
            nodes_to_execute=order,
            initial_context=context,  # Pass Context object
            completed_nodes=[],
        )

    async def resume(self, run_id: RunID, dag: Any) -> Any:
        """Resume execution from a checkpoint."""
        checkpoint = await self._checkpointer.load(run_id)

        if not checkpoint:
            raise ValueError(f"No checkpoint found for {run_id}")
        if not checkpoint.can_resume():
            raise ValueError(f"Cannot resume: status={checkpoint.status}")
        if checkpoint.dag_name != dag.name:
            raise ValueError(f"DAG mismatch: {checkpoint.dag_name} != {dag.name}")

        return await self._execute_nodes(
            dag=dag,
            run_id=run_id,
            nodes_to_execute=list(checkpoint.pending_nodes),
            initial_context=checkpoint.context,  # Pass Context object
            completed_nodes=list(checkpoint.completed_nodes),
        )

    async def _execute_nodes(
        self,
        dag: Any,
        run_id: RunID,
        nodes_to_execute: list[NodeID],
        initial_context: Context,  # Updated to Context
        completed_nodes: list[NodeID],
    ) -> Any:
        """
        Core execution loop - shared by run() and resume().

        This is the single source of truth for node execution with checkpointing.
        """
        from cemaf.orchestration.executor import ExecutionResult, NodeResult

        context = initial_context  # Use Context directly
        node_results: list[NodeResult] = []
        nodes_since_checkpoint = 0

        try:
            for node_id in nodes_to_execute:
                node = dag.get_node(node_id)
                if not node:
                    continue

                # Execute node and get updated context
                result, context = await self._executor._execute_with_retry(
                    node, context
                )  # Context is updated here

                node_results.append(result)
                completed_nodes.append(node_id)
                nodes_since_checkpoint += 1

                # Checkpoint at interval
                if nodes_since_checkpoint >= self._interval:
                    await self._save_checkpoint(
                        run_id,
                        dag.name,
                        RunStatus.RUNNING,
                        completed_nodes,
                        nodes_to_execute,
                        context,
                    )
                    nodes_since_checkpoint = 0

                # Handle failure
                if not result.success:
                    if self._checkpoint_on_failure:
                        await self._save_checkpoint(
                            run_id,
                            dag.name,
                            RunStatus.FAILED,
                            completed_nodes,
                            nodes_to_execute,
                            context,
                            error=result.error,
                            failed_node=node_id,
                        )

                    if not node.retry_on_failure:
                        # Return final context here too
                        return ExecutionResult(
                            run_id=run_id,
                            dag_name=dag.name,
                            status=RunStatus.FAILED,
                            node_results=tuple(node_results),
                            final_context=context,
                            error=result.error,
                        )

            # Success
            await self._save_checkpoint(
                run_id,
                dag.name,
                RunStatus.COMPLETED,
                completed_nodes,
                [],
                context,
            )

            return ExecutionResult(
                run_id=run_id,
                dag_name=dag.name,
                status=RunStatus.COMPLETED,
                node_results=tuple(node_results),
                final_context=context,
            )

        except Exception as e:
            if self._checkpoint_on_failure:
                await self._save_checkpoint(
                    run_id,
                    dag.name,
                    RunStatus.FAILED,
                    completed_nodes,
                    nodes_to_execute,
                    context,
                    error=str(e),
                )

            return ExecutionResult(
                run_id=run_id,
                dag_name=dag.name,
                status=RunStatus.FAILED,
                node_results=tuple(node_results),
                final_context=context,
                error=str(e),
            )

    async def _save_checkpoint(
        self,
        run_id: RunID,
        dag_name: str,
        status: RunStatus,
        completed: list[NodeID],
        pending: list[NodeID],
        context: Context,  # Updated to Context
        error: str | None = None,
        failed_node: NodeID | None = None,
    ) -> None:
        """Save checkpoint - single method for all checkpoint saves."""
        remaining = [n for n in pending if n not in completed]
        await self._checkpointer.save(
            DAGCheckpoint(
                run_id=run_id,
                dag_name=dag_name,
                status=status,
                completed_nodes=tuple(completed),
                pending_nodes=tuple(remaining),
                context=context,
                error=error,
                failed_node=failed_node,
            )
        )
