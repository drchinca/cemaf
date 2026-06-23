"""
Scheduler module.

Provides background task scheduling with cron expressions,
intervals, and async job execution.
"""

from cemaf.scheduler.executor import AsyncJobExecutor
from cemaf.scheduler.factories import (
    create_scheduler_executor,
    create_scheduler_executor_from_config,
)
from cemaf.scheduler.mock import MockScheduler, MockTrigger
from cemaf.scheduler.nightshift import NightShiftGate, NightShiftTrigger, NightShiftWindow
from cemaf.scheduler.primitives import JobDefinition, JobKind
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
    "create_scheduler_executor",
    "create_scheduler_executor_from_config",
    # Job definitions
    "JobKind",
    "JobDefinition",
    # Nightshift
    "NightShiftWindow",
    "NightShiftGate",
    "NightShiftTrigger",
    # Mock
    "MockScheduler",
    "MockTrigger",
]
