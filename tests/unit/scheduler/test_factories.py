"""Tests for scheduler factory functions and composition roots."""

import pytest

from cemaf.config.protocols import SchedulerSettings, Settings
from cemaf.scheduler import (
    AsyncJobExecutor,
    Job,
    JobResult,
    MockScheduler,
    create_scheduler_executor,
    create_scheduler_executor_from_config,
    scheduler_registry,
)
from cemaf.scheduler.factories import (
    create_managed_scheduler,
    create_managed_scheduler_from_config,
)
from cemaf.scheduler.heartbeats import InMemoryHeartbeatStore
from cemaf.scheduler.primitives import InMemoryJobStore, ManagedScheduler


class CustomScheduler:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}

    def add_job(self, job: Job) -> None:
        self.jobs[job.id] = job

    def remove_job(self, job_id: str) -> bool:
        return self.jobs.pop(job_id, None) is not None

    def get_job(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def get_jobs(self) -> list[Job]:
        return list(self.jobs.values())

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def run_now(self, job_id: str) -> JobResult:
        raise KeyError(job_id)


def test_create_scheduler_executor_defaults_to_async_scheduler() -> None:
    scheduler = create_scheduler_executor()

    assert isinstance(scheduler, AsyncJobExecutor)


def test_create_scheduler_executor_supports_mock_backend() -> None:
    scheduler = create_scheduler_executor(backend="mock")

    assert isinstance(scheduler, MockScheduler)


def test_create_scheduler_executor_supports_custom_registered_backend() -> None:
    created: dict[str, object] = {}

    def _factory(**kwargs):
        created["args"] = kwargs
        return CustomScheduler()

    scheduler_registry.register(backend="custom-scheduler", factory=_factory)

    scheduler = create_scheduler_executor(
        backend="custom-scheduler",
        max_concurrent_jobs=3,
        default_job_timeout_seconds=4.5,
        check_interval_seconds=0.25,
        region="local",
    )

    assert isinstance(scheduler, CustomScheduler)
    assert created["args"]["max_concurrent_jobs"] == 3
    assert created["args"]["default_job_timeout_seconds"] == 4.5
    assert created["args"]["check_interval_seconds"] == 0.25
    assert created["args"]["region"] == "local"


def test_create_scheduler_executor_from_config_supports_env_backend(monkeypatch) -> None:  # noqa: ANN001
    scheduler_registry.register(backend="env-scheduler", factory=lambda **_: CustomScheduler())
    monkeypatch.setenv("CEMAF_SCHEDULER_BACKEND", "env-scheduler")

    scheduler = create_scheduler_executor_from_config()

    assert isinstance(scheduler, CustomScheduler)


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
