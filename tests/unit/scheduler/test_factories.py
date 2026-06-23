"""Tests for scheduler factory functions."""

import pytest

from cemaf.config.protocols import SchedulerSettings, Settings
from cemaf.scheduler.factories import (
    create_managed_scheduler,
    create_managed_scheduler_from_config,
    create_scheduler_executor_from_config,
)
from cemaf.scheduler.heartbeats import InMemoryHeartbeatStore
from cemaf.scheduler.primitives import InMemoryJobStore, ManagedScheduler


class TestCreateManagedScheduler:
    def test_create_managed_scheduler_accepts_injected_stores(self) -> None:
        scheduler = create_managed_scheduler(
            worker_id="worker_a",
            job_store=InMemoryJobStore(),
            heartbeat_store=InMemoryHeartbeatStore(),
        )

        assert isinstance(scheduler, ManagedScheduler)
        assert scheduler.worker_id == "worker_a"

    def test_create_managed_scheduler_from_settings_uses_scheduler_config(self) -> None:
        settings = Settings(
            scheduler=SchedulerSettings(
                max_concurrent_jobs=4,
                check_interval_seconds=2.5,
                heartbeat_interval_seconds=15.0,
                heartbeat_ttl_seconds=45.0,
                worker_id="worker_settings",
            )
        )

        scheduler = create_managed_scheduler_from_config(settings=settings)

        assert scheduler.worker_id == "worker_settings"
        assert scheduler._executor._max_concurrent == 4
        assert scheduler._executor._check_interval == 2.5
        assert scheduler._heartbeat._interval == 15.0
        assert scheduler._heartbeat._ttl == 45.0

    def test_create_managed_scheduler_from_env_uses_heartbeat_settings(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("CEMAF_SCHEDULER_MAX_CONCURRENT_JOBS", "3")
        monkeypatch.setenv("CEMAF_SCHEDULER_CHECK_INTERVAL_SECONDS", "4.0")
        monkeypatch.setenv("CEMAF_SCHEDULER_HEARTBEAT_INTERVAL_SECONDS", "12.0")
        monkeypatch.setenv("CEMAF_SCHEDULER_HEARTBEAT_TTL_SECONDS", "48.0")
        monkeypatch.setenv("CEMAF_SCHEDULER_WORKER_ID", "worker_env")

        scheduler = create_managed_scheduler_from_config()

        assert scheduler.worker_id == "worker_env"
        assert scheduler._executor._max_concurrent == 3
        assert scheduler._executor._check_interval == 4.0
        assert scheduler._heartbeat._interval == 12.0
        assert scheduler._heartbeat._ttl == 48.0


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
