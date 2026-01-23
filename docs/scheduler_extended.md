# Scheduler Module - Extended Documentation

## Overview

The scheduler module provides background task scheduling with support for cron expressions, intervals, one-time execution, and immediate execution with async job handling.

**What it does**: Schedules async jobs to run at specific times or intervals, executes them with configurable triggers (cron, interval, once, immediate), tracks job status and results, and supports job failure handling. Uses async/await patterns for non-blocking execution.

**Key use cases**:
- Schedule daily/weekly content generation runs
- Publish scheduled content at optimal times
- Refresh trending topics and data periodically
- Clean up old logs and expired cache entries
- Monitor system health on intervals
- Execute time-sensitive tasks (publish at 9 AM, analyze weekly trends)

**When to use vs. alternatives**: Use scheduler for recurring tasks and time-based execution. Use it for periodic maintenance, content publishing windows, and data refreshes. Don't use for immediate job execution (use direct async calls) or complex workflow orchestration (use DAGs).

## Core Concepts

### Trigger Types

**CronTrigger**: Unix cron expressions for complex schedules. "0 9 * * MON" = 9 AM every Monday. Supports minute, hour, day, month, weekday.

**IntervalTrigger**: Repeat every N seconds/minutes/hours. Execute every 1 hour, every 30 minutes, etc.

**OnceTrigger**: Execute once at specific time, then never again.

**ImmediateTrigger**: Execute immediately and only once. Useful for testing and manual execution.

### Job Lifecycle

**Scheduled**: Job registered but not running. Waiting for trigger time.

**Running**: Job is currently executing.

**Completed**: Job finished successfully. Result available.

**Failed**: Job failed with error. Error message captured.

**Cancelled**: Job was cancelled before execution.

### Job Result Tracking

JobResult captures:
- Status (completed, failed, cancelled)
- Duration of execution
- Result data (if successful)
- Error details (if failed)
- Execution metadata (when ran, how long)

## Usage Examples

### Schedule Daily Content Generation

```python
from cemaf.scheduler import Scheduler, CronTrigger, Job, JobStatus

scheduler = Scheduler()

# Define job
async def generate_daily_content():
    """Generate content for all projects."""
    projects = await project_store.list_by_status()

    for project in projects:
        run = Run(
            project_id=project.id,
            pipeline="daily_generation",
            inputs={"date": date.today().isoformat()}
        )
        await orchestrator.execute(run)

    return {"projects_processed": len(projects)}

# Schedule at 9 AM every day
job = Job(
    name="daily_content_generation",
    func=generate_daily_content,
    trigger=CronTrigger("0 9 * * *"),  # 9 AM every day
)

await scheduler.schedule(job)
```

### Weekly Analysis and Reporting

```python
from cemaf.scheduler import IntervalTrigger
import datetime

async def analyze_weekly_performance():
    """Run weekly performance analysis."""
    # Get metrics from last 7 days
    one_week_ago = datetime.datetime.now() - datetime.timedelta(days=7)
    runs = await run_store.list_by_project(
        status=RunStatus.COMPLETED,
        since=one_week_ago
    )

    # Calculate metrics
    total_cost = sum(r.total_cost_usd for r in runs)
    avg_duration = sum(r.duration_seconds for r in runs) / len(runs)

    # Generate report
    report = {
        "period": "last_7_days",
        "runs_completed": len(runs),
        "total_cost": total_cost,
        "avg_duration": avg_duration,
        "recommendations": []
    }

    if total_cost > 100:
        report["recommendations"].append("Cost increasing, review optimization")

    return report

# Schedule weekly (every Monday at midnight)
job = Job(
    name="weekly_performance_analysis",
    func=analyze_weekly_performance,
    trigger=CronTrigger("0 0 * * MON"),
)

await scheduler.schedule(job)

# Or every 7 days from now
job = Job(
    name="weekly_performance_analysis",
    func=analyze_weekly_performance,
    trigger=IntervalTrigger(seconds=7 * 24 * 3600),
)

await scheduler.schedule(job)
```

### Cleanup and Maintenance

```python
from cemaf.scheduler import IntervalTrigger

async def cleanup_old_records():
    """Remove completed runs older than 90 days."""
    cutoff_date = datetime.datetime.now() - datetime.timedelta(days=90)

    # Delete old runs
    deleted = await run_store.delete_before(cutoff_date)

    # Clear expired cache
    cache_deleted = await cache.clear_expired()

    return {
        "runs_deleted": deleted,
        "cache_items_cleared": cache_deleted
    }

# Run every night at 2 AM
job = Job(
    name="nightly_cleanup",
    func=cleanup_old_records,
    trigger=CronTrigger("0 2 * * *"),
)

await scheduler.schedule(job)

# Monitor cleanup
result = await scheduler.get_job_result("nightly_cleanup")
if result.status == JobStatus.FAILED:
    print(f"Cleanup failed: {result.error}")
```

### Publishing Scheduled Content

```python
from cemaf.scheduler import IntervalTrigger

async def publish_scheduled_content():
    """Publish any content scheduled for now or earlier."""
    now = datetime.datetime.now(timezone.utc)

    # Get scheduled content ready to publish
    content_items = await content_store.list_scheduled(limit=100)

    published = []
    for item in content_items:
        if item.scheduled_at <= now:
            # Publish to platform
            success = await publisher.publish(item)

            if success:
                published.append(item.id)
                # Update status
                await content_store.update(
                    item.with_status(ContentStatus.PUBLISHED)
                )

    return {"published": len(published)}

# Check every 5 minutes
job = Job(
    name="publish_scheduled_content",
    func=publish_scheduled_content,
    trigger=IntervalTrigger(seconds=5 * 60),
)

await scheduler.schedule(job)
```

### Health Check Monitoring

```python
from cemaf.observability.health import HealthChecker

async def monitor_system_health():
    """Check system health and alert if degraded."""
    checker = HealthChecker()
    health = await checker.check_all()

    if health.status != HealthStatus.HEALTHY:
        # Send alert
        await alerter.send({
            "level": "warning",
            "message": f"System health: {health.status}",
            "details": {
                name: check.message
                for name, check in health.checks.items()
                if check.status != HealthStatus.HEALTHY
            }
        })

    return health.to_dict()

# Check every 5 minutes
job = Job(
    name="health_monitor",
    func=monitor_system_health,
    trigger=IntervalTrigger(seconds=5 * 60),
)

await scheduler.schedule(job)
```

### Complex Cron Expressions

```python
from cemaf.scheduler import CronTrigger

# 9 AM every weekday
weekday_9am = CronTrigger("0 9 * * MON-FRI")

# Midnight on first day of each month
monthly = CronTrigger("0 0 1 * *")

# Every 30 minutes during business hours (9 AM - 5 PM)
business_hours = CronTrigger("*/30 9-17 * * *")

# 3 AM on Sundays (weekly maintenance window)
maintenance_window = CronTrigger("0 3 * * SUN")

# Multiple times: 9 AM and 6 PM
morning_evening = CronTrigger("0 9,18 * * *")
```

### Job Monitoring and Debugging

```python
# Get job status
job_result = await scheduler.get_job_result("daily_content_generation")

if job_result.status == JobStatus.FAILED:
    print(f"Job failed: {job_result.error}")
    print(f"Duration: {job_result.duration_ms}ms")
    # Retry or alert

elif job_result.status == JobStatus.COMPLETED:
    print(f"Job succeeded: {job_result.result}")
    print(f"Duration: {job_result.duration_ms}ms")

# List all jobs
all_jobs = await scheduler.list_jobs()
for job_info in all_jobs:
    print(f"{job_info.name}: {job_info.status}")

# Cancel a job
await scheduler.cancel_job("daily_content_generation")
```

### Common Mistake: Blocking Execution

```python
# ❌ WRONG - Synchronous execution blocks scheduler
async def slow_job():
    # This blocks the scheduler thread
    time.sleep(10)  # Don't do this!
    return "done"

# ✅ CORRECT - Use async throughout
async def slow_job():
    # Non-blocking async
    await asyncio.sleep(10)
    return "done"

# Or use async wrappers
async def blocking_job():
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, blocking_function)
    return result
```

## Integration

### With Orchestration

```python
from cemaf.scheduler import Scheduler, Job, CronTrigger

# Schedule pipeline execution
async def run_content_pipeline():
    orchestrator = Orchestrator()
    run = Run(
        project_id=project_id,
        pipeline="content_generation"
    )
    return await orchestrator.execute(run)

scheduler = Scheduler()
job = Job(
    name="scheduled_pipeline",
    func=run_content_pipeline,
    trigger=CronTrigger("0 9 * * *")
)
await scheduler.schedule(job)
```

### With Observability

```python
from cemaf.observability.logger import StructuredLogger

logger = StructuredLogger()

async def job_with_logging():
    start = time.time()

    try:
        result = await execute_job()
        duration = time.time() - start

        await logger.info(
            "Scheduled job completed",
            job_name="test_job",
            duration_seconds=duration,
            result=result
        )

        return result
    except Exception as e:
        await logger.error(
            "Scheduled job failed",
            job_name="test_job",
            error=str(e)
        )
        raise
```

### With Persistence

```python
# Store job results
async def save_job_result():
    result = await scheduler.get_job_result("daily_analysis")

    run = Run(
        project_id=project_id,
        pipeline="scheduled_analysis",
        outputs=result.result,
        status=RunStatus.COMPLETED if result.success else RunStatus.FAILED
    )

    await run_store.create(run)
```

## API Reference

### Trigger Implementations

```python
class CronTrigger:
    """Unix cron expression trigger."""
    def __init__(self, expression: str):
        """
        Args:
            expression: Cron format "minute hour day month weekday"
                       e.g., "0 9 * * MON" = 9 AM Monday
        """

class IntervalTrigger:
    """Repeat every N time units."""
    def __init__(
        self,
        seconds: int | None = None,
        minutes: int | None = None,
        hours: int | None = None,
        days: int | None = None
    ):
        """Provide one time unit. E.g., minutes=30 = every 30 minutes."""

class OnceTrigger:
    """Execute once at specific time."""
    def __init__(self, at: datetime):
        """Execute at specific datetime."""

class ImmediateTrigger:
    """Execute immediately."""
```

### Job

```python
@dataclass
class Job:
    name: str
    func: Callable[[], Awaitable[Any]]  # Async function
    trigger: Trigger                     # When to run
    max_retries: int = 0                # Retry on failure
    timeout_seconds: int | None = None  # Execution timeout
```

### JobStatus

```python
class JobStatus(str, Enum):
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

### JobResult

```python
@dataclass
class JobResult:
    job_name: str
    status: JobStatus
    result: Any | None = None
    error: str | None = None
    duration_ms: float = 0.0
    executed_at: datetime | None = None
```

### Scheduler Protocol

```python
@runtime_checkable
class Scheduler(Protocol):
    async def schedule(self, job: Job) -> None:
        """Schedule a job."""

    async def unschedule(self, job_name: str) -> bool:
        """Remove a scheduled job."""

    async def get_job_result(self, job_name: str) -> JobResult | None:
        """Get result of last execution."""

    async def list_jobs(self) -> list[JobInfo]:
        """List all scheduled jobs."""

    async def cancel_job(self, job_name: str) -> bool:
        """Cancel running job."""
```

## Best Practices

### Performance Tips

- **Async throughout**: Never block in scheduled jobs
- **Timeouts**: Always set reasonable timeouts to prevent stuck jobs
- **Batching**: Batch operations to reduce overhead
- **Parallel jobs**: Run independent jobs in parallel

### Cron Expression Patterns

```python
SCHEDULES = {
    "hourly": "0 * * * *",
    "every_30_min": "*/30 * * * *",
    "daily_9am": "0 9 * * *",
    "daily_midnight": "0 0 * * *",
    "weekdays_9am": "0 9 * * MON-FRI",
    "mondays_midnight": "0 0 * * MON",
    "monthly_first": "0 0 1 * *",
    "quarterly": "0 0 1 */3 *",
}
```

### Common Pitfalls

**Long-running jobs**: Don't schedule jobs that take hours. Break into smaller tasks.

**Overlapping execution**: Ensure previous job finishes before next starts. Scheduler should prevent this.

**Lost errors**: Always log job failures. Monitor job status.

**No idempotency**: Ensure jobs can be safely retried. Use idempotent operations.

**Timezone issues**: Cron times are in local or UTC. Be explicit about timezone.

### When NOT to Use

- **One-time tasks**: Use direct execution, not scheduler
- **Real-time tasks**: Need immediate execution, not scheduled
- **Complex workflows**: Use orchestration, not simple scheduler
- **Urgent tasks**: Don't wait for scheduled time

### Job Design Pattern

```python
async def well_designed_job():
    """Good job design pattern."""
    job_id = generate_id()
    start = time.time()

    try:
        # Get necessary context
        logger.info("Job starting", job_id=job_id)

        # Do work with timeout
        result = await do_work_with_timeout()

        duration = time.time() - start
        logger.info(
            "Job completed",
            job_id=job_id,
            duration_seconds=duration
        )

        # Persist result
        await store_result(result)
        return result

    except asyncio.TimeoutError:
        logger.error("Job timeout", job_id=job_id)
        raise
    except Exception as e:
        logger.error("Job failed", job_id=job_id, error=str(e))
        raise
```
