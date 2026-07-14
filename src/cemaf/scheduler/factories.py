"""
Factory functions for scheduler components.

Provides convenient ways to create task schedulers with sensible defaults
while maintaining dependency injection principles.
"""

import os
from typing import Any

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import SchedulerSettings, Settings
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.observability.protocols import MetricsCollector
from cemaf.scheduler.executor import AsyncJobExecutor
from cemaf.scheduler.heartbeats import HeartbeatStore
from cemaf.scheduler.mock import MockScheduler
from cemaf.scheduler.primitives import JobStore, ManagedScheduler
from cemaf.scheduler.protocols import Scheduler

scheduler_registry: ProviderRegistry[Scheduler] = ProviderRegistry(name="scheduler")


def _create_async_scheduler(**kwargs: Any) -> Scheduler:
    return AsyncJobExecutor(
        max_concurrent=int(kwargs.get("max_concurrent_jobs", 10)),
        check_interval_seconds=float(kwargs.get("check_interval_seconds", 1.0)),
    )


def _create_mock_scheduler(**kwargs: Any) -> Scheduler:
    return MockScheduler()


scheduler_registry.register(backend="async", factory=_create_async_scheduler)
scheduler_registry.register(backend="mock", factory=_create_mock_scheduler)


def _load_scheduler_settings(settings: Settings | None = None) -> SchedulerSettings:
    """Resolve scheduler settings from an explicit config object or raw env vars."""
    if settings is not None:
        return settings.scheduler

    return SchedulerSettings(
        max_concurrent_jobs=int(os.getenv("CEMAF_SCHEDULER_MAX_CONCURRENT_JOBS", "10")),
        default_job_timeout_seconds=float(os.getenv("CEMAF_SCHEDULER_DEFAULT_JOB_TIMEOUT_SECONDS", "300.0")),
        default_max_retries=int(os.getenv("CEMAF_SCHEDULER_DEFAULT_MAX_RETRIES", "3")),
        enable_persistence=os.getenv("CEMAF_SCHEDULER_ENABLE_PERSISTENCE", "false").lower() == "true",
        check_interval_seconds=float(os.getenv("CEMAF_SCHEDULER_CHECK_INTERVAL_SECONDS", "1.0")),
        heartbeat_interval_seconds=float(os.getenv("CEMAF_SCHEDULER_HEARTBEAT_INTERVAL_SECONDS", "10.0")),
        heartbeat_ttl_seconds=float(os.getenv("CEMAF_SCHEDULER_HEARTBEAT_TTL_SECONDS", "30.0")),
        worker_id=os.getenv("CEMAF_SCHEDULER_WORKER_ID", ""),
    )


def create_scheduler_executor(
    backend: str = "async",
    max_concurrent_jobs: int = 10,
    default_job_timeout_seconds: float = 300.0,
    check_interval_seconds: float = 1.0,
    **backend_options: Any,
) -> Scheduler:
    """
    Factory for SchedulerExecutor with sensible defaults.

    Args:
        backend: Scheduler backend (async, mock, or registered custom backend)
        max_concurrent_jobs: Maximum concurrent jobs
        default_job_timeout_seconds: Default timeout per job

    Returns:
        Configured SchedulerExecutor instance

    Example:
        # With defaults
        scheduler = create_scheduler_executor()

        # Custom configuration
        scheduler = create_scheduler_executor(max_concurrent_jobs=20)
    """
    return scheduler_registry.create(
        backend=backend,
        max_concurrent_jobs=max_concurrent_jobs,
        default_job_timeout_seconds=default_job_timeout_seconds,
        check_interval_seconds=check_interval_seconds,
        **backend_options,
    )


def create_scheduler_executor_from_config(settings: Settings | None = None) -> Scheduler:
    """
    Create SchedulerExecutor from scheduler configuration.

    Reads from `Settings.scheduler` when provided, otherwise from environment:
    - CEMAF_SCHEDULER_BACKEND: Scheduler backend (default: async)
    - CEMAF_SCHEDULER_MAX_CONCURRENT_JOBS: Max concurrent jobs (default: 10)
    - CEMAF_SCHEDULER_DEFAULT_JOB_TIMEOUT_SECONDS: Job timeout (default: 300.0)
    - CEMAF_SCHEDULER_CHECK_INTERVAL_SECONDS: Scheduler poll interval (default: 1.0)

    Returns:
        Configured SchedulerExecutor instance

    Example:
        # From environment
        scheduler = create_scheduler_executor_from_config()
    """
    cfg = settings or load_settings_from_env_sync()

    backend = os.getenv("CEMAF_SCHEDULER_BACKEND", "async")
    max_concurrent = int(
        os.getenv("CEMAF_SCHEDULER_MAX_CONCURRENT_JOBS", str(cfg.scheduler.max_concurrent_jobs))
    )
    timeout = float(
        os.getenv(
            "CEMAF_SCHEDULER_DEFAULT_JOB_TIMEOUT_SECONDS",
            str(cfg.scheduler.default_job_timeout_seconds),
        )
    )
    check_interval = float(
        os.getenv(
            "CEMAF_SCHEDULER_CHECK_INTERVAL_SECONDS",
            str(cfg.scheduler.check_interval_seconds),
        )
    )

    return create_scheduler_executor(
        backend=backend,
        max_concurrent_jobs=max_concurrent,
        default_job_timeout_seconds=timeout,
        check_interval_seconds=check_interval,
    )


def create_managed_scheduler(
    *,
    worker_id: str | None = None,
    job_store: JobStore | None = None,
    heartbeat_store: HeartbeatStore | None = None,
    max_concurrent_jobs: int = 10,
    check_interval_seconds: float = 1.0,
    heartbeat_interval_seconds: float = 10.0,
    heartbeat_ttl_seconds: float = 30.0,
    metrics: MetricsCollector | None = None,
) -> ManagedScheduler:
    """Create a managed scheduler with durable jobs and worker heartbeats."""
    return ManagedScheduler(
        worker_id=worker_id,
        job_store=job_store,
        heartbeat_store=heartbeat_store,
        max_concurrent_jobs=max_concurrent_jobs,
        check_interval_seconds=check_interval_seconds,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        heartbeat_ttl_seconds=heartbeat_ttl_seconds,
        metrics=metrics,
    )


def create_managed_scheduler_from_config(
    settings: Settings | None = None,
    *,
    job_store: JobStore | None = None,
    heartbeat_store: HeartbeatStore | None = None,
    metrics: MetricsCollector | None = None,
) -> ManagedScheduler:
    """
    Create a managed scheduler from scheduler configuration.

    Reads from `Settings.scheduler` when provided, otherwise from environment:
    - `CEMAF_SCHEDULER_MAX_CONCURRENT_JOBS`
    - `CEMAF_SCHEDULER_CHECK_INTERVAL_SECONDS`
    - `CEMAF_SCHEDULER_HEARTBEAT_INTERVAL_SECONDS`
    - `CEMAF_SCHEDULER_HEARTBEAT_TTL_SECONDS`
    - `CEMAF_SCHEDULER_WORKER_ID`
    """
    cfg = _load_scheduler_settings(settings)

    return create_managed_scheduler(
        worker_id=cfg.worker_id or None,
        job_store=job_store,
        heartbeat_store=heartbeat_store,
        max_concurrent_jobs=cfg.max_concurrent_jobs,
        check_interval_seconds=cfg.check_interval_seconds,
        heartbeat_interval_seconds=cfg.heartbeat_interval_seconds,
        heartbeat_ttl_seconds=cfg.heartbeat_ttl_seconds,
        metrics=metrics,
    )
