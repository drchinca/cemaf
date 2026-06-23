"""Integration test for the dog-fooded meta-scheduler (SPEC-11).

Proves the dog-fooding promise: a CEMAF deployment, configured via
``bootstrap_meta_dogfood``, will run audit / knowledge-refresh / dreaming as
managed background jobs using only CEMAF primitives.
"""

from __future__ import annotations

import pytest

from cemaf.agents.registry import AgentRegistry
from cemaf.audit.factories import create_audit_system
from cemaf.core.enums import MemoryScope
from cemaf.events.bus import InMemoryEventBus
from cemaf.knowledge.factories import create_knowledge_graph
from cemaf.memory.factories import create_memory_manager
from cemaf.meta.bootstrap import MetaServices, create_meta_executor
from cemaf.meta.dogfood import (
    DREAMING_JOB_ID,
    KNOWLEDGE_REFRESH_JOB_ID,
    SELF_AUDIT_JOB_ID,
    DogfoodDefaults,
    bootstrap_meta_dogfood,
)
from cemaf.orchestration.services import RuntimeServices
from cemaf.scheduler.factories import create_managed_scheduler
from cemaf.scheduler.primitives import JobKind, JobRunStatus


@pytest.mark.asyncio
async def test_bootstrap_meta_dogfood_registers_three_default_jobs() -> None:
    memory_manager = create_memory_manager()
    agent_registry = AgentRegistry()
    event_bus = InMemoryEventBus()
    audit_log, audit_trail = create_audit_system(event_bus=event_bus)
    kg = create_knowledge_graph(memory_manager=memory_manager)

    services = RuntimeServices(event_bus=event_bus, memory_manager=memory_manager)
    executor = create_meta_executor(
        agent_registry=agent_registry,
        services=services,
        meta_services=MetaServices(
            audit_log=audit_log,
            audit_trail=audit_trail,
            knowledge_graph=kg,
        ),
    )

    scheduler = create_managed_scheduler(worker_id="dogfood_worker")
    jobs = await bootstrap_meta_dogfood(
        scheduler=scheduler,
        executor=executor,
        memory_manager=memory_manager,
        defaults=DogfoodDefaults(nightshift_window=None),
    )

    assert jobs.self_audit.id == SELF_AUDIT_JOB_ID
    assert jobs.knowledge_refresh.id == KNOWLEDGE_REFRESH_JOB_ID
    assert jobs.dreaming.id == DREAMING_JOB_ID
    assert jobs.self_audit.kind == JobKind.SYSTEM
    assert jobs.knowledge_refresh.kind == JobKind.SYSTEM
    assert jobs.dreaming.kind == JobKind.DREAM

    persisted = {job.id for job in await scheduler.list_jobs()}
    assert persisted == {SELF_AUDIT_JOB_ID, KNOWLEDGE_REFRESH_JOB_ID, DREAMING_JOB_ID}


@pytest.mark.asyncio
async def test_dogfood_self_audit_runs_under_scheduler() -> None:
    memory_manager = create_memory_manager()
    agent_registry = AgentRegistry()
    event_bus = InMemoryEventBus()
    audit_log, audit_trail = create_audit_system(event_bus=event_bus)
    kg = create_knowledge_graph(memory_manager=memory_manager)

    services = RuntimeServices(event_bus=event_bus, memory_manager=memory_manager)
    executor = create_meta_executor(
        agent_registry=agent_registry,
        services=services,
        meta_services=MetaServices(audit_log=audit_log, audit_trail=audit_trail, knowledge_graph=kg),
    )

    scheduler = create_managed_scheduler(worker_id="audit_worker")
    await bootstrap_meta_dogfood(
        scheduler=scheduler,
        executor=executor,
        memory_manager=memory_manager,
        defaults=DogfoodDefaults(nightshift_window=None),
    )

    result = await scheduler.run_now(SELF_AUDIT_JOB_ID)
    runs = await scheduler.list_runs(job_id=SELF_AUDIT_JOB_ID)

    assert result.status.value == "completed"
    assert len(runs) == 1
    assert runs[0].status == JobRunStatus.COMPLETED
    assert isinstance(runs[0].result, dict)


@pytest.mark.asyncio
async def test_dogfood_knowledge_refresh_runs_under_scheduler() -> None:
    memory_manager = create_memory_manager()
    agent_registry = AgentRegistry()
    event_bus = InMemoryEventBus()
    audit_log, audit_trail = create_audit_system(event_bus=event_bus)
    kg = create_knowledge_graph(memory_manager=memory_manager)

    services = RuntimeServices(event_bus=event_bus, memory_manager=memory_manager)
    executor = create_meta_executor(
        agent_registry=agent_registry,
        services=services,
        meta_services=MetaServices(audit_log=audit_log, audit_trail=audit_trail, knowledge_graph=kg),
    )

    scheduler = create_managed_scheduler(worker_id="kg_worker")
    await bootstrap_meta_dogfood(
        scheduler=scheduler,
        executor=executor,
        memory_manager=memory_manager,
        defaults=DogfoodDefaults(nightshift_window=None),
    )

    result = await scheduler.run_now(KNOWLEDGE_REFRESH_JOB_ID)
    runs = await scheduler.list_runs(job_id=KNOWLEDGE_REFRESH_JOB_ID)

    assert result.status.value == "completed"
    assert len(runs) == 1
    assert runs[0].status == JobRunStatus.COMPLETED


@pytest.mark.asyncio
async def test_dogfood_dreaming_runs_and_consolidates_memory() -> None:
    memory_manager = create_memory_manager()
    await memory_manager.remember(
        scope=MemoryScope.PROJECT,
        key="fact_one",
        value={"summary": "CEMAF self-hosts."},
    )
    await memory_manager.remember(
        scope=MemoryScope.PROJECT,
        key="fact_two",
        value={"summary": "Meta-agents run on their own scheduler."},
    )

    agent_registry = AgentRegistry()
    event_bus = InMemoryEventBus()
    audit_log, audit_trail = create_audit_system(event_bus=event_bus)
    kg = create_knowledge_graph(memory_manager=memory_manager)

    services = RuntimeServices(event_bus=event_bus, memory_manager=memory_manager)
    executor = create_meta_executor(
        agent_registry=agent_registry,
        services=services,
        meta_services=MetaServices(audit_log=audit_log, audit_trail=audit_trail, knowledge_graph=kg),
    )

    scheduler = create_managed_scheduler(worker_id="dream_worker")
    await bootstrap_meta_dogfood(
        scheduler=scheduler,
        executor=executor,
        memory_manager=memory_manager,
        defaults=DogfoodDefaults(
            nightshift_window=None,
            dreaming_min_sessions=None,
            dreaming_use_lock_gate=False,
        ),
    )

    result = await scheduler.run_now(DREAMING_JOB_ID)
    runs = await scheduler.list_runs(job_id=DREAMING_JOB_ID)

    assert result.status.value == "completed"
    assert len(runs) == 1
    assert runs[0].status == JobRunStatus.COMPLETED
    assert isinstance(runs[0].result, dict)
    assert runs[0].result.get("consolidated_count", 0) >= 1


@pytest.mark.asyncio
async def test_dogfood_singleton_lease_prevents_double_run() -> None:
    """Two scheduler instances sharing a JobStore — only one runs at a time."""
    from cemaf.scheduler.heartbeats import InMemoryHeartbeatStore
    from cemaf.scheduler.primitives import InMemoryJobStore

    shared_job_store = InMemoryJobStore()
    shared_heartbeat = InMemoryHeartbeatStore()

    memory_manager = create_memory_manager()
    agent_registry = AgentRegistry()
    event_bus = InMemoryEventBus()
    audit_log, audit_trail = create_audit_system(event_bus=event_bus)
    kg = create_knowledge_graph(memory_manager=memory_manager)

    services = RuntimeServices(event_bus=event_bus, memory_manager=memory_manager)
    executor = create_meta_executor(
        agent_registry=agent_registry,
        services=services,
        meta_services=MetaServices(audit_log=audit_log, audit_trail=audit_trail, knowledge_graph=kg),
    )

    scheduler_a = create_managed_scheduler(
        worker_id="worker_a",
        job_store=shared_job_store,
        heartbeat_store=shared_heartbeat,
    )
    scheduler_b = create_managed_scheduler(
        worker_id="worker_b",
        job_store=shared_job_store,
        heartbeat_store=shared_heartbeat,
    )

    await bootstrap_meta_dogfood(
        scheduler=scheduler_a,
        executor=executor,
        memory_manager=memory_manager,
        defaults=DogfoodDefaults(nightshift_window=None),
    )
    await bootstrap_meta_dogfood(
        scheduler=scheduler_b,
        executor=executor,
        memory_manager=memory_manager,
        defaults=DogfoodDefaults(nightshift_window=None),
    )

    acquired = await shared_job_store.acquire_lease(SELF_AUDIT_JOB_ID, "worker_a", ttl_seconds=60.0)
    assert acquired

    result_b = await scheduler_b.run_now(SELF_AUDIT_JOB_ID)

    assert result_b.status.value == "completed"

    runs = await shared_job_store.list_runs(job_id=SELF_AUDIT_JOB_ID)
    statuses = [r.status for r in runs]
    assert JobRunStatus.DEFERRED in statuses
    deferred = next(r for r in runs if r.status == JobRunStatus.DEFERRED)
    assert deferred.metadata.get("reason") == "lease_held"
