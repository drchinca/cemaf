"""Managed scheduling primitives for durable jobs and coordinated workers."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from cemaf.core.types import JSON
from cemaf.core.utils import generate_id, safe_json, utc_now
from cemaf.observability.protocols import MetricsCollector
from cemaf.scheduler.executor import AsyncJobExecutor
from cemaf.scheduler.heartbeats import (
    HeartbeatMonitor,
    HeartbeatStore,
    InMemoryHeartbeatStore,
    WorkerHeartbeat,
)
from cemaf.scheduler.protocols import Job, JobResult, JobStatus, Trigger


class JobKind(StrEnum):
    """High-level job families for operator-facing classification."""

    STANDARD = "standard"
    DREAM = "dream"
    SYSTEM = "system"


class JobRunStatus(StrEnum):
    """Lifecycle states for managed job runs."""

    DEFERRED = "deferred"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class JobDefinition:
    """Durable scheduler-facing description of a background job."""

    id: str
    name: str
    trigger: Trigger
    kind: JobKind = JobKind.STANDARD
    enabled: bool = True
    max_retries: int = 3
    timeout_seconds: float = 300.0
    lease_ttl_seconds: float = 600.0
    singleton: bool = True
    tags: tuple[str, ...] = field(default_factory=tuple)
    metadata: JSON = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.max_retries < 1:
            raise ValueError("max_retries must be >= 1")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.lease_ttl_seconds <= 0:
            raise ValueError("lease_ttl_seconds must be positive")

    def to_job(self, handler: Callable[[], Awaitable[Any]]) -> Job:
        """Materialize the runtime scheduler job object."""
        metadata = dict(self.metadata)
        metadata["singleton"] = self.singleton
        return Job(
            id=self.id,
            name=self.name,
            trigger=self.trigger,
            handler=handler,
            enabled=self.enabled,
            max_retries=self.max_retries,
            timeout_seconds=self.timeout_seconds,
            metadata=safe_json(metadata),
        )


@dataclass(frozen=True)
class JobLease:
    """Worker ownership record for a scheduled job."""

    job_id: str
    worker_id: str
    acquired_at: datetime
    expires_at: datetime

    @classmethod
    def fresh(
        cls,
        *,
        job_id: str,
        worker_id: str,
        ttl_seconds: float,
        acquired_at: datetime | None = None,
    ) -> JobLease:
        """Create a fresh lease with the configured TTL."""
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        now = acquired_at or utc_now()
        return cls(
            job_id=job_id,
            worker_id=worker_id,
            acquired_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )

    def is_active(self, *, now: datetime | None = None) -> bool:
        """Whether the lease is still valid."""
        reference = now or utc_now()
        return reference < self.expires_at


@dataclass(frozen=True)
class JobRunRecord:
    """Persisted managed-job run record."""

    run_id: str
    job_id: str
    worker_id: str
    status: JobRunStatus
    started_at: datetime
    completed_at: datetime | None = None
    result: Any = None
    error: str | None = None
    metadata: JSON = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        """Wall-clock duration in milliseconds when the run has completed."""
        if self.completed_at is None:
            return 0.0
        return (self.completed_at - self.started_at).total_seconds() * 1000


@runtime_checkable
class JobStore(Protocol):
    """Storage protocol for managed scheduler state."""

    async def save_job(self, definition: JobDefinition) -> None:
        """Persist or replace a job definition."""
        ...

    async def get_job(self, job_id: str) -> JobDefinition | None:
        """Fetch one job definition."""
        ...

    async def list_jobs(self) -> tuple[JobDefinition, ...]:
        """List all known job definitions."""
        ...

    async def delete_job(self, job_id: str) -> bool:
        """Delete a job definition."""
        ...

    async def acquire_lease(self, job_id: str, worker_id: str, ttl_seconds: float) -> bool:
        """Try to acquire a per-job execution lease."""
        ...

    async def release_lease(self, job_id: str, worker_id: str) -> bool:
        """Release a lease if owned by the given worker."""
        ...

    async def get_lease(self, job_id: str) -> JobLease | None:
        """Fetch the current job lease."""
        ...

    async def save_run(self, record: JobRunRecord) -> None:
        """Persist or replace a run record."""
        ...

    async def get_run(self, run_id: str) -> JobRunRecord | None:
        """Fetch a run record."""
        ...

    async def list_runs(
        self,
        *,
        job_id: str | None = None,
        limit: int = 100,
    ) -> tuple[JobRunRecord, ...]:
        """List recent run records."""
        ...


class InMemoryJobStore:
    """Reference job store for local use and tests."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobDefinition] = {}
        self._leases: dict[str, JobLease] = {}
        self._runs: dict[str, JobRunRecord] = {}
        self._lock = asyncio.Lock()

    async def save_job(self, definition: JobDefinition) -> None:
        async with self._lock:
            self._jobs[definition.id] = definition

    async def get_job(self, job_id: str) -> JobDefinition | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def list_jobs(self) -> tuple[JobDefinition, ...]:
        async with self._lock:
            return tuple(sorted(self._jobs.values(), key=lambda item: item.id))

    async def delete_job(self, job_id: str) -> bool:
        async with self._lock:
            removed = self._jobs.pop(job_id, None) is not None
            self._leases.pop(job_id, None)
            return removed

    async def acquire_lease(self, job_id: str, worker_id: str, ttl_seconds: float) -> bool:
        async with self._lock:
            now = utc_now()
            existing = self._leases.get(job_id)
            if existing is not None and existing.is_active(now=now) and existing.worker_id != worker_id:
                return False
            self._leases[job_id] = JobLease.fresh(
                job_id=job_id,
                worker_id=worker_id,
                ttl_seconds=ttl_seconds,
                acquired_at=now,
            )
            return True

    async def release_lease(self, job_id: str, worker_id: str) -> bool:
        async with self._lock:
            existing = self._leases.get(job_id)
            if existing is None or existing.worker_id != worker_id:
                return False
            self._leases.pop(job_id, None)
            return True

    async def get_lease(self, job_id: str) -> JobLease | None:
        async with self._lock:
            lease = self._leases.get(job_id)
            if lease is None:
                return None
            if lease.is_active():
                return lease
            self._leases.pop(job_id, None)
            return None

    async def save_run(self, record: JobRunRecord) -> None:
        async with self._lock:
            self._runs[record.run_id] = record

    async def get_run(self, run_id: str) -> JobRunRecord | None:
        async with self._lock:
            return self._runs.get(run_id)

    async def list_runs(
        self,
        *,
        job_id: str | None = None,
        limit: int = 100,
    ) -> tuple[JobRunRecord, ...]:
        if limit <= 0:
            return ()
        async with self._lock:
            runs = list(self._runs.values())
        if job_id is not None:
            runs = [record for record in runs if record.job_id == job_id]
        runs.sort(key=lambda record: record.started_at, reverse=True)
        return tuple(runs[:limit])


@dataclass(frozen=True)
class _ActiveRun:
    run_id: str
    job_id: str
    started_at: datetime
    singleton: bool


class ManagedScheduler:
    """Scheduler wrapper with durable job definitions, run records, and worker heartbeats."""

    def __init__(
        self,
        *,
        worker_id: str | None = None,
        job_store: JobStore | None = None,
        heartbeat_store: HeartbeatStore | None = None,
        max_concurrent_jobs: int = 10,
        check_interval_seconds: float = 1.0,
        heartbeat_interval_seconds: float = 10.0,
        heartbeat_ttl_seconds: float = 30.0,
        metrics: MetricsCollector | None = None,
    ) -> None:
        self._worker_id = worker_id or generate_id("worker")
        self._job_store = job_store or InMemoryJobStore()
        self._job_defs: dict[str, JobDefinition] = {}
        self._job_handlers: dict[str, Callable[[], Awaitable[Any]]] = {}
        self._runtime_jobs: dict[str, Job] = {}
        self._active_runs: dict[asyncio.Task[Any], _ActiveRun] = {}
        self._in_progress_counts: dict[str, int] = defaultdict(int)
        self._metrics = metrics
        self._heartbeat = HeartbeatMonitor(
            store=heartbeat_store or InMemoryHeartbeatStore(),
            worker_id=self._worker_id,
            interval_seconds=heartbeat_interval_seconds,
            ttl_seconds=heartbeat_ttl_seconds,
            jobs_provider=self._jobs_provider,
            metadata_provider=self._metadata_provider,
            metrics=metrics,
        )
        self._executor = AsyncJobExecutor(
            max_concurrent=max_concurrent_jobs,
            check_interval_seconds=check_interval_seconds,
            on_job_complete=self._on_job_complete,
        )

    @property
    def worker_id(self) -> str:
        """Current managed worker identifier."""
        return self._worker_id

    async def register_job(
        self,
        *,
        definition: JobDefinition,
        handler: Callable[[], Awaitable[Any]],
    ) -> None:
        """Register a managed job and persist its definition."""
        await self._job_store.save_job(definition)
        wrapped = self._wrap_handler(definition=definition, handler=handler)
        self._job_defs[definition.id] = definition
        self._job_handlers[definition.id] = handler
        runtime_job = definition.to_job(handler=wrapped)
        self._runtime_jobs[definition.id] = runtime_job
        self._executor.add_job(runtime_job)
        if self._metrics is not None:
            self._metrics.counter(
                "cemaf.scheduler.jobs.registered",
                tags={"kind": definition.kind.value, "worker_id": self._worker_id},
            )

    async def unregister_job(self, job_id: str) -> bool:
        """Remove a managed job from runtime and persistent stores."""
        removed_runtime = self._executor.remove_job(job_id)
        removed_store = await self._job_store.delete_job(job_id)
        self._job_defs.pop(job_id, None)
        self._job_handlers.pop(job_id, None)
        self._runtime_jobs.pop(job_id, None)
        return removed_runtime or removed_store

    async def list_jobs(self) -> tuple[JobDefinition, ...]:
        """List persisted job definitions."""
        return await self._job_store.list_jobs()

    async def list_runs(
        self,
        *,
        job_id: str | None = None,
        limit: int = 100,
    ) -> tuple[JobRunRecord, ...]:
        """List recent managed runs."""
        return await self._job_store.list_runs(job_id=job_id, limit=limit)

    async def start(self) -> None:
        """Start scheduler loop and worker heartbeats."""
        await self._heartbeat.start()
        await self._executor.start()

    async def stop(self, *, delete_heartbeat: bool = False) -> None:
        """Stop scheduler loop and worker heartbeats."""
        await self._executor.stop()
        await self._heartbeat.stop(delete=delete_heartbeat)

    async def run_now(self, job_id: str) -> JobResult:
        """Run one managed job immediately."""
        result = await self._executor.run_now(job_id)
        await self._on_job_complete(result)
        return result

    async def worker_status(self) -> str:
        """Current worker liveness string."""
        return (await self._heartbeat.status()).value

    async def list_stale_workers(self) -> tuple[WorkerHeartbeat, ...]:
        """List workers whose heartbeat has expired."""
        return await self._heartbeat.list_stale_workers()

    def _jobs_provider(self) -> tuple[str, ...]:
        return tuple(sorted(job_id for job_id, count in self._in_progress_counts.items() if count > 0))

    def _metadata_provider(self) -> JSON:
        return {
            "managed_jobs": len(self._job_defs),
            "active_runs": sum(self._in_progress_counts.values()),
        }

    def _wrap_handler(
        self,
        *,
        definition: JobDefinition,
        handler: Callable[[], Awaitable[Any]],
    ) -> Callable[[], Awaitable[Any]]:
        async def wrapped() -> Any:
            task = asyncio.current_task()
            if task is None:
                raise RuntimeError("ManagedScheduler requires an active asyncio task")

            current = self._active_runs.get(task)
            if current is None:
                if definition.singleton:
                    acquired = await self._job_store.acquire_lease(
                        definition.id,
                        self._worker_id,
                        definition.lease_ttl_seconds,
                    )
                    if not acquired:
                        deferred = JobRunRecord(
                            run_id=generate_id("jobrun"),
                            job_id=definition.id,
                            worker_id=self._worker_id,
                            status=JobRunStatus.DEFERRED,
                            started_at=utc_now(),
                            completed_at=utc_now(),
                            metadata={"reason": "lease_held", **safe_json(definition.metadata)},
                        )
                        await self._job_store.save_run(deferred)
                        return {"_cemaf_deferred": True, "run_id": deferred.run_id}

                current = _ActiveRun(
                    run_id=generate_id("jobrun"),
                    job_id=definition.id,
                    started_at=utc_now(),
                    singleton=definition.singleton,
                )
                self._active_runs[task] = current
                self._in_progress_counts[definition.id] += 1
                await self._heartbeat.beat()
                await self._job_store.save_run(
                    JobRunRecord(
                        run_id=current.run_id,
                        job_id=definition.id,
                        worker_id=self._worker_id,
                        status=JobRunStatus.RUNNING,
                        started_at=current.started_at,
                        metadata=safe_json(definition.metadata),
                    )
                )

            payload = await handler()
            return {"_cemaf_run_id": current.run_id, "payload": safe_json(payload)}

        return wrapped

    async def _on_job_complete(self, result: JobResult) -> None:
        payload = result.result if isinstance(result.result, dict) else None
        if isinstance(payload, dict) and payload.get("_cemaf_deferred"):
            return

        task = asyncio.current_task()
        active = self._active_runs.pop(task, None) if task is not None else None
        if active is not None:
            remaining = self._in_progress_counts.get(active.job_id, 0) - 1
            if remaining > 0:
                self._in_progress_counts[active.job_id] = remaining
            else:
                self._in_progress_counts.pop(active.job_id, None)

        run_id = ""
        started_at = result.started_at
        if active is not None:
            run_id = active.run_id
            started_at = active.started_at
        elif isinstance(payload, dict) and isinstance(payload.get("_cemaf_run_id"), str):
            run_id = payload["_cemaf_run_id"]
        else:
            run_id = generate_id("jobrun")

        final_status = self._map_status(result.status)
        final_payload: Any = None
        if isinstance(payload, dict) and "payload" in payload:
            final_payload = payload["payload"]
        elif result.result is not None:
            final_payload = safe_json(result.result)

        await self._job_store.save_run(
            JobRunRecord(
                run_id=run_id,
                job_id=result.job_id,
                worker_id=self._worker_id,
                status=final_status,
                started_at=started_at,
                completed_at=result.completed_at or utc_now(),
                result=final_payload,
                error=result.error,
                metadata={"duration_ms": result.duration_ms},
            )
        )

        if active is not None and active.singleton:
            await self._job_store.release_lease(result.job_id, self._worker_id)
        if active is not None:
            await self._heartbeat.beat()
        if self._metrics is not None:
            self._metrics.counter(
                "cemaf.scheduler.jobs.completed",
                tags={
                    "job_id": result.job_id,
                    "status": final_status.value,
                    "worker_id": self._worker_id,
                },
            )

    @staticmethod
    def _map_status(status: JobStatus) -> JobRunStatus:
        match status:
            case JobStatus.COMPLETED:
                return JobRunStatus.COMPLETED
            case JobStatus.TIMEOUT:
                return JobRunStatus.TIMEOUT
            case JobStatus.CANCELLED:
                return JobRunStatus.CANCELLED
            case _:
                return JobRunStatus.FAILED
