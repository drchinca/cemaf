"""Holistic proof test for the SPEC-18 phase-1a identity substrate (§2.1, §3
invariants 1-2/4-6/9-13) under concurrent, multi-agent, multi-task,
multi-run load — real components only, composed through the public
factories (`create_agent_directory`, `create_runtime_services`), no mocks.

`tests/unit/agents/test_directory.py` proves each contract in isolation.
This test proves they all hold *simultaneously*, under real `asyncio`
concurrency, across several agent definitions and tasks at once:
admission idempotency survives concurrent duplicate registration, ordinals
stay gap-free and globally unique per `(agent_id, task_id)` even under lock
contention, retries and deliberate replacements stay distinguishable,
display-name aliases never leak across tasks even when the same alias
string is independently minted in each one, the full lifecycle state
machine holds under concurrent transitions, and `dispose()` cleans up
exactly the run it was asked to — nothing more, nothing less.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest

from cemaf.agents.directory import InvalidInstanceTransitionError
from cemaf.agents.factories import create_agent_directory
from cemaf.core.enums import InstanceStatus
from cemaf.core.types import AgentID, AttemptID, NodeID, RunID, TaskID
from cemaf.orchestration.factories import create_runtime_services

AGENT_DEFINITIONS = tuple(AgentID(name) for name in ("Librarian", "Researcher", "Summarizer", "Writer"))
TASK_IDS = tuple(TaskID(f"task-{i}") for i in range(3))
SPAWNS_PER_AGENT_PER_TASK = 5
DUPLICATE_ADMIT_ATTEMPTS = (
    3  # races the same spawn_key against itself, like pre-dispatch + dispatch-time admission would
)


@pytest.mark.asyncio
async def test_identity_substrate_holds_under_concurrent_multi_task_load() -> None:
    services = create_runtime_services(agent_directory=create_agent_directory())
    directory = services.agent_directory
    assert directory is not None
    run_id = RunID("run-primary")

    # Phase 1 — every base spawn admitted with DUPLICATE_ADMIT_ATTEMPTS racing
    # copies, across every (agent, task, ordinal) combination at once. Proves
    # idempotent collapse under real lock contention, not sequential replay.
    async def admit_base(agent_id: AgentID, task_id: TaskID, ordinal: int) -> tuple[str, set[UUID]]:
        spawn_key = f"{run_id}:{agent_id}:{task_id}:{ordinal}"
        node_id = NodeID(f"node-{agent_id}-{ordinal}")
        results = await asyncio.gather(
            *(
                directory.admit(
                    spawn_key=spawn_key, agent_id=agent_id, task_id=task_id, run_id=run_id, node_id=node_id
                )
                for _ in range(DUPLICATE_ADMIT_ATTEMPTS)
            )
        )
        return spawn_key, {instance.instance_id for instance in results}

    base_admissions = await asyncio.gather(
        *(
            admit_base(agent_id, task_id, ordinal)
            for agent_id in AGENT_DEFINITIONS
            for task_id in TASK_IDS
            for ordinal in range(SPAWNS_PER_AGENT_PER_TASK)
        )
    )

    base_instances_by_key: dict[str, UUID] = {}
    for spawn_key, instance_ids in base_admissions:
        assert len(instance_ids) == 1, (
            f"{spawn_key} produced {len(instance_ids)} distinct instances under concurrent duplicate admits"
        )
        base_instances_by_key[spawn_key] = instance_ids.pop()

    expected_base_count = len(AGENT_DEFINITIONS) * len(TASK_IDS) * SPAWNS_PER_AGENT_PER_TASK
    assert len(base_instances_by_key) == expected_base_count
    assert (
        len(set(base_instances_by_key.values())) == expected_base_count
    )  # globally unique across every agent/task
    assert all(isinstance(instance_id, UUID) for instance_id in base_instances_by_key.values())

    # Phase 2 — one deliberate replacement per (agent, task), racing
    # concurrently across every pair. Ordinal must continue past the 5 base
    # spawns with no reset and no collision.
    async def admit_replacement(agent_id: AgentID, task_id: TaskID) -> tuple[str, UUID, UUID, str]:
        original_key = f"{run_id}:{agent_id}:{task_id}:0"
        original_id = base_instances_by_key[original_key]
        replacement_key = f"{original_key}:replacement"
        replacement = await directory.admit(
            spawn_key=replacement_key,
            agent_id=agent_id,
            task_id=task_id,
            run_id=run_id,
            replaces_id=original_id,
        )
        return replacement_key, original_id, replacement.instance_id, replacement.display_name

    replacements = await asyncio.gather(
        *(admit_replacement(agent_id, task_id) for agent_id in AGENT_DEFINITIONS for task_id in TASK_IDS)
    )
    replacement_instances_by_key: dict[str, UUID] = {}
    for agent_id, (replacement_key, original_id, replacement_id, display_name) in zip(
        (a for a in AGENT_DEFINITIONS for _ in TASK_IDS), replacements, strict=True
    ):
        assert replacement_id != original_id
        assert display_name == f"{agent_id}-{SPAWNS_PER_AGENT_PER_TASK + 1}"
        replacement_instances_by_key[replacement_key] = replacement_id

    # Phase 3 — drive every base AND replacement instance through a full,
    # varied lifecycle concurrently: RUNNING -> {COMPLETED, FAILED, CANCELLED,
    # WAITING->COMPLETED}.
    outcomes = (
        InstanceStatus.COMPLETED,
        InstanceStatus.FAILED,
        InstanceStatus.CANCELLED,
        InstanceStatus.WAITING,
    )

    async def run_lifecycle(index: int, instance_id: UUID, task_id: TaskID) -> InstanceStatus:
        await directory.transition(
            instance_id,
            task_id=task_id,
            status=InstanceStatus.RUNNING,
            attempt_id=AttemptID(f"attempt-{index}"),
        )
        outcome = outcomes[index % len(outcomes)]
        if outcome is InstanceStatus.WAITING:
            await directory.transition(instance_id, task_id=task_id, status=InstanceStatus.WAITING)
            await directory.transition(instance_id, task_id=task_id, status=InstanceStatus.RUNNING)
            outcome = InstanceStatus.COMPLETED
        await directory.transition(instance_id, task_id=task_id, status=outcome)
        return outcome

    def task_id_of(spawn_key: str) -> TaskID:
        return TaskID(spawn_key.split(":")[2])

    keyed_instances = list(base_instances_by_key.items()) + list(replacement_instances_by_key.items())
    final_outcomes = await asyncio.gather(
        *(
            run_lifecycle(i, instance_id, task_id_of(spawn_key))
            for i, (spawn_key, instance_id) in enumerate(keyed_instances)
        )
    )

    # Phase 4 — per-task, per-status listing is exactly correct, and terminal
    # instances carry terminal_at while non-terminal ones never do.
    for task_id in TASK_IDS:
        for status in InstanceStatus:
            listed = await directory.list(task_id=task_id, status=status)
            expected_ids = {
                instance_id
                for (spawn_key, instance_id), outcome in zip(keyed_instances, final_outcomes, strict=True)
                if task_id_of(spawn_key) == task_id and outcome == status
            }
            assert {instance.instance_id for instance in listed} == expected_ids

    for (spawn_key, instance_id), outcome in zip(keyed_instances, final_outcomes, strict=True):
        instance = await directory.get(instance_id, task_id=task_id_of(spawn_key))
        assert instance is not None
        assert (instance.terminal_at is not None) == (
            outcome in (InstanceStatus.COMPLETED, InstanceStatus.FAILED, InstanceStatus.CANCELLED)
        )

    # Phase 5 — alias resolution never leaks across tasks, even though every
    # task independently mints the identical alias string ("Librarian-1", ...).
    for agent_id in AGENT_DEFINITIONS:
        alias = f"{agent_id}-1"
        resolved = [await directory.get(alias, task_id=task_id) for task_id in TASK_IDS]
        assert all(instance is not None for instance in resolved)
        assert len({instance.instance_id for instance in resolved if instance is not None}) == len(TASK_IDS)

    # Phase 6 — a terminal instance rejects a further transition.
    completed_spawn_key, completed_instance_id = next(
        (spawn_key, instance_id)
        for (spawn_key, instance_id), outcome in zip(keyed_instances, final_outcomes, strict=True)
        if outcome == InstanceStatus.COMPLETED
    )
    with pytest.raises(InvalidInstanceTransitionError):
        await directory.transition(
            completed_instance_id, task_id=task_id_of(completed_spawn_key), status=InstanceStatus.RUNNING
        )

    # Phase 7 — dispose() is run-scoped, not task-scoped: a second run in the
    # same task is unaffected, keeps the task's ordinal sequence unbroken, and
    # survives disposing the first run.
    second_run_id = RunID("run-secondary")
    probe_task, probe_agent = TASK_IDS[0], AGENT_DEFINITIONS[0]
    second_run_instance = await directory.admit(
        spawn_key=f"{second_run_id}:{probe_agent}:{probe_task}:probe",
        agent_id=probe_agent,
        task_id=probe_task,
        run_id=second_run_id,
    )
    assert second_run_instance.display_name == f"{probe_agent}-{SPAWNS_PER_AGENT_PER_TASK + 2}"

    await directory.dispose(run_id=run_id)

    for spawn_key, instance_id in keyed_instances:  # covers both base and replacement instances
        assert await directory.get(instance_id, task_id=task_id_of(spawn_key)) is None
    assert await directory.get(second_run_instance.instance_id, task_id=probe_task) is not None
    assert services.agent_directory is directory  # the composed bundle held one directory throughout

    # Phase 8 — composition-time validation still rejects a non-conforming
    # object after all of the above, proving the public factory path is the
    # one under test, not just the concrete class in isolation.
    with pytest.raises(ValueError, match="AgentDirectory protocol"):
        create_runtime_services(agent_directory=object())  # type: ignore[arg-type]
