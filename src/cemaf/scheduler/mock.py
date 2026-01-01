"""
Mock implementations for testing scheduler.
"""

from datetime import datetime

from cemaf.scheduler.protocols import Job, JobResult


class MockTrigger:
    """
    Mock trigger for testing.

    Always returns a fixed next run time and can be configured
    to fire or not.
    """

    def __init__(
        self,
        should_fire: bool = False,
        next_run_time: datetime | None = None,
        name: str = "mock_trigger",
    ) -> None:
        """
        Initialize mock trigger.

        Args:
            should_fire: Whether trigger should fire.
            next_run_time: Fixed next run time.
            name: Trigger name.
        """
        self._should_fire = should_fire
        self._next_run_time = next_run_time
        self._name = name
        self._fire_count = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def fire_count(self) -> int:
        return self._fire_count

    def set_should_fire(self, should_fire: bool) -> None:
        """Set whether trigger should fire."""
        self._should_fire = should_fire

    def next_run(self, after: datetime) -> datetime | None:
        """Return configured next run time."""
        return self._next_run_time

    def should_run(self, now: datetime) -> bool:
        """Return configured should_fire value."""
        return self._should_fire

    def mark_run(self, at: datetime | None = None) -> None:
        """Record that trigger fired."""
        self._fire_count += 1
        self._should_fire = False  # Reset after firing


class MockScheduler:
    """
    Mock scheduler for testing.

    Records job additions and executions without actually scheduling.
    """

    def __init__(self) -> None:
        """Initialize mock scheduler."""
        self._jobs: dict[str, Job] = {}
        self._executions: list[tuple[str, datetime]] = []
        self._running = False

    @property
    def jobs(self) -> dict[str, Job]:
        """Get all jobs."""
        return dict(self._jobs)

    @property
    def executions(self) -> list[tuple[str, datetime]]:
        """Get all execution records."""
        return list(self._executions)

    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running

    def add_job(self, job: Job) -> None:
        """Record job addition."""
        self._jobs[job.id] = job

    def remove_job(self, job_id: str) -> bool:
        """Remove a job."""
        if job_id in self._jobs:
            del self._jobs[job_id]
            return True
        return False

    def get_job(self, job_id: str) -> Job | None:
        """Get a job by ID."""
        return self._jobs.get(job_id)

    def get_jobs(self) -> list[Job]:
        """Get all jobs."""
        return list(self._jobs.values())

    async def start(self) -> None:
        """Mark as started."""
        self._running = True

    async def stop(self) -> None:
        """Mark as stopped."""
        self._running = False

    async def run_now(self, job_id: str) -> JobResult:
        """Record execution and run job."""
        job = self._jobs.get(job_id)
        if not job:
            raise KeyError(f"Job not found: {job_id}")

        started_at = datetime.now()
        self._executions.append((job_id, started_at))

        try:
            result = await job.handler()
            return JobResult.success(
                job_id=job_id,
                started_at=started_at,
                result=result,
            )
        except Exception as e:
            return JobResult.failure(
                job_id=job_id,
                started_at=started_at,
                error=str(e),
            )

    def reset(self) -> None:
        """Reset mock state."""
        self._jobs.clear()
        self._executions.clear()
        self._running = False
