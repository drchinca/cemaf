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
