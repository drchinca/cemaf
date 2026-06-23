"""Dog-fooded meta-scheduler — wire meta-agents as autonomous background citizens.

SPEC-11. Turns the three pre-built meta DAGs (self_audit, knowledge_refresh) and
the dreaming-mode composition into ``ManagedScheduler`` jobs with sensible
defaults: durable run records, lease-based singleton enforcement, heartbeat
liveness, and quiet-hours gating via ``NightShiftWindow``.

After ``bootstrap_meta_dogfood(...)``, a CEMAF deployment running 24h
unattended will have consolidated its memory, audited its own traces, and
refreshed its knowledge graph — using only CEMAF primitives.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from cemaf.core.types import JSON
from cemaf.core.utils import safe_json
from cemaf.memory.manager import MemoryManager
from cemaf.meta.dags import create_knowledge_refresh_dag, create_self_audit_dag
from cemaf.meta.dreaming import DreamingMode
from cemaf.orchestration.executor import DAGExecutor
from cemaf.scheduler.nightshift import NightShiftTrigger, NightShiftWindow
from cemaf.scheduler.primitives import JobDefinition, JobKind, ManagedScheduler
from cemaf.scheduler.protocols import Trigger
from cemaf.scheduler.triggers import IntervalTrigger

SELF_AUDIT_JOB_ID = "meta.self_audit"
KNOWLEDGE_REFRESH_JOB_ID = "meta.knowledge_refresh"
DREAMING_JOB_ID = "meta.dreaming"


@dataclass(frozen=True)
class DogfoodJobs:
    """Handles to the meta jobs registered against a ``ManagedScheduler``."""

    self_audit: JobDefinition
    knowledge_refresh: JobDefinition
    dreaming: JobDefinition


@dataclass(frozen=True)
class DogfoodDefaults:
    """Defaults for ``bootstrap_meta_dogfood``. Override per-job by passing fields."""

    self_audit_interval: timedelta = field(default_factory=lambda: timedelta(hours=6))
    knowledge_refresh_interval: timedelta = field(default_factory=lambda: timedelta(hours=12))
    dreaming_interval: timedelta = field(default_factory=lambda: timedelta(hours=4))
    dreaming_min_sessions: int | None = 3
    dreaming_use_lock_gate: bool = True
    nightshift_window: NightShiftWindow | None = field(default_factory=NightShiftWindow)


def _wrap_with_nightshift(*, base: Trigger, window: NightShiftWindow | None, job_id: str) -> Trigger:
    if window is None:
        return base
    return NightShiftTrigger(base_trigger=base, window=window, name=f"{job_id}.nightshift")


def _dag_handler(*, executor: DAGExecutor, dag_factory: Callable[[], Any]) -> Callable[[], Awaitable[JSON]]:
    async def handler() -> JSON:
        result = await executor.run(dag=dag_factory())
        payload: JSON = {
            "run_id": str(result.run_id),
            "success": result.success,
            "final_context": result.final_context.to_dict() if result.final_context else {},
            "error": result.error,
        }
        return safe_json(payload)  # type: ignore[no-any-return]

    return handler


async def register_self_audit_job(
    scheduler: ManagedScheduler,
    *,
    executor: DAGExecutor,
    interval: timedelta = timedelta(hours=6),
    nightshift: NightShiftWindow | None = None,
    job_id: str = SELF_AUDIT_JOB_ID,
) -> JobDefinition:
    """Register the self-audit DAG to run on an interval, optionally nightshift-gated."""
    base = IntervalTrigger(seconds=int(interval.total_seconds()), name=f"{job_id}.interval")
    trigger = _wrap_with_nightshift(base=base, window=nightshift, job_id=job_id)
    tags: tuple[str, ...] = ("audit",) + (("nightshift",) if nightshift else ())
    definition = JobDefinition(
        id=job_id,
        name="Meta Self-Audit",
        trigger=trigger,
        kind=JobKind.SYSTEM,
        tags=tags,
        metadata={"dag": "self_audit"},
    )
    await scheduler.register_job(
        definition=definition,
        handler=_dag_handler(executor=executor, dag_factory=create_self_audit_dag),
    )
    return definition


async def register_knowledge_refresh_job(
    scheduler: ManagedScheduler,
    *,
    executor: DAGExecutor,
    interval: timedelta = timedelta(hours=12),
    nightshift: NightShiftWindow | None = None,
    job_id: str = KNOWLEDGE_REFRESH_JOB_ID,
) -> JobDefinition:
    """Register the knowledge-refresh DAG to run on an interval, optionally nightshift-gated."""
    base = IntervalTrigger(seconds=int(interval.total_seconds()), name=f"{job_id}.interval")
    trigger = _wrap_with_nightshift(base=base, window=nightshift, job_id=job_id)
    tags: tuple[str, ...] = ("knowledge",) + (("nightshift",) if nightshift else ())
    definition = JobDefinition(
        id=job_id,
        name="Meta Knowledge Refresh",
        trigger=trigger,
        kind=JobKind.SYSTEM,
        tags=tags,
        metadata={"dag": "knowledge_refresh"},
    )
    await scheduler.register_job(
        definition=definition,
        handler=_dag_handler(executor=executor, dag_factory=create_knowledge_refresh_dag),
    )
    return definition


async def register_dreaming_job(
    scheduler: ManagedScheduler,
    *,
    memory_manager: MemoryManager,
    interval: timedelta = timedelta(hours=4),
    min_sessions: int | None = 3,
    use_lock_gate: bool = True,
    nightshift: NightShiftWindow | None = None,
    job_id: str = DREAMING_JOB_ID,
) -> JobDefinition:
    """Register the dreaming-mode composition (DreamAgent + gates) as a scheduled job."""
    mode = DreamingMode(
        job_id=job_id,
        job_name="Meta Dreaming Mode",
        trigger=IntervalTrigger(seconds=int(interval.total_seconds()), name=f"{job_id}.interval"),
        min_interval=interval,
        min_sessions=min_sessions,
        use_lock_gate=use_lock_gate,
        nightshift=nightshift,
        metadata={"source": "bootstrap_meta_dogfood"},
    )
    handle = mode.build(memory_manager=memory_manager)
    await scheduler.register_job(definition=handle.definition, handler=handle.handler)
    return handle.definition


async def bootstrap_meta_dogfood(
    *,
    scheduler: ManagedScheduler,
    executor: DAGExecutor,
    memory_manager: MemoryManager,
    defaults: DogfoodDefaults | None = None,
) -> DogfoodJobs:
    """Register the three default meta jobs (audit, knowledge refresh, dreaming) on the scheduler.

    Idempotent only at the JobStore level: re-registering an existing job replaces
    its definition. Caller is responsible for ``scheduler.start()`` after this call.
    """
    cfg = defaults or DogfoodDefaults()
    audit = await register_self_audit_job(
        scheduler,
        executor=executor,
        interval=cfg.self_audit_interval,
        nightshift=cfg.nightshift_window,
    )
    knowledge = await register_knowledge_refresh_job(
        scheduler,
        executor=executor,
        interval=cfg.knowledge_refresh_interval,
        nightshift=cfg.nightshift_window,
    )
    dreaming = await register_dreaming_job(
        scheduler,
        memory_manager=memory_manager,
        interval=cfg.dreaming_interval,
        min_sessions=cfg.dreaming_min_sessions,
        use_lock_gate=cfg.dreaming_use_lock_gate,
        nightshift=cfg.nightshift_window,
    )
    return DogfoodJobs(self_audit=audit, knowledge_refresh=knowledge, dreaming=dreaming)


__all__ = [
    "SELF_AUDIT_JOB_ID",
    "KNOWLEDGE_REFRESH_JOB_ID",
    "DREAMING_JOB_ID",
    "DogfoodJobs",
    "DogfoodDefaults",
    "register_self_audit_job",
    "register_knowledge_refresh_job",
    "register_dreaming_job",
    "bootstrap_meta_dogfood",
]
