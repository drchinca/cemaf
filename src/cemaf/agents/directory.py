"""In-memory AgentDirectory implementation (SPEC-18 §2.1)."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from uuid import UUID, uuid4

from cemaf.agents.identity import AgentInstance, format_display_name
from cemaf.core.enums import InstanceStatus
from cemaf.core.types import JSON, AgentID, AttemptID, NodeID, RunID, TaskID
from cemaf.core.utils import generate_id, utc_now
from cemaf.persistence.idempotency import IdempotentEffectSink

_TERMINAL: frozenset[InstanceStatus] = frozenset(
    {InstanceStatus.COMPLETED, InstanceStatus.FAILED, InstanceStatus.CANCELLED}
)

_VALID_TRANSITIONS: dict[InstanceStatus, frozenset[InstanceStatus]] = {
    InstanceStatus.QUEUED: frozenset(
        {InstanceStatus.QUEUED, InstanceStatus.RUNNING, InstanceStatus.CANCELLED, InstanceStatus.FAILED}
    ),
    InstanceStatus.RUNNING: frozenset(
        {
            InstanceStatus.RUNNING,
            InstanceStatus.WAITING,
            InstanceStatus.COMPLETED,
            InstanceStatus.FAILED,
            InstanceStatus.CANCELLED,
        }
    ),
    InstanceStatus.WAITING: frozenset(
        {
            InstanceStatus.WAITING,
            InstanceStatus.RUNNING,
            InstanceStatus.COMPLETED,
            InstanceStatus.FAILED,
            InstanceStatus.CANCELLED,
        }
    ),
    InstanceStatus.COMPLETED: frozenset(),
    InstanceStatus.FAILED: frozenset(),
    InstanceStatus.CANCELLED: frozenset(),
}


class InvalidInstanceTransitionError(RuntimeError):
    """Raised when a transition moves an AgentInstance out of a terminal state, or skips states illegally."""


class InMemoryAgentDirectory:
    """Concurrency-safe, single-process AgentDirectory (SPEC-18 §2.1).

    Admission composes `IdempotentEffectSink` so a retried `admit()` with the
    same `spawn_key` replays the existing instance instead of minting a new
    one — this is what makes "retries retain identity" true without extra
    bookkeeping. Ordinal assignment for the human-readable `display_name`
    alias happens inside the same per-`(agent_id, task_id)` lock as the
    idempotency check, so concurrent parallel peers never race for the same
    ordinal.
    """

    def __init__(self, *, effect_sink: IdempotentEffectSink) -> None:
        self._effect_sink = effect_sink
        self._instances: dict[UUID, AgentInstance] = {}
        self._instance_by_spawn_key: dict[str, UUID] = {}
        self._spawn_key_by_instance: dict[UUID, str] = {}
        self._alias_index: dict[tuple[TaskID, str], UUID] = {}
        self._ordinals: dict[tuple[AgentID, TaskID], int] = defaultdict(int)
        self._locks: dict[tuple[AgentID, TaskID], asyncio.Lock] = defaultdict(asyncio.Lock)

    async def admit(
        self,
        *,
        spawn_key: str,
        agent_id: AgentID,
        task_id: TaskID,
        run_id: RunID,
        node_id: NodeID | None = None,
        council_member_slot: str | None = None,
        parent_instance_id: UUID | None = None,
        capabilities: frozenset[str] = frozenset(),
        replaces_id: UUID | None = None,
    ) -> AgentInstance:
        payload: JSON = {
            "agent_id": str(agent_id),
            "task_id": str(task_id),
            "run_id": str(run_id),
            "node_id": str(node_id) if node_id is not None else None,
            "council_member_slot": council_member_slot,
            "parent_instance_id": (str(parent_instance_id) if parent_instance_id is not None else None),
            "replaces_id": str(replaces_id) if replaces_id is not None else None,
        }
        lock = self._locks[(agent_id, task_id)]
        async with lock:
            receipt = await self._effect_sink.publish(key=spawn_key, payload=payload)
            if not receipt.created:
                existing_id = self._instance_by_spawn_key[spawn_key]
                return self._instances[existing_id]

            self._ordinals[(agent_id, task_id)] += 1
            ordinal = self._ordinals[(agent_id, task_id)]
            instance = AgentInstance(
                instance_id=uuid4(),
                agent_id=agent_id,
                display_name=format_display_name(agent_id, ordinal),
                capabilities=capabilities,
                task_id=task_id,
                run_id=run_id,
                status=InstanceStatus.QUEUED,
                created_at=utc_now(),
                attempt_id=AttemptID(generate_id("attempt")),
                node_id=node_id,
                council_member_slot=council_member_slot,
                parent_instance_id=parent_instance_id,
                replaces_id=replaces_id,
            )
            self._instances[instance.instance_id] = instance
            self._instance_by_spawn_key[spawn_key] = instance.instance_id
            self._spawn_key_by_instance[instance.instance_id] = spawn_key
            self._alias_index[(task_id, instance.display_name)] = instance.instance_id
            return instance

    async def get(self, ref: UUID | str, *, task_id: TaskID) -> AgentInstance | None:
        if isinstance(ref, UUID):
            instance = self._instances.get(ref)
            return instance if instance is not None and instance.task_id == task_id else None
        instance_id = self._alias_index.get((task_id, ref))
        if instance_id is None:
            return None
        return self._instances.get(instance_id)

    async def list(
        self,
        *,
        task_id: TaskID,
        status: InstanceStatus | None = None,
    ) -> tuple[AgentInstance, ...]:
        matches = (
            instance
            for instance in self._instances.values()
            if instance.task_id == task_id and (status is None or instance.status == status)
        )
        return tuple(sorted(matches, key=lambda instance: instance.created_at))

    async def transition(
        self,
        instance_id: UUID,
        *,
        task_id: TaskID,
        status: InstanceStatus,
        attempt_id: AttemptID | None = None,
    ) -> AgentInstance:
        current = self._instances.get(instance_id)
        if current is None or current.task_id != task_id:
            raise KeyError(f"no AgentInstance {instance_id} in task {task_id!r}")
        if status != current.status and status not in _VALID_TRANSITIONS[current.status]:
            raise InvalidInstanceTransitionError(f"{current.status} -> {status} is not a valid transition")

        terminal_at = utc_now() if status in _TERMINAL else current.terminal_at
        updated = AgentInstance(
            instance_id=current.instance_id,
            agent_id=current.agent_id,
            display_name=current.display_name,
            capabilities=current.capabilities,
            task_id=current.task_id,
            run_id=current.run_id,
            status=status,
            created_at=current.created_at,
            attempt_id=attempt_id or current.attempt_id,
            tenant_id=current.tenant_id,
            project_id=current.project_id,
            node_id=current.node_id,
            council_member_slot=current.council_member_slot,
            parent_instance_id=current.parent_instance_id,
            terminal_at=terminal_at,
            replaces_id=current.replaces_id,
        )
        self._instances[instance_id] = updated
        return updated

    async def dispose(self, *, run_id: RunID) -> None:
        stale = [
            instance_id for instance_id, instance in self._instances.items() if instance.run_id == run_id
        ]
        for instance_id in stale:
            instance = self._instances.pop(instance_id)
            spawn_key = self._spawn_key_by_instance.pop(instance_id, None)
            if spawn_key is not None:
                self._instance_by_spawn_key.pop(spawn_key, None)
            self._alias_index.pop((instance.task_id, instance.display_name), None)
