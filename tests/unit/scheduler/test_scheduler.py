"""Tests for scheduler module."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from cemaf.scheduler.executor import AsyncJobExecutor
from cemaf.scheduler.mock import MockScheduler, MockTrigger
from cemaf.scheduler.protocols import (
    Job,
    JobResult,
    JobStatus,
)
from cemaf.scheduler.triggers import (
    CronTrigger,
    ImmediateTrigger,
    IntervalTrigger,
    OnceTrigger,
)

# =============================================================================
# JobResult Tests
# =============================================================================


class TestJobResult:
    """Tests for JobResult model."""

    def test_success_factory(self) -> None:
        """Test success factory method."""
        started = datetime.now()
        result = JobResult.success(
            job_id="job1",
            started_at=started,
            result={"data": "value"},
        )

        assert result.status == JobStatus.COMPLETED
        assert result.job_id == "job1"
        assert result.result == {"data": "value"}
        assert result.error is None

    def test_failure_factory(self) -> None:
        """Test failure factory method."""
        started = datetime.now()
        result = JobResult.failure(
            job_id="job1",
            started_at=started,
            error="Something went wrong",
        )

        assert result.status == JobStatus.FAILED
        assert result.error == "Something went wrong"

    def test_duration_calculated(self) -> None:
        """Test duration is calculated."""
        started = datetime.now() - timedelta(seconds=1)
        result = JobResult.success(job_id="job1", started_at=started)

        assert result.duration_ms >= 1000


# =============================================================================
# CronTrigger Tests
# =============================================================================


class TestCronTrigger:
    """Tests for CronTrigger."""

    def test_parse_simple_expression(self) -> None:
        """Test parsing simple cron expression."""
        trigger = CronTrigger("0 9 * * *")  # Daily at 9am
        assert trigger.expression == "0 9 * * *"

    def test_invalid_expression(self) -> None:
        """Test invalid expression raises error."""
        with pytest.raises(ValueError):
            CronTrigger("invalid")

    def test_should_run_at_matching_time(self) -> None:
        """Test should_run returns True at matching time."""
        trigger = CronTrigger("30 10 * * *")  # 10:30 daily

        matching_time = datetime(2024, 1, 15, 10, 30)
        assert trigger.should_run(matching_time) is True

        non_matching = datetime(2024, 1, 15, 10, 31)
        assert trigger.should_run(non_matching) is False

    def test_next_run_calculation(self) -> None:
        """Test next_run returns next matching time."""
        trigger = CronTrigger("0 * * * *")  # Every hour

        now = datetime(2024, 1, 15, 10, 30)
        next_run = trigger.next_run(now)

        assert next_run is not None
        assert next_run.hour == 11
        assert next_run.minute == 0

    def test_every_minute(self) -> None:
        """Test every minute expression."""
        trigger = CronTrigger("* * * * *")

        now = datetime(2024, 1, 15, 10, 30, 45)
        assert trigger.should_run(now) is True

    def test_name_property(self) -> None:
        """Test trigger name."""
        trigger = CronTrigger("0 9 * * *", name="morning_job")
        assert trigger.name == "morning_job"


# =============================================================================
# IntervalTrigger Tests
# =============================================================================


class TestIntervalTrigger:
    """Tests for IntervalTrigger."""

    def test_create_with_seconds(self) -> None:
        """Test creating with seconds."""
        trigger = IntervalTrigger(seconds=30)
        assert trigger.interval == timedelta(seconds=30)

    def test_create_with_minutes(self) -> None:
        """Test creating with minutes."""
        trigger = IntervalTrigger(minutes=5)
        assert trigger.interval == timedelta(minutes=5)

    def test_create_with_hours(self) -> None:
        """Test creating with hours."""
        trigger = IntervalTrigger(hours=2)
        assert trigger.interval == timedelta(hours=2)

    def test_combined_units(self) -> None:
        """Test combining multiple units."""
        trigger = IntervalTrigger(hours=1, minutes=30)
        assert trigger.interval == timedelta(hours=1, minutes=30)

    def test_zero_interval_raises(self) -> None:
        """Test zero interval raises error."""
        with pytest.raises(ValueError):
            IntervalTrigger()

    def test_should_run_first_time(self) -> None:
        """Test should_run returns True on first call."""
        trigger = IntervalTrigger(seconds=60)
        assert trigger.should_run(datetime.now()) is True

    def test_should_run_after_interval(self) -> None:
        """Test should_run after interval passes."""
        trigger = IntervalTrigger(seconds=1)
        now = datetime.now()

        trigger.mark_run(now)

        assert trigger.should_run(now) is False
        assert trigger.should_run(now + timedelta(seconds=2)) is True

    def test_next_run_calculation(self) -> None:
        """Test next_run returns correct time."""
        trigger = IntervalTrigger(minutes=10)
        now = datetime.now()

        next_run = trigger.next_run(now)
        assert next_run == now  # First run is immediate

        trigger.mark_run(now)

        next_run = trigger.next_run(now)
        assert next_run == now + timedelta(minutes=10)


# =============================================================================
# OnceTrigger Tests
# =============================================================================


class TestOnceTrigger:
    """Tests for OnceTrigger."""

    def test_should_run_at_scheduled_time(self) -> None:
        """Test should_run at scheduled time."""
        run_at = datetime(2024, 6, 15, 12, 0)
        trigger = OnceTrigger(run_at=run_at)

        # Before scheduled time
        assert trigger.should_run(datetime(2024, 6, 15, 11, 59)) is False

        # At or after scheduled time
        assert trigger.should_run(datetime(2024, 6, 15, 12, 0)) is True
        assert trigger.should_run(datetime(2024, 6, 15, 12, 1)) is True

    def test_only_runs_once(self) -> None:
        """Test trigger only fires once."""
        run_at = datetime(2024, 6, 15, 12, 0)
        trigger = OnceTrigger(run_at=run_at)

        assert trigger.should_run(datetime(2024, 6, 15, 12, 0)) is True

        trigger.mark_run()

        assert trigger.should_run(datetime(2024, 6, 15, 12, 0)) is False

    def test_next_run_after_marked(self) -> None:
        """Test next_run returns None after marked."""
        run_at = datetime(2024, 6, 15, 12, 0)
        trigger = OnceTrigger(run_at=run_at)

        trigger.mark_run()

        assert trigger.next_run(datetime.now()) is None


# =============================================================================
# ImmediateTrigger Tests
# =============================================================================


class TestImmediateTrigger:
    """Tests for ImmediateTrigger."""

    def test_runs_immediately(self) -> None:
        """Test trigger fires immediately."""
        trigger = ImmediateTrigger()
        assert trigger.should_run(datetime.now()) is True

    def test_only_runs_once(self) -> None:
        """Test trigger only fires once."""
        trigger = ImmediateTrigger()

        trigger.mark_run()

        assert trigger.should_run(datetime.now()) is False


# =============================================================================
# AsyncJobExecutor Tests
# =============================================================================


class TestAsyncJobExecutor:
    """Tests for AsyncJobExecutor."""

    async def test_add_and_get_job(self) -> None:
        """Test adding and retrieving jobs."""
        executor = AsyncJobExecutor()

        job = Job(
            id="job1",
            name="Test Job",
            trigger=MockTrigger(),
            handler=lambda: asyncio.sleep(0),
        )

        executor.add_job(job)

        assert executor.get_job("job1") is not None
        assert len(executor.get_jobs()) == 1

    async def test_remove_job(self) -> None:
        """Test removing a job."""
        executor = AsyncJobExecutor()

        job = Job(
            id="job1",
            name="Test Job",
            trigger=MockTrigger(),
            handler=lambda: asyncio.sleep(0),
        )

        executor.add_job(job)
        result = executor.remove_job("job1")

        assert result is True
        assert executor.get_job("job1") is None

    async def test_run_now(self) -> None:
        """Test running a job immediately."""
        executor = AsyncJobExecutor()

        executed = False

        async def handler() -> str:
            nonlocal executed
            executed = True
            return "done"

        job = Job(
            id="job1",
            name="Test Job",
            trigger=MockTrigger(),
            handler=handler,
        )

        executor.add_job(job)
        result = await executor.run_now("job1")

        assert executed is True
        assert result.status == JobStatus.COMPLETED
        assert result.result == "done"

    async def test_run_now_nonexistent(self) -> None:
        """Test running non-existent job raises error."""
        executor = AsyncJobExecutor()

        with pytest.raises(KeyError):
            await executor.run_now("nonexistent")

    async def test_job_timeout(self) -> None:
        """Test job timeout handling."""
        executor = AsyncJobExecutor()

        async def slow_handler() -> None:
            await asyncio.sleep(10)

        job = Job(
            id="job1",
            name="Slow Job",
            trigger=MockTrigger(),
            handler=slow_handler,
            timeout_seconds=0.01,
            max_retries=1,
        )

        executor.add_job(job)
        result = await executor.run_now("job1")

        assert result.status == JobStatus.TIMEOUT

    async def test_job_failure_and_retry(self) -> None:
        """Test job failure and retry."""
        executor = AsyncJobExecutor()

        attempt_count = 0

        async def failing_handler() -> None:
            nonlocal attempt_count
            attempt_count += 1
            raise ValueError("Intentional failure")

        job = Job(
            id="job1",
            name="Failing Job",
            trigger=MockTrigger(),
            handler=failing_handler,
            max_retries=3,
        )

        executor.add_job(job)
        result = await executor.run_now("job1")

        assert result.status == JobStatus.FAILED
        assert attempt_count == 3  # Tried 3 times

    async def test_error_callback(self) -> None:
        """Test error callback is called."""
        errors: list[tuple[str, Exception]] = []

        async def on_error(job_id: str, error: Exception) -> None:
            errors.append((job_id, error))

        executor = AsyncJobExecutor(on_job_error=on_error)

        async def failing_handler() -> None:
            raise ValueError("Error")

        job = Job(
            id="job1",
            name="Failing Job",
            trigger=MockTrigger(),
            handler=failing_handler,
            max_retries=1,
        )

        executor.add_job(job)
        await executor.run_now("job1")

        assert len(errors) == 1
        assert errors[0][0] == "job1"


# =============================================================================
# MockScheduler Tests
# =============================================================================


class TestMockScheduler:
    """Tests for MockScheduler."""

    async def test_add_job(self) -> None:
        """Test adding jobs to mock."""
        scheduler = MockScheduler()

        job = Job(
            id="job1",
            name="Test Job",
            trigger=MockTrigger(),
            handler=lambda: asyncio.sleep(0),
        )

        scheduler.add_job(job)

        assert "job1" in scheduler.jobs

    async def test_run_now_records_execution(self) -> None:
        """Test run_now records execution."""
        scheduler = MockScheduler()

        async def handler() -> str:
            return "result"

        job = Job(
            id="job1",
            name="Test Job",
            trigger=MockTrigger(),
            handler=handler,
        )

        scheduler.add_job(job)
        result = await scheduler.run_now("job1")

        assert len(scheduler.executions) == 1
        assert scheduler.executions[0][0] == "job1"
        assert result.result == "result"

    async def test_start_stop(self) -> None:
        """Test start and stop."""
        scheduler = MockScheduler()

        await scheduler.start()
        assert scheduler.is_running is True

        await scheduler.stop()
        assert scheduler.is_running is False

    async def test_reset(self) -> None:
        """Test reset clears state."""
        scheduler = MockScheduler()

        job = Job(
            id="job1",
            name="Test Job",
            trigger=MockTrigger(),
            handler=lambda: asyncio.sleep(0),
        )

        scheduler.add_job(job)
        scheduler.reset()

        assert len(scheduler.jobs) == 0
        assert len(scheduler.executions) == 0


# =============================================================================
# MockTrigger Tests
# =============================================================================


class TestMockTrigger:
    """Tests for MockTrigger."""

    def test_configurable_should_fire(self) -> None:
        """Test should_fire is configurable."""
        trigger = MockTrigger(should_fire=True)
        assert trigger.should_run(datetime.now()) is True

        trigger.set_should_fire(False)
        assert trigger.should_run(datetime.now()) is False

    def test_mark_run_resets_fire(self) -> None:
        """Test mark_run resets should_fire."""
        trigger = MockTrigger(should_fire=True)

        trigger.mark_run()

        assert trigger.should_run(datetime.now()) is False
        assert trigger.fire_count == 1

    def test_configurable_next_run(self) -> None:
        """Test next_run time is configurable."""
        next_time = datetime(2024, 6, 15, 12, 0)
        trigger = MockTrigger(next_run_time=next_time)

        assert trigger.next_run(datetime.now()) == next_time
