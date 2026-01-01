"""
Async job executor and scheduler implementation.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

from cemaf.scheduler.protocols import Job, JobResult, JobStatus

logger = logging.getLogger(__name__)


class AsyncJobExecutor:
    """
    Async job scheduler and executor.

    Runs jobs based on their triggers with support for:
    - Concurrent execution
    - Timeout handling
    - Retry logic
    - Error callbacks
    """

    def __init__(
        self,
        max_concurrent: int = 10,
        check_interval_seconds: float = 1.0,
        on_job_complete: Callable[[JobResult], Awaitable[None]] | None = None,
        on_job_error: Callable[[str, Exception], Awaitable[None]] | None = None,
    ) -> None:
        """
        Initialize job executor.

        Args:
            max_concurrent: Maximum concurrent job executions.
            check_interval_seconds: How often to check for jobs to run.
            on_job_complete: Callback when job completes.
            on_job_error: Callback when job fails.
        """
        self._jobs: dict[str, Job] = {}
        self._max_concurrent = max_concurrent
        self._check_interval = check_interval_seconds
        self._on_complete = on_job_complete
        self._on_error = on_job_error
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._results: list[JobResult] = []

    def add_job(self, job: Job) -> None:
        """Add a job to the scheduler."""
        self._jobs[job.id] = job
        logger.debug("Added job: %s (%s)", job.name, job.id)

    def remove_job(self, job_id: str) -> bool:
        """Remove a job from the scheduler."""
        if job_id in self._jobs:
            del self._jobs[job_id]
            logger.debug("Removed job: %s", job_id)
            return True
        return False

    def get_job(self, job_id: str) -> Job | None:
        """Get a job by ID."""
        return self._jobs.get(job_id)

    def get_jobs(self) -> list[Job]:
        """Get all jobs."""
        return list(self._jobs.values())

    @property
    def results(self) -> list[JobResult]:
        """Get all job results."""
        return list(self._results)

    async def start(self) -> None:
        """Start the scheduler loop."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("Scheduler started")

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False

        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

        logger.info("Scheduler stopped")

    async def run_now(self, job_id: str) -> JobResult:
        """Run a job immediately."""
        job = self._jobs.get(job_id)
        if not job:
            raise KeyError(f"Job not found: {job_id}")

        return await self._execute_job(job)

    async def _scheduler_loop(self) -> None:
        """Main scheduler loop."""
        while self._running:
            try:
                now = datetime.now()

                for job in list(self._jobs.values()):
                    if not job.enabled:
                        continue

                    if job.trigger.should_run(now):
                        # Schedule job execution
                        asyncio.create_task(self._execute_with_semaphore(job))

                        # Mark trigger as run if it supports it
                        if hasattr(job.trigger, "mark_run"):
                            job.trigger.mark_run(now)

                await asyncio.sleep(self._check_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Scheduler loop error: %s", e)

    async def _execute_with_semaphore(self, job: Job) -> None:
        """Execute job with concurrency limiting."""
        async with self._semaphore:
            result = await self._execute_job(job)
            self._results.append(result)

            if self._on_complete:
                try:
                    await self._on_complete(result)
                except Exception as e:
                    logger.error("on_complete callback error: %s", e)

    async def _execute_job(self, job: Job) -> JobResult:
        """Execute a single job with timeout and retries."""
        started_at = datetime.now()
        last_error: str | None = None

        for attempt in range(max(1, job.max_retries)):
            try:
                # Execute with timeout
                result = await asyncio.wait_for(
                    job.handler(),
                    timeout=job.timeout_seconds,
                )

                return JobResult.success(
                    job_id=job.id,
                    started_at=started_at,
                    result=result,
                )

            except TimeoutError:
                last_error = f"Timeout after {job.timeout_seconds}s"
                logger.warning(
                    "Job %s timed out (attempt %d/%d)",
                    job.id,
                    attempt + 1,
                    job.max_retries,
                )

            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "Job %s failed (attempt %d/%d): %s",
                    job.id,
                    attempt + 1,
                    job.max_retries,
                    e,
                )

                if self._on_error:
                    with contextlib.suppress(Exception):
                        await self._on_error(job.id, e)

            # Wait before retry
            if attempt < job.max_retries - 1:
                await asyncio.sleep(0.5 * (attempt + 1))

        # All retries exhausted
        status = JobStatus.TIMEOUT if "Timeout" in (last_error or "") else JobStatus.FAILED
        return JobResult.failure(
            job_id=job.id,
            started_at=started_at,
            error=last_error or "Unknown error",
            status=status,
        )
