"""Tests for durable file-backed DAG checkpoints."""

import pytest

from cemaf.context.context import Context
from cemaf.context.patch import ContextPatch, PatchOperation, PatchSource
from cemaf.core.enums import RunStatus
from cemaf.core.types import NodeID, RunID
from cemaf.orchestration.checkpointer import DAGCheckpoint
from cemaf.orchestration.file_checkpointer import FileCheckpointer, checkpoint_from_dict, checkpoint_to_dict


@pytest.mark.unit
@pytest.mark.asyncio
async def test_file_checkpointer_round_trip(tmp_path) -> None:
    patch = ContextPatch.set("build.manifest", {"files": ["a.py"]}, source=PatchSource.AGENT)
    context = Context().apply(patch)
    checkpoint = DAGCheckpoint(
        run_id=RunID("goal-session:demo"),
        dag_name="autonomy:demo",
        status=RunStatus.RUNNING,
        completed_nodes=(NodeID("step-1"),),
        pending_nodes=(NodeID("step-2"),),
        context=context,
    )

    store = FileCheckpointer(tmp_path / "checkpoints")
    await store.save(checkpoint)
    loaded = await store.load(RunID("goal-session:demo"))

    assert loaded is not None
    assert loaded.dag_name == "autonomy:demo"
    assert loaded.completed_nodes == (NodeID("step-1"),)
    assert loaded.context.get("build.manifest") == {"files": ["a.py"]}
    assert len(loaded.context.patch_history) == 1


def _checkpoint(run_id: str) -> DAGCheckpoint:
    return DAGCheckpoint(
        run_id=RunID(run_id),
        dag_name="dag",
        status=RunStatus.RUNNING,
        context=Context(),
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_save_prunes_to_max_checkpoints(tmp_path) -> None:
    store = FileCheckpointer(tmp_path / "ckpt", max_checkpoints=3)
    for i in range(5):
        await store.save(_checkpoint(f"run-{i}"))

    remaining = sorted(p.name for p in (tmp_path / "ckpt").glob("*.json"))
    assert len(remaining) == 3
    # oldest two runs pruned, newest three kept
    assert remaining == ["run-2.json", "run-3.json", "run-4.json"]
    assert await store.load(RunID("run-0")) is None
    assert await store.load(RunID("run-4")) is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_max_checkpoints_zero_keeps_all(tmp_path) -> None:
    store = FileCheckpointer(tmp_path / "ckpt", max_checkpoints=0)
    for i in range(6):
        await store.save(_checkpoint(f"run-{i}"))

    assert len(list((tmp_path / "ckpt").glob("*.json"))) == 6


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resave_same_run_does_not_count_against_cap(tmp_path) -> None:
    store = FileCheckpointer(tmp_path / "ckpt", max_checkpoints=2)
    # one run saved repeatedly overwrites a single file, never trips pruning
    for _ in range(4):
        await store.save(_checkpoint("run-stable"))

    files = list((tmp_path / "ckpt").glob("*.json"))
    assert len(files) == 1
    assert await store.load(RunID("run-stable")) is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prune_keeps_most_recently_saved_not_lexical(tmp_path) -> None:
    """Recency is by save time, not filename order: a low-named run saved last survives."""
    import os
    import time

    store = FileCheckpointer(tmp_path / "ckpt", max_checkpoints=1)
    ckpt_dir = tmp_path / "ckpt"

    await store.save(_checkpoint("run-zzz"))
    # force an older mtime on the first file so save-order is unambiguous
    old = time.time() - 100
    os.utime(ckpt_dir / "run-zzz.json", (old, old))

    await store.save(_checkpoint("run-aaa"))  # saved later → newer mtime

    remaining = [p.name for p in ckpt_dir.glob("*.json")]
    assert remaining == ["run-aaa.json"]  # kept the newer one despite 'aaa' < 'zzz'


@pytest.mark.unit
def test_negative_max_checkpoints_rejected(tmp_path) -> None:
    with pytest.raises(ValueError, match="max_checkpoints must be >= 0"):
        FileCheckpointer(tmp_path / "ckpt", max_checkpoints=-1)


@pytest.mark.unit
def test_checkpoint_serialization_preserves_patch_history() -> None:
    patch = ContextPatch(
        path="goal",
        operation=PatchOperation.SET,
        value="build",
        source=PatchSource.SYSTEM,
        source_id="test",
        reason="seed",
    )
    context = Context(data={"goal": "build"}, patch_history=(patch,))
    checkpoint = DAGCheckpoint(
        run_id=RunID("run-1"),
        dag_name="dag",
        status=RunStatus.COMPLETED,
        context=context,
    )

    restored = checkpoint_from_dict(checkpoint_to_dict(checkpoint))
    assert restored.context.data == {"goal": "build"}
    assert len(restored.context.patch_history) == 1
    assert restored.context.patch_history[0].path == "goal"
