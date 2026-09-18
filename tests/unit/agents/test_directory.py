"""Contract tests for InMemoryAgentDirectory (SPEC-18 §2.1, §10 L1 "2.1 Identity" row).

Covers: admission idempotency by spawn key; UUID uniqueness across repeated
spawns; retry vs. replacement identity; alias resolution; concurrent-admit
ordinal safety.
"""

from __future__ import annotations

import asyncio

import pytest

from cemaf.agents.directory import InMemoryAgentDirectory, InvalidInstanceTransitionError
from cemaf.core.enums import InstanceStatus
from cemaf.core.types import AgentID, AttemptID, NodeID, RunID, TaskID
from cemaf.persistence.idempotency import IdempotencyConflictError, InMemoryIdempotentEffectSink

AGENT_ID = AgentID("Researcher")
TASK_ID = TaskID("task-1")
RUN_ID = RunID("run-1")


def _directory() -> InMemoryAgentDirectory:
    return InMemoryAgentDirectory(effect_sink=InMemoryIdempotentEffectSink())


class TestAdmissionIdempotency:
    @pytest.mark.asyncio
    async def test_same_spawn_key_replays_same_instance(self) -> None:
        directory = _directory()
        first = await directory.admit(
            spawn_key="run:node-a", agent_id=AGENT_ID, task_id=TASK_ID, run_id=RUN_ID
        )
        second = await directory.admit(
            spawn_key="run:node-a", agent_id=AGENT_ID, task_id=TASK_ID, run_id=RUN_ID
        )

        assert first.instance_id == second.instance_id
        assert first.display_name == second.display_name

    @pytest.mark.asyncio
    async def test_same_spawn_key_different_payload_conflicts(self) -> None:
        directory = _directory()
        await directory.admit(spawn_key="run:node-a", agent_id=AGENT_ID, task_id=TASK_ID, run_id=RUN_ID)

        with pytest.raises(IdempotencyConflictError):
            await directory.admit(
                spawn_key="run:node-a", agent_id=AGENT_ID, task_id=TASK_ID, run_id=RunID("run-2")
            )

    @pytest.mark.asyncio
    async def test_different_spawn_keys_same_definition_are_distinguishable(self) -> None:
        directory = _directory()
        first = await directory.admit(
            spawn_key="run:node-a", agent_id=AGENT_ID, task_id=TASK_ID, run_id=RUN_ID
        )
        second = await directory.admit(
            spawn_key="run:node-b", agent_id=AGENT_ID, task_id=TASK_ID, run_id=RUN_ID
        )

        assert first.instance_id != second.instance_id
        assert {first.display_name, second.display_name} == {"Researcher-1", "Researcher-2"}

    @pytest.mark.asyncio
    async def test_concurrent_admits_produce_gap_free_unique_ordinals(self) -> None:
        directory = _directory()
        results = await asyncio.gather(
            *(
                directory.admit(spawn_key=f"run:node-{i}", agent_id=AGENT_ID, task_id=TASK_ID, run_id=RUN_ID)
                for i in range(20)
            )
        )

        instance_ids = {instance.instance_id for instance in results}
        ordinals = sorted(int(instance.display_name.rsplit("-", 1)[1]) for instance in results)
        assert len(instance_ids) == 20
        assert ordinals == list(range(1, 21))


class TestRetryVsReplacementIdentity:
    @pytest.mark.asyncio
    async def test_retry_keeps_instance_id_but_gets_new_attempt_id(self) -> None:
        directory = _directory()
        instance = await directory.admit(
            spawn_key="run:node-a", agent_id=AGENT_ID, task_id=TASK_ID, run_id=RUN_ID
        )
        retried = await directory.transition(
            instance.instance_id,
            task_id=TASK_ID,
            status=InstanceStatus.RUNNING,
            attempt_id=AttemptID("attempt-2"),
        )

        assert retried.instance_id == instance.instance_id
        assert retried.attempt_id == "attempt-2"
        assert retried.attempt_id != instance.attempt_id

    @pytest.mark.asyncio
    async def test_replacement_spawn_gets_new_instance_id_and_records_replaces_id(self) -> None:
        directory = _directory()
        original = await directory.admit(
            spawn_key="run:node-a", agent_id=AGENT_ID, task_id=TASK_ID, run_id=RUN_ID
        )
        replacement = await directory.admit(
            spawn_key="run:node-a-replacement",
            agent_id=AGENT_ID,
            task_id=TASK_ID,
            run_id=RUN_ID,
            replaces_id=original.instance_id,
        )

        assert replacement.instance_id != original.instance_id
        assert replacement.replaces_id == original.instance_id


class TestAliasResolution:
    @pytest.mark.asyncio
    async def test_get_resolves_either_uuid_or_alias(self) -> None:
        directory = _directory()
        instance = await directory.admit(
            spawn_key="run:node-a", agent_id=AGENT_ID, task_id=TASK_ID, run_id=RUN_ID
        )

        by_uuid = await directory.get(instance.instance_id, task_id=TASK_ID)
        by_alias = await directory.get(instance.display_name, task_id=TASK_ID)

        assert by_uuid is not None
        assert by_alias is not None
        assert by_uuid.instance_id == by_alias.instance_id == instance.instance_id

    @pytest.mark.asyncio
    async def test_get_scoped_to_task_returns_none_for_other_task(self) -> None:
        directory = _directory()
        instance = await directory.admit(
            spawn_key="run:node-a", agent_id=AGENT_ID, task_id=TASK_ID, run_id=RUN_ID
        )

        assert await directory.get(instance.display_name, task_id=TaskID("other-task")) is None


class TestListAndTransition:
    @pytest.mark.asyncio
    async def test_list_filters_by_status(self) -> None:
        directory = _directory()
        a = await directory.admit(spawn_key="run:node-a", agent_id=AGENT_ID, task_id=TASK_ID, run_id=RUN_ID)
        await directory.admit(spawn_key="run:node-b", agent_id=AGENT_ID, task_id=TASK_ID, run_id=RUN_ID)
        await directory.transition(a.instance_id, task_id=TASK_ID, status=InstanceStatus.RUNNING)

        running = await directory.list(task_id=TASK_ID, status=InstanceStatus.RUNNING)
        queued = await directory.list(task_id=TASK_ID, status=InstanceStatus.QUEUED)

        assert [instance.instance_id for instance in running] == [a.instance_id]
        assert len(queued) == 1

    @pytest.mark.asyncio
    async def test_invalid_transition_out_of_terminal_state_raises(self) -> None:
        directory = _directory()
        instance = await directory.admit(
            spawn_key="run:node-a", agent_id=AGENT_ID, task_id=TASK_ID, run_id=RUN_ID
        )
        await directory.transition(instance.instance_id, task_id=TASK_ID, status=InstanceStatus.RUNNING)
        await directory.transition(instance.instance_id, task_id=TASK_ID, status=InstanceStatus.COMPLETED)

        with pytest.raises(InvalidInstanceTransitionError):
            await directory.transition(instance.instance_id, task_id=TASK_ID, status=InstanceStatus.RUNNING)


class TestDispose:
    @pytest.mark.asyncio
    async def test_dispose_removes_only_the_disposed_runs_instances(self) -> None:
        directory = _directory()
        kept = await directory.admit(
            spawn_key="keep:node-a", agent_id=AGENT_ID, task_id=TASK_ID, run_id=RunID("run-keep")
        )
        disposed = await directory.admit(
            spawn_key="dispose:node-a", agent_id=AGENT_ID, task_id=TASK_ID, run_id=RunID("run-dispose")
        )

        await directory.dispose(run_id=RunID("run-dispose"))

        assert await directory.get(kept.instance_id, task_id=TASK_ID) is not None
        assert await directory.get(disposed.instance_id, task_id=TASK_ID) is None

    @pytest.mark.asyncio
    async def test_dispose_does_not_reset_ordinal_counter_for_the_task(self) -> None:
        directory = _directory()
        await directory.admit(spawn_key="run:node-a", agent_id=AGENT_ID, task_id=TASK_ID, run_id=RUN_ID)
        await directory.dispose(run_id=RUN_ID)

        next_instance = await directory.admit(
            spawn_key="run2:node-a", agent_id=AGENT_ID, task_id=TASK_ID, run_id=RunID("run-2")
        )
        assert next_instance.display_name == "Researcher-2"

    @pytest.mark.asyncio
    async def test_missing_node_id_defaults_to_none(self) -> None:
        directory = _directory()
        instance = await directory.admit(
            spawn_key="run:node-a",
            agent_id=AGENT_ID,
            task_id=TASK_ID,
            run_id=RUN_ID,
            node_id=NodeID("node-a"),
        )
        assert instance.node_id == "node-a"
