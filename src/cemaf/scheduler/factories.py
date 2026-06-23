"""
Factory functions for scheduler components.

Provides convenient ways to create task schedulers with sensible defaults
while maintaining dependency injection principles.
"""

import os

from cemaf.config.protocols import SchedulerSettings, Settings
from cemaf.observability.protocols import MetricsCollector
from cemaf.scheduler.executor import AsyncJobExecutor
from cemaf.scheduler.heartbeats import HeartbeatStore
from cemaf.scheduler.primitives import JobStore, ManagedScheduler


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
    max_concurrent_jobs: int = 10,
    default_job_timeout_seconds: float = 300.0,
) -> AsyncJobExecutor:
    """
    Factory for SchedulerExecutor with sensible defaults.

    Args:
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
    # AsyncJobExecutor uses max_concurrent, not max_concurrent_jobs
    return AsyncJobExecutor(
        max_concurrent=max_concurrent_jobs,
    )


def create_scheduler_executor_from_config(settings: Settings | None = None) -> AsyncJobExecutor:
    """
    Create SchedulerExecutor from scheduler configuration.

    Reads from `Settings.scheduler` when provided, otherwise from environment:
    - `CEMAF_SCHEDULER_MAX_CONCURRENT_JOBS`: Max concurrent jobs (default: `10`)
    - `CEMAF_SCHEDULER_DEFAULT_JOB_TIMEOUT_SECONDS`: Job timeout (default: `300.0`)

    Returns:
        Configured SchedulerExecutor instance

    Example:
        # From environment
        scheduler = create_scheduler_executor_from_config()
    """
    cfg = _load_scheduler_settings(settings)

    return create_scheduler_executor(
        max_concurrent_jobs=cfg.max_concurrent_jobs,
        default_job_timeout_seconds=cfg.default_job_timeout_seconds,
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
