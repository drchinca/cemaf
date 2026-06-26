"""Tests for scheduler factory composition roots."""

from cemaf.scheduler import (
    AsyncJobExecutor,
    Job,
    JobResult,
    MockScheduler,
    create_scheduler_executor,
    create_scheduler_executor_from_config,
    scheduler_registry,
)


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
