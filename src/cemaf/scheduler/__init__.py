"""
Scheduler module.

Provides background task scheduling with cron expressions,
intervals, and async job execution.
"""

from cemaf.scheduler.executor import AsyncJobExecutor
from cemaf.scheduler.mock import MockScheduler, MockTrigger
from cemaf.scheduler.protocols import (
    Job,
    JobResult,
    JobStatus,
    Scheduler,
    Trigger,
)
from cemaf.scheduler.triggers import (
    CronTrigger,
    ImmediateTrigger,
    IntervalTrigger,
    OnceTrigger,
)

__all__ = [
    # Protocols
    "Trigger",
    "Job",
    "JobResult",
    "JobStatus",
    "Scheduler",
    # Triggers
    "CronTrigger",
    "IntervalTrigger",
    "OnceTrigger",
    "ImmediateTrigger",
    # Executor
    "AsyncJobExecutor",
    # Mock
    "MockScheduler",
    "MockTrigger",
]
