"""Integration tests for managed dreaming-mode scheduling."""

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.memory.factories import create_memory_manager
from cemaf.meta.dreaming import DreamingMode
from cemaf.scheduler.heartbeats import InMemoryHeartbeatStore
from cemaf.scheduler.primitives import InMemoryJobStore, JobRunStatus, ManagedScheduler


@pytest.mark.asyncio
async def test_dreaming_mode_runs_under_managed_scheduler() -> None:
    memory_manager = create_memory_manager()
    await memory_manager.remember(
        scope=MemoryScope.PROJECT,
        key="fact",
        value={"summary": "A durable project fact."},
    )

    mode = DreamingMode(min_sessions=1, use_lock_gate=False)
    handle = mode.build(memory_manager=memory_manager, current_sessions=1)

    job_store = InMemoryJobStore()
    heartbeat_store = InMemoryHeartbeatStore()
    scheduler = ManagedScheduler(
        worker_id="worker_a",
        job_store=job_store,
        heartbeat_store=heartbeat_store,
        heartbeat_interval_seconds=60.0,
        heartbeat_ttl_seconds=60.0,
    )
    await scheduler.register_job(definition=handle.definition, handler=handle.handler)

    result = await scheduler.run_now(handle.definition.id)
    runs = await scheduler.list_runs(job_id=handle.definition.id)
    heartbeat = await heartbeat_store.get("worker_a")

    assert result.status.value == "completed"
    assert len(runs) == 1
    assert runs[0].status == JobRunStatus.COMPLETED
    assert isinstance(runs[0].result, dict)
    assert runs[0].result["consolidated_count"] >= 1
    assert heartbeat is not None
