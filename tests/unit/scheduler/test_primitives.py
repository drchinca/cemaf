"""Tests for managed scheduler primitives, jobs, and heartbeats."""

from __future__ import annotations

import asyncio

import pytest

from cemaf.scheduler.heartbeats import (
    HeartbeatMonitor,
    InMemoryHeartbeatStore,
    WorkerHeartbeatStatus,
)
from cemaf.scheduler.primitives import (
    InMemoryJobStore,
    JobDefinition,
    JobKind,
    JobRunStatus,
    ManagedScheduler,
)
from cemaf.scheduler.triggers import ImmediateTrigger


class TestInMemoryJobStore:
    @pytest.mark.asyncio
    async def test_lease_is_exclusive_across_workers(self) -> None:
        store = InMemoryJobStore()
        acquired_first = await store.acquire_lease("dream", "worker_a", ttl_seconds=30)
        acquired_second = await store.acquire_lease("dream", "worker_b", ttl_seconds=30)

        assert acquired_first is True
        assert acquired_second is False

    @pytest.mark.asyncio
    async def test_release_lease_by_owner(self) -> None:
        store = InMemoryJobStore()
        await store.acquire_lease("dream", "worker_a", ttl_seconds=30)

        released = await store.release_lease("dream", "worker_a")
        lease = await store.get_lease("dream")

        assert released is True
        assert lease is None


class TestJobDefinition:
    def test_to_job_injects_singleton_metadata(self) -> None:
        definition = JobDefinition(
            id="dream",
            name="Dream Job",
            trigger=ImmediateTrigger(),
            kind=JobKind.DREAM,
        )

        async def handler() -> dict[str, bool]:
            return {"ok": True}

        job = definition.to_job(handler=handler)

        assert job.metadata["singleton"] is True


class TestHeartbeats:
    @pytest.mark.asyncio
    async def test_monitor_reports_stale_workers(self) -> None:
        store = InMemoryHeartbeatStore()
        monitor = HeartbeatMonitor(
            store=store,
            worker_id="worker_a",
            interval_seconds=1.0,
            ttl_seconds=0.01,
        )
        await monitor.beat()
        await asyncio.sleep(0.02)

        status = await monitor.status()
        stale = await monitor.list_stale_workers()

        assert status == WorkerHeartbeatStatus.STALE
        assert len(stale) == 1
        assert stale[0].worker_id == "worker_a"


class TestManagedScheduler:
    @pytest.mark.asyncio
    async def test_run_now_records_completed_run_and_heartbeat(self) -> None:
        job_store = InMemoryJobStore()
        heartbeat_store = InMemoryHeartbeatStore()
        scheduler = ManagedScheduler(
            worker_id="worker_a",
            job_store=job_store,
            heartbeat_store=heartbeat_store,
            heartbeat_interval_seconds=60.0,
            heartbeat_ttl_seconds=60.0,
        )
        await scheduler.register_job(
            definition=JobDefinition(
                id="dream",
                name="Dream Job",
                trigger=ImmediateTrigger(),
                kind=JobKind.DREAM,
            ),
            handler=self._success_handler,
        )

        result = await scheduler.run_now("dream")
        runs = await scheduler.list_runs(job_id="dream")
        worker_status = await scheduler.worker_status()
        heartbeat = await heartbeat_store.get("worker_a")

        assert result.status.value == "completed"
        assert len(runs) == 1
        assert runs[0].status == JobRunStatus.COMPLETED
        assert runs[0].result == {"ok": True}
        assert worker_status == WorkerHeartbeatStatus.ACTIVE.value
        assert heartbeat is not None
        assert heartbeat.jobs_in_progress == ()

    @pytest.mark.asyncio
    async def test_run_now_records_failure(self) -> None:
        scheduler = ManagedScheduler(worker_id="worker_a")
        await scheduler.register_job(
            definition=JobDefinition(
                id="failing",
                name="Failing Job",
                trigger=ImmediateTrigger(),
            ),
            handler=self._failing_handler,
        )

        result = await scheduler.run_now("failing")
        runs = await scheduler.list_runs(job_id="failing")

        assert result.status.value == "failed"
        assert len(runs) == 1
        assert runs[0].status == JobRunStatus.FAILED
        assert "boom" in (runs[0].error or "")

    async def _success_handler(self) -> dict[str, bool]:
        return {"ok": True}

    async def _failing_handler(self) -> None:
        raise RuntimeError("boom")
