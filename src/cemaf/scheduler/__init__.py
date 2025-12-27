"""
Scheduler module.

Provides background task scheduling with cron expressions,
intervals, and async job execution.
"""

from cemaf.scheduler.protocols import (
    Trigger,
    Job,
    JobResult,
    JobStatus,
    Scheduler,
)
from cemaf.scheduler.triggers import (
    CronTrigger,
    IntervalTrigger,
    OnceTrigger,
    ImmediateTrigger,
)
from cemaf.scheduler.executor import AsyncJobExecutor
from cemaf.scheduler.mock import MockScheduler, MockTrigger

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

