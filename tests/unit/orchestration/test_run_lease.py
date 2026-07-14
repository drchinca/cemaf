"""Durable lease and checkpoint-fencing tests."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest

from cemaf.context.context import Context
from cemaf.core.enums import RunStatus
from cemaf.core.types import RunID
from cemaf.orchestration.checkpointer import DAGCheckpoint
from cemaf.orchestration.file_checkpointer import FileCheckpointer, StaleCheckpointWriteError
from cemaf.orchestration.run_lease import FileRunLeaseStore, StaleRunLeaseError


@pytest.mark.asyncio
async def test_only_one_process_claim_wins_and_tokens_never_repeat(tmp_path: Path) -> None:
    store = FileRunLeaseStore(tmp_path)
    run_id = RunID("lease-race")

    claims = await asyncio.gather(
        *(store.acquire(run_id, f"worker-{index}", ttl=timedelta(seconds=10)) for index in range(10))
    )
    winners = [claim for claim in claims if claim is not None]
    assert len(winners) == 1

    first = winners[0]
    await store.release(first)
    second = await store.acquire(run_id, "replacement", ttl=timedelta(seconds=10))
    assert second is not None
    assert second.fencing_token == first.fencing_token + 1
    assert await store.validate(first) is False
    with pytest.raises(StaleRunLeaseError):
        await store.release(first)


@pytest.mark.asyncio
async def test_lower_fencing_token_cannot_overwrite_new_checkpoint(tmp_path: Path) -> None:
    checkpointer = FileCheckpointer(tmp_path, max_checkpoints=0)
    run_id = RunID("fenced-checkpoint")
    newer = DAGCheckpoint(
        run_id=run_id,
        dag_name="fenced",
        status=RunStatus.RUNNING,
        context=Context(data={"owner": "new"}),
        fencing_token=2,
    )
    stale = DAGCheckpoint(
        run_id=run_id,
        dag_name="fenced",
        status=RunStatus.RUNNING,
        context=Context(data={"owner": "stale"}),
        fencing_token=1,
    )

    await checkpointer.save(newer)
    with pytest.raises(StaleCheckpointWriteError):
        await checkpointer.save(stale)

    loaded = await checkpointer.load(run_id)
    assert loaded is not None
    assert loaded.context.get("owner") == "new"
    assert loaded.fencing_token == 2
