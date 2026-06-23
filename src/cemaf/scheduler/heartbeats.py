"""Worker heartbeat primitives for scheduled background execution."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol, runtime_checkable

from cemaf.core.types import JSON
from cemaf.core.utils import safe_json, utc_now
from cemaf.observability.protocols import MetricsCollector


class WorkerHeartbeatStatus(StrEnum):
    """Liveness status derived from the last heartbeat observation."""

    ACTIVE = "active"
    STALE = "stale"
    MISSING = "missing"


@dataclass(frozen=True)
class WorkerHeartbeat:
    """One worker heartbeat record with a fixed expiry."""

    worker_id: str
    observed_at: datetime
    expires_at: datetime
    jobs_in_progress: tuple[str, ...] = field(default_factory=tuple)
    metadata: JSON = field(default_factory=dict)

    @classmethod
    def fresh(
        cls,
        *,
        worker_id: str,
        ttl_seconds: float,
        jobs_in_progress: tuple[str, ...] = (),
        metadata: JSON | None = None,
        observed_at: datetime | None = None,
    ) -> WorkerHeartbeat:
        """Build a fresh heartbeat that expires after the configured TTL."""
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        now = observed_at or utc_now()
        return cls(
            worker_id=worker_id,
            observed_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
            jobs_in_progress=tuple(sorted(jobs_in_progress)),
            metadata=safe_json(metadata or {}),
        )

    def is_alive(self, *, now: datetime | None = None) -> bool:
        """Whether the heartbeat is still fresh."""
        reference = now or utc_now()
        return reference < self.expires_at

    def status(self, *, now: datetime | None = None) -> WorkerHeartbeatStatus:
        """Derived worker status at the given time."""
        return WorkerHeartbeatStatus.ACTIVE if self.is_alive(now=now) else WorkerHeartbeatStatus.STALE


@runtime_checkable
class HeartbeatStore(Protocol):
    """Storage protocol for worker heartbeats."""

    async def upsert(self, heartbeat: WorkerHeartbeat) -> None:
        """Insert or replace the latest heartbeat for a worker."""
        ...

    async def get(self, worker_id: str) -> WorkerHeartbeat | None:
        """Fetch a worker heartbeat."""
        ...

    async def list_all(self) -> tuple[WorkerHeartbeat, ...]:
        """List all known worker heartbeats."""
        ...

    async def delete(self, worker_id: str) -> bool:
        """Delete a worker heartbeat."""
        ...


class InMemoryHeartbeatStore:
    """Simple in-memory heartbeat store for single-process deployments and tests."""

    def __init__(self) -> None:
        self._heartbeats: dict[str, WorkerHeartbeat] = {}
        self._lock = asyncio.Lock()

    async def upsert(self, heartbeat: WorkerHeartbeat) -> None:
        async with self._lock:
            self._heartbeats[heartbeat.worker_id] = heartbeat

    async def get(self, worker_id: str) -> WorkerHeartbeat | None:
        async with self._lock:
            return self._heartbeats.get(worker_id)

    async def list_all(self) -> tuple[WorkerHeartbeat, ...]:
        async with self._lock:
            return tuple(sorted(self._heartbeats.values(), key=lambda item: item.observed_at, reverse=True))

    async def delete(self, worker_id: str) -> bool:
        async with self._lock:
            return self._heartbeats.pop(worker_id, None) is not None


class HeartbeatMonitor:
    """Periodic worker heartbeat publisher with stale-worker inspection helpers."""

    def __init__(
        self,
        *,
        store: HeartbeatStore,
        worker_id: str,
        interval_seconds: float = 10.0,
        ttl_seconds: float = 30.0,
        jobs_provider: Callable[[], tuple[str, ...]] | None = None,
        metadata_provider: Callable[[], JSON] | None = None,
        metrics: MetricsCollector | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._store = store
        self._worker_id = worker_id
        self._interval = interval_seconds
        self._ttl = ttl_seconds
        self._jobs_provider = jobs_provider
        self._metadata_provider = metadata_provider
        self._metrics = metrics
        self._task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def worker_id(self) -> str:
        """Worker identifier for this monitor."""
        return self._worker_id

    async def beat(
        self,
        *,
        jobs_in_progress: tuple[str, ...] | None = None,
        metadata: JSON | None = None,
    ) -> WorkerHeartbeat:
        """Publish one heartbeat immediately."""
        jobs = jobs_in_progress if jobs_in_progress is not None else self._current_jobs()
        details = metadata if metadata is not None else self._current_metadata()
        heartbeat = WorkerHeartbeat.fresh(
            worker_id=self._worker_id,
            ttl_seconds=self._ttl,
            jobs_in_progress=jobs,
            metadata=details,
        )
        await self._store.upsert(heartbeat)
        if self._metrics is not None:
            self._metrics.counter("cemaf.worker.heartbeats.total", tags={"worker_id": self._worker_id})
            self._metrics.gauge(
                "cemaf.worker.jobs_in_progress",
                float(len(heartbeat.jobs_in_progress)),
                tags={"worker_id": self._worker_id},
            )
        return heartbeat

    async def start(self) -> None:
        """Start the periodic heartbeat loop."""
        if self._running:
            return
        self._running = True
        await self.beat()
        self._task = asyncio.create_task(self._loop(), name=f"heartbeat-{self._worker_id}")

    async def stop(self, *, delete: bool = False) -> None:
        """Stop the heartbeat loop and optionally delete the worker record."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if delete:
            await self._store.delete(self._worker_id)

    async def status(self) -> WorkerHeartbeatStatus:
        """Current derived status for the worker."""
        heartbeat = await self._store.get(self._worker_id)
        if heartbeat is None:
            return WorkerHeartbeatStatus.MISSING
        return heartbeat.status()

    async def list_stale_workers(self) -> tuple[WorkerHeartbeat, ...]:
        """List workers whose last heartbeat has expired."""
        heartbeats = await self._store.list_all()
        return tuple(item for item in heartbeats if item.status() == WorkerHeartbeatStatus.STALE)

    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                await self.beat()
            except asyncio.CancelledError:
                raise
            except Exception:
                if self._metrics is not None:
                    self._metrics.counter(
                        "cemaf.worker.heartbeats.failed",
                        tags={"worker_id": self._worker_id},
                    )

    def _current_jobs(self) -> tuple[str, ...]:
        if self._jobs_provider is None:
            return ()
        return tuple(self._jobs_provider())

    def _current_metadata(self) -> JSON:
        if self._metadata_provider is None:
            return {}
        metadata = safe_json(self._metadata_provider())
        if isinstance(metadata, dict):
            return metadata
        return {"value": metadata}
