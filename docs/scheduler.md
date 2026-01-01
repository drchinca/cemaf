# Scheduler

Job scheduling with various trigger types.

## Scheduler Architecture

```mermaid
flowchart TB
    subgraph Triggers
        INTERVAL[IntervalTrigger<br/>Periodic execution]
        CRON[CronTrigger<br/>Cron expression]
        ONCE[OnceTrigger<br/>Single execution]
    end

    subgraph Executor
        EXEC[AsyncJobExecutor<br/>Job runner]
        QUEUE[Job Queue<br/>Pending jobs]
    end

    subgraph Jobs
        JOB[Job<br/>Async function]
        RESULT[Job Result]
    end

    INTERVAL --> EXEC
    CRON --> EXEC
    ONCE --> EXEC
    EXEC --> QUEUE
    QUEUE --> JOB
    JOB --> RESULT
```

## Scheduling Flow

```mermaid
sequenceDiagram
    participant Client
    participant Executor as AsyncJobExecutor
    participant Trigger
    participant Job

    Client->>Executor: add_job(id, job, trigger)
    Executor->>Trigger: Register

    loop Schedule Loop
        Trigger->>Executor: Time to run
        Executor->>Job: Execute
        Job-->>Executor: Result
        Executor->>Trigger: Reschedule (if recurring)
    end

    Client->>Executor: run_now(job_id)
    Executor->>Job: Execute immediately
    Job-->>Executor: Result
```

## Job Scheduling

```python
from cemaf.scheduler.executor import AsyncJobExecutor
from cemaf.scheduler.triggers import IntervalTrigger

executor = AsyncJobExecutor()

# Schedule job
await executor.add_job(
    job_id="daily_task",
    job=my_async_function,
    trigger=IntervalTrigger(seconds=86400)
)

# Run now
await executor.run_now("daily_task")
```
