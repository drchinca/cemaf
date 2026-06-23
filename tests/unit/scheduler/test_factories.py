"""Tests for scheduler factory functions."""

from cemaf.config.protocols import SchedulerSettings, Settings
from cemaf.scheduler.factories import create_scheduler_executor_from_config


class TestCreateSchedulerExecutorFromConfig:
    def test_uses_explicit_settings(self) -> None:
        settings = Settings(
            scheduler=SchedulerSettings(
                max_concurrent_jobs=7,
                default_job_timeout_seconds=120.0,
            )
        )

        executor = create_scheduler_executor_from_config(settings=settings)

        assert executor._max_concurrent == 7
