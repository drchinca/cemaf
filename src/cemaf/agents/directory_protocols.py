"""AgentDirectory protocol (SPEC-18 §2.1) — admits, resolves, lists, and terminates agent instances."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from cemaf.agents.identity import AgentInstance
from cemaf.core.enums import InstanceStatus
from cemaf.core.types import AgentID, AttemptID, NodeID, RunID, TaskID


@runtime_checkable
class AgentDirectory(Protocol):
    """Admits, resolves, lists, and transitions agent-instance identities.

    `admit`/`get`/`list`/`transition` are the agent/tool-facing contract
    (SPEC-18 §2.1). `dispose` is an executor-internal fifth method for
    run-scoped retention cleanup, called by the executor at run end — never
    part of the agent/tool-facing surface above.
    """

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
        """Idempotently admit a spawn keyed by `spawn_key`; replay returns the original instance."""
        ...

    async def get(self, ref: UUID | str, *, task_id: TaskID) -> AgentInstance | None:
        """Resolve either the instance UUID or its display-name alias, scoped to `task_id`."""
        ...

    async def list(
        self,
        *,
        task_id: TaskID,
        status: InstanceStatus | None = None,
    ) -> tuple[AgentInstance, ...]:
        """List instances for a task, optionally filtered by lifecycle status."""
        ...

    async def transition(
        self,
        instance_id: UUID,
        *,
        task_id: TaskID,
        status: InstanceStatus,
        attempt_id: AttemptID | None = None,
    ) -> AgentInstance:
        """Move an instance to `status`; a new `attempt_id` marks a retry, not a re-admission."""
        ...

    async def dispose(self, *, run_id: RunID) -> None:
        """Retention cleanup for every instance admitted under `run_id`. Executor-internal."""
        ...
