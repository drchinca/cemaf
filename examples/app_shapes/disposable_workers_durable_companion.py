"""Disposable CEMAF workers backed by a durable companion service plane.

The worker owns no durable authority. Every first-attempt worker in this
example is terminated after its first node. A replacement worker reaches the
same file-backed checkpoint, resumes the DAG, heals a transient failure, and
finishes. Patch lineage and attempt traces remain replayable after both worker
objects are gone.

The companion is a bundle of CEMAF services, not an agent and not an
orchestrator on the hot path:

    3 disposable workers -> FileCheckpointer
                         -> FileRunLogger attempt traces
                         -> AutoHealManager recovery policy
                         -> Replayer verification

Run the heavier load profile with:

    uv run python benchmarks/stress_disposable_workers.py --runs 300 --workers 3
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any

from cemaf.context.context import Context
from cemaf.context.patch import ContextPatch, PatchSource
from cemaf.core.enums import NodeType, RunStatus
from cemaf.core.recovery import AutoHealManager, RecoveryStrategy
from cemaf.core.result import Result
from cemaf.core.types import NodeID, RunID
from cemaf.observability.run_logger import FileRunLogger, RunRecord
from cemaf.orchestration.checkpointer import CheckpointingDAGExecutor
from cemaf.orchestration.dag import DAG, Edge, Node
from cemaf.orchestration.executor import DAGExecutor
from cemaf.orchestration.file_checkpointer import FileCheckpointer
from cemaf.orchestration.results import ExecutionResult, NodeResult
from cemaf.orchestration.services import RuntimeServices
from cemaf.replay.replayer import Replayer, ReplayMode


class ReplacementRecovery(RecoveryStrategy):
    """Persist the deterministic recovery decision in context lineage."""

    def __init__(self, worker_id: str) -> None:
        self._worker_id = worker_id

    def recover(self, error_result: Result[Any], context: Context) -> Result[Context]:
        del error_result
        patch = ContextPatch.set(
            "recovery",
            {"healed": True, "worker_id": self._worker_id},
            source=PatchSource.SYSTEM,
            source_id="durable-companion",
            reason="replacement worker applied companion recovery policy",
            correlation_id=str(context.get("workflow_run_id", "")),
        )
        return Result.ok(context.apply(patch))


@dataclass(frozen=True)
class DurableCompanion:
    """Shared durable services reachable by any disposable worker."""

    root: Path
    checkpointer: FileCheckpointer

    @classmethod
    def create(cls, root: str | Path) -> DurableCompanion:
        durable_root = Path(root).resolve()
        durable_root.mkdir(parents=True, exist_ok=True)
        return cls(
            root=durable_root,
            checkpointer=FileCheckpointer(
                durable_root / "checkpoints",
                max_checkpoints=0,
            ),
        )

    @property
    def traces_root(self) -> Path:
        return self.root / "traces"

    def trace_logger(self) -> FileRunLogger:
        """Return a process-local writer targeting the shared trace store."""
        return FileRunLogger(root=self.traces_root)

    def recovery_manager(self, worker_id: str) -> AutoHealManager:
        manager = AutoHealManager()
        manager.register("TransientWorkerError", ReplacementRecovery(worker_id))
        return manager

    async def replay(self, run_id: RunID, initial_context: Context) -> bool:
        """Reconstruct final state solely from persisted patch lineage."""
        checkpoint = await self.checkpointer.load(run_id)
        if checkpoint is None:
            return False
        record = RunRecord(
            run_id=str(run_id),
            dag_name=checkpoint.dag_name,
            initial_context=initial_context,
            final_context=checkpoint.context,
            patches=list(checkpoint.context.get_timeline()),
        )
        replay = await Replayer(record).replay(mode=ReplayMode.PATCH_ONLY)
        return replay.success and replay.final_context.data == checkpoint.context.data


class PipelineNodeExecutor:
    """Domain work performed by one disposable worker process."""

    def __init__(
        self,
        *,
        worker_id: str,
        terminate_at: str | None = None,
        fail_publish_once: bool = False,
    ) -> None:
        self._worker_id = worker_id
        self._terminate_at = terminate_at
        self._fail_publish_once = fail_publish_once

    async def execute_node(self, node: Node, context: Context) -> NodeResult:
        if str(node.id) == self._terminate_at:
            raise asyncio.CancelledError(f"simulated loss of {self._worker_id}")

        inputs = context.get("_resolved_inputs", {}) or {}
        if str(node.id) == "ingest":
            output: Any = {
                "value": str(inputs["payload"]),
                "worker_id": self._worker_id,
            }
        elif str(node.id) == "transform":
            source = inputs["ingested"]
            output = {
                "value": str(source["value"]).upper(),
                "worker_id": self._worker_id,
            }
        elif str(node.id) == "publish":
            if self._fail_publish_once and not context.get("recovery.healed", False):
                self._fail_publish_once = False
                return NodeResult(
                    node_id=node.id,
                    success=False,
                    error="transient publish failure after worker replacement",
                    metadata={"exception_type": "TransientWorkerError"},
                )
            transformed = inputs["transformed"]
            output = {
                "value": transformed["value"],
                "worker_id": self._worker_id,
            }
        else:
            return NodeResult(node_id=node.id, success=False, error="unknown node")

        return NodeResult(
            node_id=node.id,
            success=True,
            output=output,
            metadata={"_context_output": output},
        )


class DisposableWorker:
    """One replaceable worker with no state needed by its successor."""

    def __init__(
        self,
        *,
        companion: DurableCompanion,
        worker_id: str,
        terminate_at: str | None = None,
        fail_publish_once: bool = False,
    ) -> None:
        self._companion = companion
        self.worker_id = worker_id
        self._logger = companion.trace_logger()
        services = RuntimeServices(
            run_logger=self._logger,
            auto_heal_manager=companion.recovery_manager(worker_id),
        )
        base = DAGExecutor(
            node_executor=PipelineNodeExecutor(
                worker_id=worker_id,
                terminate_at=terminate_at,
                fail_publish_once=fail_publish_once,
            ),
            services=services,
        )
        self._executor = CheckpointingDAGExecutor(
            base_executor=base,
            checkpointer=companion.checkpointer,
            checkpoint_interval=1,
        )

    async def execute(
        self,
        *,
        dag: DAG,
        run_id: RunID,
        initial_context: Context,
        resume: bool,
    ) -> ExecutionResult:
        attempt_id = f"{run_id}__{self.worker_id}"
        trace_initial = initial_context
        if resume:
            checkpoint = await self._companion.checkpointer.load(run_id)
            if checkpoint is None:
                raise RuntimeError(f"missing checkpoint for {run_id}")
            trace_initial = checkpoint.context

        self._logger.start_run(attempt_id, dag_name=dag.name, initial_context=trace_initial)
        current = self._logger.get_current_record()
        if current is not None:
            current.metadata.update(
                {
                    "workflow_run_id": str(run_id),
                    "worker_id": self.worker_id,
                    "resumed": resume,
                }
            )

        try:
            result = (
                await self._executor.resume(run_id, dag)
                if resume
                else await self._executor.run(dag, initial_context, run_id)
            )
        except asyncio.CancelledError:
            # Deliberately do not close the run. The live trace on disk is the
            # evidence left by the dead process.
            raise

        self._logger.end_run(
            final_context=result.final_context,
            success=result.status == RunStatus.COMPLETED,
            error=result.error,
        )
        return result


def build_pipeline() -> DAG:
    """Build the three-stage domain pipeline run by every worker."""
    nodes = (
        Node(
            id=NodeID("ingest"),
            type=NodeType.TOOL,
            name="Ingest",
            ref_id="ingest",
            input_mapping={"payload": "$$payload$$"},
            output_key="ingested",
            structured_output=True,
        ),
        Node(
            id=NodeID("transform"),
            type=NodeType.TOOL,
            name="Transform",
            ref_id="transform",
            input_mapping={"ingested": "$$ingested$$"},
            output_key="transformed",
            structured_output=True,
        ),
        Node(
            id=NodeID("publish"),
            type=NodeType.TOOL,
            name="Publish",
            ref_id="publish",
            input_mapping={"transformed": "$$transformed$$"},
            output_key="published",
            structured_output=True,
        ),
    )
    return DAG(
        name="disposable-worker-pipeline",
        nodes=nodes,
        edges=(
            Edge(source=NodeID("ingest"), target=NodeID("transform")),
            Edge(source=NodeID("transform"), target=NodeID("publish")),
        ),
        entry_node=NodeID("ingest"),
    )


async def _run_wave(
    *,
    companion: DurableCompanion,
    dag: DAG,
    run_ids: list[RunID],
    wave: int,
) -> list[tuple[RunID, Context, ExecutionResult]]:
    initial_contexts = [
        Context(data={"workflow_run_id": str(run_id), "payload": f"payload-{run_id}"}) for run_id in run_ids
    ]
    doomed = [
        DisposableWorker(
            companion=companion,
            worker_id=f"wave-{wave}-worker-{index}-dead",
            terminate_at="transform",
        )
        for index in range(len(run_ids))
    ]
    first_attempts = await asyncio.gather(
        *(
            worker.execute(
                dag=dag,
                run_id=run_id,
                initial_context=initial,
                resume=False,
            )
            for worker, run_id, initial in zip(doomed, run_ids, initial_contexts, strict=True)
        ),
        return_exceptions=True,
    )
    if not all(isinstance(item, asyncio.CancelledError) for item in first_attempts):
        raise AssertionError("every first-attempt worker must terminate after checkpointing")

    # Rebuild the service bundle from the durable root as a separate process
    # would. No Python object from the dead workers is needed for recovery.
    replacement_companion = DurableCompanion.create(companion.root)
    replacements = [
        DisposableWorker(
            companion=replacement_companion,
            worker_id=f"wave-{wave}-worker-{index}-replacement",
            fail_publish_once=True,
        )
        for index in range(len(run_ids))
    ]
    resumed = await asyncio.gather(
        *(
            worker.execute(
                dag=dag,
                run_id=run_id,
                initial_context=initial,
                resume=True,
            )
            for worker, run_id, initial in zip(
                replacements,
                run_ids,
                initial_contexts,
                strict=True,
            )
        )
    )
    return list(zip(run_ids, initial_contexts, resumed, strict=True))


async def run_experiment(
    *,
    root: str | Path,
    run_count: int = 12,
    worker_count: int = 3,
) -> dict[str, Any]:
    """Kill, replace, heal, replay, and verify a bounded load of pipelines."""
    if run_count < 1:
        raise ValueError("run_count must be positive")
    if worker_count not in (2, 3):
        raise ValueError("worker_count must be 2 or 3")

    companion = DurableCompanion.create(root)
    dag = build_pipeline()
    started = perf_counter()
    executions: list[tuple[RunID, Context, ExecutionResult]] = []

    for wave, offset in enumerate(range(0, run_count, worker_count)):
        run_ids = [
            RunID(f"pipeline-{index:05d}") for index in range(offset, min(offset + worker_count, run_count))
        ]
        executions.extend(
            await _run_wave(
                companion=companion,
                dag=dag,
                run_ids=run_ids,
                wave=wave,
            )
        )

    replay_matches = await asyncio.gather(
        *(companion.replay(run_id, initial) for run_id, initial, _ in executions)
    )
    checkpoints = [await companion.checkpointer.load(run_id) for run_id, _, _ in executions]
    completed = sum(result.status == RunStatus.COMPLETED for _, _, result in executions)
    healed = sum(
        bool(checkpoint and checkpoint.context.get("recovery.healed", False)) for checkpoint in checkpoints
    )
    patch_ids = [
        patch.id
        for checkpoint in checkpoints
        if checkpoint is not None
        for patch in checkpoint.context.get_timeline()
    ]
    trace_dirs = list(companion.traces_root.glob("live__*"))
    abandoned_traces = sum(
        (trace_dir / "run_record.live.json").is_file() and not (trace_dir / "run_record.json").is_file()
        for trace_dir in trace_dirs
    )
    elapsed_ms = (perf_counter() - started) * 1000

    summary = {
        "pipelines": run_count,
        "concurrent_workers": worker_count,
        "terminated_workers": run_count,
        "replacement_workers": run_count,
        "completed": completed,
        "healed": healed,
        "replay_matches": sum(replay_matches),
        "checkpoint_files": len(list((companion.root / "checkpoints").glob("*.json"))),
        "attempt_trace_dirs": len(trace_dirs),
        "abandoned_worker_traces": abandoned_traces,
        "lineage_patches": len(patch_ids),
        "unique_patch_ids": len(set(patch_ids)),
        "elapsed_ms": round(elapsed_ms, 3),
        "pipelines_per_second": round(run_count / (elapsed_ms / 1000), 2),
    }

    expected_patches_per_run = 4  # ingest, transform, recovery, publish
    assert completed == run_count
    assert healed == run_count
    assert all(replay_matches)
    assert summary["checkpoint_files"] == run_count
    assert summary["attempt_trace_dirs"] == run_count * 2
    assert abandoned_traces == run_count
    assert len(patch_ids) == run_count * expected_patches_per_run
    assert len(set(patch_ids)) == len(patch_ids)
    return summary


async def main() -> None:
    with TemporaryDirectory(prefix="cemaf-durable-companion-") as root:
        summary = await run_experiment(root=root, run_count=12, worker_count=3)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
