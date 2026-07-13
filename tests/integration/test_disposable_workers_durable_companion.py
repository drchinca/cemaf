"""Real worker-loss and replacement proof for the durable companion shape."""

from __future__ import annotations

from pathlib import Path

import pytest

from examples.app_shapes.disposable_workers_durable_companion import run_experiment


@pytest.mark.asyncio
async def test_three_disposable_pipelines_survive_worker_loss_under_load(tmp_path: Path) -> None:
    summary = await run_experiment(root=tmp_path, run_count=60, worker_count=3)

    assert summary["completed"] == 60
    assert summary["terminated_workers"] == 60
    assert summary["replacement_workers"] == 60
    assert summary["healed"] == 60
    assert summary["replay_matches"] == 60
    assert summary["checkpoint_files"] == 60
    assert summary["attempt_trace_dirs"] == 120
    assert summary["abandoned_worker_traces"] == 60
    assert summary["lineage_patches"] == 240
    assert summary["unique_patch_ids"] == 240


@pytest.mark.asyncio
async def test_two_disposable_pipelines_use_the_same_companion_contract(tmp_path: Path) -> None:
    summary = await run_experiment(root=tmp_path, run_count=10, worker_count=2)

    assert summary["completed"] == 10
    assert summary["replay_matches"] == 10
