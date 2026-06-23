"""Factory functions for scheduler components."""

import os

from cemaf.config.protocols import SchedulerSettings, Settings
from cemaf.scheduler.executor import AsyncJobExecutor


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
    """Factory for AsyncJobExecutor with sensible defaults."""
    return AsyncJobExecutor(max_concurrent=max_concurrent_jobs)


def create_scheduler_executor_from_config(settings: Settings | None = None) -> AsyncJobExecutor:
    """Create AsyncJobExecutor from scheduler configuration."""
    cfg = _load_scheduler_settings(settings)
    return create_scheduler_executor(
        max_concurrent_jobs=cfg.max_concurrent_jobs,
        default_job_timeout_seconds=cfg.default_job_timeout_seconds,
    )
