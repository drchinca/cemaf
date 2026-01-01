"""
Factory functions for scheduler components.

Provides convenient ways to create task schedulers with sensible defaults
while maintaining dependency injection principles.
"""

import os

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.scheduler.executor import SchedulerExecutor


def create_scheduler_executor(
    max_concurrent_jobs: int = 10,
    default_job_timeout_seconds: float = 300.0,
) -> SchedulerExecutor:
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
    return SchedulerExecutor(
        max_concurrent_jobs=max_concurrent_jobs,
        default_job_timeout_seconds=default_job_timeout_seconds,
    )


def create_scheduler_executor_from_config(settings: Settings | None = None) -> SchedulerExecutor:
    """
    Create SchedulerExecutor from environment configuration.

    Reads from environment variables:
    - CEMAF_SCHEDULER_MAX_CONCURRENT_JOBS: Max concurrent jobs (default: 10)
    - CEMAF_SCHEDULER_DEFAULT_JOB_TIMEOUT_SECONDS: Job timeout (default: 300.0)

    Returns:
        Configured SchedulerExecutor instance

    Example:
        # From environment
        scheduler = create_scheduler_executor_from_config()
    """
    cfg = settings or load_settings_from_env_sync()  # noqa: F841

    max_concurrent = int(os.getenv("CEMAF_SCHEDULER_MAX_CONCURRENT_JOBS", "10"))
    timeout = float(os.getenv("CEMAF_SCHEDULER_DEFAULT_JOB_TIMEOUT_SECONDS", "300.0"))

    return create_scheduler_executor(
        max_concurrent_jobs=max_concurrent,
        default_job_timeout_seconds=timeout,
    )
