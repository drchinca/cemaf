"""
Scheduler module.

Provides background task scheduling with cron expressions,
intervals, and async job execution.
"""

from cemaf.scheduler.executor import AsyncJobExecutor
from cemaf.scheduler.factories import (
    create_scheduler_executor,
    create_scheduler_executor_from_config,
    scheduler_registry,
)
from cemaf.scheduler.gates import (
    CompositeGateResult,
    ExecutionGate,
    GateResult,
    LockGate,
    SessionCountGate,
    TimeGate,
    create_execution_gate,
    create_execution_gates,
    evaluate_gates,
    execution_gate_registry,
)
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
    "ExecutionGate",
    "GateResult",
    "CompositeGateResult",
    # Triggers
    "CronTrigger",
    "IntervalTrigger",
    "OnceTrigger",
    "ImmediateTrigger",
    # Executor
    "AsyncJobExecutor",
    "create_scheduler_executor",
    "create_scheduler_executor_from_config",
    "scheduler_registry",
    "TimeGate",
    "SessionCountGate",
    "LockGate",
    "create_execution_gate",
    "create_execution_gates",
    "evaluate_gates",
    "execution_gate_registry",
    # Mock
    "MockScheduler",
    "MockTrigger",
]
