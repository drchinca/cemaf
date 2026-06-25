"""
Factory functions for scheduler components.

Provides convenient ways to create task schedulers with sensible defaults
while maintaining dependency injection principles.
"""

import os
from typing import Any

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.scheduler.executor import AsyncJobExecutor
from cemaf.scheduler.mock import MockScheduler
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
    Create SchedulerExecutor from environment configuration.

    Reads from environment variables:
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
