"""
Scheduler protocols and base types.

Defines the contracts for schedulers, jobs, and triggers.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from cemaf.core.types import JSON


class JobStatus(str, Enum):
    """Status of a job execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class JobResult(BaseModel):
    """Result of a job execution."""

    model_config = {"frozen": True}

    job_id: str
    status: JobStatus
    started_at: datetime
    completed_at: datetime | None = None
    result: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    metadata: JSON = Field(default_factory=dict)

    @classmethod
    def success(
        cls,
        job_id: str,
        started_at: datetime,
        result: Any = None,
    ) -> JobResult:
        """Create a successful result."""
        completed_at = datetime.now()
        return cls(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            started_at=started_at,
            completed_at=completed_at,
            result=result,
            duration_ms=(completed_at - started_at).total_seconds() * 1000,
        )

    @classmethod
    def failure(
        cls,
        job_id: str,
        started_at: datetime,
        error: str,
        status: JobStatus = JobStatus.FAILED,
    ) -> JobResult:
        """Create a failed result."""
        completed_at = datetime.now()
        return cls(
            job_id=job_id,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            error=error,
            duration_ms=(completed_at - started_at).total_seconds() * 1000,
        )


@runtime_checkable
class Trigger(Protocol):
    """
    Protocol for job triggers.

    A Trigger determines when a job should run.
    """

    @property
    def name(self) -> str:
        """Trigger identifier."""
        ...

    def next_run(self, after: datetime) -> datetime | None:
        """
        Calculate the next run time after the given datetime.

        Args:
            after: Calculate next run after this time.

        Returns:
            Next run datetime, or None if no more runs.
        """
        ...

    def should_run(self, now: datetime) -> bool:
        """
        Check if the job should run now.

        Args:
            now: Current datetime.

        Returns:
            True if job should run.
        """
        ...


class Job(BaseModel):
    """
    A scheduled job.

    Note: The handler field stores a reference to an async callable.
    """

    model_config = {"frozen": True, "arbitrary_types_allowed": True}

    id: str
    name: str
    trigger: Any  # Trigger (can't use Protocol in Pydantic)
    handler: Callable[[], Awaitable[Any]]
    enabled: bool = True
    max_retries: int = 3
    timeout_seconds: float = 300.0
    metadata: JSON = Field(default_factory=dict)


@runtime_checkable
class Scheduler(Protocol):
    """
    Protocol for job schedulers.

    A Scheduler manages and executes jobs based on their triggers.
    """

    def add_job(self, job: Job) -> None:
        """
        Add a job to the scheduler.

        Args:
            job: Job to schedule.
        """
        ...

    def remove_job(self, job_id: str) -> bool:
        """
        Remove a job from the scheduler.

        Args:
            job_id: ID of job to remove.

        Returns:
            True if job was found and removed.
        """
        ...

    def get_job(self, job_id: str) -> Job | None:
        """
        Get a job by ID.

        Args:
            job_id: Job ID.

        Returns:
            Job or None if not found.
        """
        ...

    def get_jobs(self) -> list[Job]:
        """
        Get all scheduled jobs.

        Returns:
            List of all jobs.
        """
        ...

    async def start(self) -> None:
        """Start the scheduler."""
        ...

    async def stop(self) -> None:
        """Stop the scheduler."""
        ...

    async def run_now(self, job_id: str) -> JobResult:
        """
        Run a job immediately, ignoring its trigger.

        Args:
            job_id: ID of job to run.

        Returns:
            JobResult from execution.

        Raises:
            KeyError: If job not found.
        """
        ...
