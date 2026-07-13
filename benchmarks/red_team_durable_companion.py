"""Adversarial durability tests for the disposable-worker companion claim.

Unlike the positive load profile, this harness uses real subprocesses and
deliberately searches for unsafe outcomes. It reports BROKEN when an invariant
fails; it does not turn known gaps into successful durability claims.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cemaf.context.context import Context
from cemaf.context.patch import ContextPatch, PatchSource
from cemaf.core.enums import RunStatus
from cemaf.core.types import RunID
from cemaf.observability.run_logger import FileRunLogger, RunRecord
from cemaf.orchestration.checkpointer import CheckpointingDAGExecutor, DAGCheckpoint
from cemaf.orchestration.executor import DAGExecutor
from cemaf.orchestration.file_checkpointer import FileCheckpointer
from cemaf.orchestration.results import NodeResult
from cemaf.orchestration.services import RuntimeServices
from cemaf.replay.replayer import Replayer, ReplayMode
from examples.app_shapes.disposable_workers_durable_companion import build_pipeline


class ProcessNodeExecutor:
    """Domain executor with process-kill and duplicate-resume barriers."""

    def __init__(self, *, root: Path, worker_id: str, mode: str) -> None:
        self._root = root
        self._worker_id = worker_id
        self._mode = mode

    async def execute_node(self, node, context: Context) -> NodeResult:  # type: ignore[no-untyped-def]
        node_id = str(node.id)
        inputs = context.get("_resolved_inputs", {}) or {}

        if node_id == "ingest":
            output: Any = {"value": str(inputs["payload"]), "worker_id": self._worker_id}
        elif node_id == "transform":
            if self._mode == "block_for_kill":
                self._marker("transform-started")
                await asyncio.sleep(60)
                raise AssertionError("parent failed to terminate blocked worker")
            if self._mode == "race_resume":
                self._marker(f"ready-{self._worker_id}")
                release = self._root / "release-racers"
                while not release.exists():
                    await asyncio.sleep(0.005)
            source = inputs["ingested"]
            output = {"value": str(source["value"]).upper(), "worker_id": self._worker_id}
        elif node_id == "publish":
            transformed = inputs["transformed"]
            with (self._root / "external-effects.log").open("a", encoding="utf-8") as handle:
                handle.write(f"{self._worker_id}:{transformed['value']}\n")
                handle.flush()
                os.fsync(handle.fileno())
            output = {"value": transformed["value"], "worker_id": self._worker_id}
        else:
            return NodeResult(node_id=node.id, success=False, error=f"unknown node {node_id}")

        return NodeResult(
            node_id=node.id,
            success=True,
            output=output,
            metadata={"_context_output": output},
        )

    def _marker(self, name: str) -> None:
        (self._root / name).write_text(self._worker_id, encoding="utf-8")


async def _worker_main(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    run_id = RunID(args.run_id)
    checkpointer = FileCheckpointer(root / "checkpoints", max_checkpoints=0)
    initial = Context(data={"workflow_run_id": str(run_id), "payload": f"payload-{run_id}"})
    trace_initial = initial
    if args.action == "resume":
        checkpoint = await checkpointer.load(run_id)
        if checkpoint is None:
            raise RuntimeError(f"missing checkpoint for {run_id}")
        trace_initial = checkpoint.context
    logger = FileRunLogger(root=root / "traces")
    logger.start_run(
        f"{run_id}__{args.worker_id}",
        dag_name="disposable-worker-pipeline",
        initial_context=trace_initial,
    )
    base = DAGExecutor(
        node_executor=ProcessNodeExecutor(root=root, worker_id=args.worker_id, mode=args.mode),
        services=RuntimeServices(run_logger=logger),
    )
    executor = CheckpointingDAGExecutor(
        base_executor=base,
        checkpointer=checkpointer,
        checkpoint_interval=1,
    )
    result = (
        await executor.run(build_pipeline(), initial, run_id)
        if args.action == "run"
        else await executor.resume(run_id, build_pipeline())
    )
    logger.end_run(
        final_context=result.final_context,
        success=result.status == RunStatus.COMPLETED,
        error=result.error,
    )
    (root / f"result-{args.worker_id}.json").write_text(
        json.dumps(
            {
                "status": result.status.value,
                "error": result.error,
                "context": result.final_context.to_checkpoint_dict(),
            }
        ),
        encoding="utf-8",
    )


def _spawn_worker(
    *,
    root: Path,
    run_id: str,
    worker_id: str,
    action: str,
    mode: str,
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "_worker",
            "--root",
            str(root),
            "--run-id",
            run_id,
            "--worker-id",
            worker_id,
            "--action",
            action,
            "--mode",
            mode,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _wait_for(path: Path, *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise TimeoutError(f"timed out waiting for {path}")


def _communicate(process: subprocess.Popen[str], *, timeout: float = 15.0) -> tuple[str, str]:
    stdout, stderr = process.communicate(timeout=timeout)
    return stdout, stderr


def _kill_after_checkpoint(*, root: Path, run_id: str, worker_id: str) -> dict[str, Any]:
    process = _spawn_worker(
        root=root,
        run_id=run_id,
        worker_id=worker_id,
        action="run",
        mode="block_for_kill",
    )
    _wait_for(root / "transform-started")
    checkpoint_path = root / "checkpoints" / f"{run_id}.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    process.send_signal(signal.SIGKILL)
    _communicate(process)
    return {
        "exit_code": process.returncode,
        "checkpoint_status": checkpoint["status"],
        "completed_nodes": checkpoint["completed_nodes"],
        "checkpoint_parseable": True,
    }


def _load_trace_replay(*, root: Path, run_id: str, worker_id: str) -> bool:
    trace_path = root / "traces" / f"live__{run_id}__{worker_id}" / "run_record.json"
    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    record = RunRecord.from_dict(payload)
    replay = asyncio.run(Replayer(record).replay(mode=ReplayMode.PATCH_ONLY))
    return bool(
        replay.success
        and record.final_context is not None
        and replay.final_context.data == record.final_context.data
    )


def _single_owner_sigkill(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    run_id = "sigkill-run"
    killed = _kill_after_checkpoint(root=root, run_id=run_id, worker_id="dead-process")
    replacement = _spawn_worker(
        root=root,
        run_id=run_id,
        worker_id="replacement-process",
        action="resume",
        mode="normal",
    )
    stdout, stderr = _communicate(replacement)
    result_path = root / "result-replacement-process.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}
    effects = (root / "external-effects.log").read_text(encoding="utf-8").splitlines()
    trace_replay = _load_trace_replay(
        root=root,
        run_id=run_id,
        worker_id="replacement-process",
    )
    survived = (
        killed["exit_code"] == -signal.SIGKILL
        and killed["completed_nodes"] == ["ingest"]
        and replacement.returncode == 0
        and result.get("status") == RunStatus.COMPLETED.value
        and len(effects) == 1
        and trace_replay
    )
    return {
        "status": "SURVIVED" if survived else "BROKEN",
        "killed_process": killed,
        "replacement_exit_code": replacement.returncode,
        "external_side_effects": len(effects),
        "durable_trace_replay": trace_replay,
        "stderr": stderr[-500:],
        "stdout": stdout[-500:],
    }


def _duplicate_resume(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    run_id = "duplicate-resume-run"
    _kill_after_checkpoint(root=root, run_id=run_id, worker_id="dead-process")
    (root / "transform-started").unlink(missing_ok=True)

    racers = [
        _spawn_worker(
            root=root,
            run_id=run_id,
            worker_id=f"racer-{index}",
            action="resume",
            mode="race_resume",
        )
        for index in range(2)
    ]
    for index in range(2):
        _wait_for(root / f"ready-racer-{index}")
    (root / "release-racers").write_text("go", encoding="utf-8")
    process_output = [_communicate(process) for process in racers]
    effects_path = root / "external-effects.log"
    effects = effects_path.read_text(encoding="utf-8").splitlines() if effects_path.exists() else []
    completed_results = 0
    for index in range(2):
        result_path = root / f"result-racer-{index}.json"
        if result_path.exists():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            completed_results += result.get("status") == RunStatus.COMPLETED.value

    safe = len(effects) == 1 and completed_results == 1
    return {
        "status": "SURVIVED" if safe else "BROKEN",
        "external_side_effects": len(effects),
        "completed_resumers": completed_results,
        "exit_codes": [process.returncode for process in racers],
        "stderr": [stderr[-500:] for _, stderr in process_output],
    }


def _broken_write(self: Path, data: str, encoding: str | None = None, **_: Any) -> int:
    with self.open("w", encoding=encoding or "utf-8") as handle:
        handle.write(data[:17])
        handle.flush()
        os.fsync(handle.fileno())
    raise OSError("injected process loss during write")


async def _checkpoint_interruption(root: Path) -> dict[str, Any]:
    checkpointer = FileCheckpointer(root / "checkpoints", max_checkpoints=0)
    run_id = RunID("torn-checkpoint")
    original = DAGCheckpoint(
        run_id=run_id,
        dag_name="red-team",
        status=RunStatus.RUNNING,
        completed_nodes=(),
        pending_nodes=(),
        context=Context(data={"version": 1}),
    )
    await checkpointer.save(original)
    newer = DAGCheckpoint(
        run_id=run_id,
        dag_name="red-team",
        status=RunStatus.RUNNING,
        completed_nodes=(),
        pending_nodes=(),
        context=Context(data={"version": 2}),
    )
    with patch.object(Path, "write_text", _broken_write):
        try:
            await checkpointer.save(newer)
        except OSError:
            pass

    old_checkpoint_survived = False
    try:
        loaded = await checkpointer.load(run_id)
        old_checkpoint_survived = bool(loaded and loaded.context.get("version") == 1)
    except json.JSONDecodeError:
        pass
    return {
        "status": "SURVIVED" if old_checkpoint_survived else "BROKEN",
        "last_good_checkpoint_preserved": old_checkpoint_survived,
    }


def _trace_interruption(root: Path) -> dict[str, Any]:
    logger = FileRunLogger(root=root / "traces")
    logger.start_run("torn-trace", dag_name="red-team", initial_context=Context())
    patch_item = ContextPatch.set(
        "step",
        1,
        source=PatchSource.SYSTEM,
        reason="red-team interrupted trace write",
    )
    with patch.object(Path, "write_text", _broken_write):
        try:
            logger.record_patch(patch_item)
        except OSError:
            pass
    live_path = logger.get_run_dir("torn-trace") / "run_record.live.json"
    last_good_trace_survived = False
    try:
        payload = json.loads(live_path.read_text(encoding="utf-8"))
        last_good_trace_survived = payload.get("patches") == []
    except json.JSONDecodeError:
        pass
    return {
        "status": "SURVIVED" if last_good_trace_survived else "BROKEN",
        "last_good_trace_preserved": last_good_trace_survived,
    }


def run_red_team(root: str | Path) -> dict[str, Any]:
    """Run destructive scenarios and report the strong claim truthfully."""
    base = Path(root).resolve()
    results = {
        "single_owner_sigkill_recovery": _single_owner_sigkill(base / "sigkill"),
        "duplicate_resume_exactly_once": _duplicate_resume(base / "duplicate"),
        "interrupted_checkpoint_write": asyncio.run(
            _checkpoint_interruption(base / "checkpoint-interruption")
        ),
        "interrupted_trace_write": _trace_interruption(base / "trace-interruption"),
    }
    broken = [name for name, result in results.items() if result["status"] == "BROKEN"]
    return {
        "overall": "BROKEN" if broken else "SURVIVED",
        "broken_invariants": broken,
        "results": results,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    worker = subparsers.add_parser("_worker")
    worker.add_argument("--root", required=True)
    worker.add_argument("--run-id", required=True)
    worker.add_argument("--worker-id", required=True)
    worker.add_argument("--action", choices=("run", "resume"), required=True)
    worker.add_argument("--mode", choices=("normal", "block_for_kill", "race_resume"), required=True)
    parser.add_argument("--root")
    return parser


def main() -> None:
    logging.getLogger("cemaf").setLevel(logging.WARNING)
    args = _parser().parse_args()
    if args.command == "_worker":
        asyncio.run(_worker_main(args))
        return
    if args.root:
        Path(args.root).mkdir(parents=True, exist_ok=True)
        result = run_red_team(args.root)
    else:
        with TemporaryDirectory(prefix="cemaf-red-team-") as root:
            result = run_red_team(root)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
