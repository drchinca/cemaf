"""Agent instance identity (SPEC-18 §2.1) — spawn-level identity distinct from registry definitions.

`agent_id` on `AgentRegistry` is a definition key: every dispatch to the same
name resolves the same shared object. `AgentInstance` is the missing
per-spawn record — a real, collision-safe UUID that distinguishes "Researcher
spawned for node A" from "Researcher spawned for node B" without mutating the
shared agent object itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from cemaf.core.enums import InstanceStatus
from cemaf.core.types import JSON, AgentID, AttemptID, NodeID, ProjectID, RunID, TaskID, TenantID


def format_display_name(agent_id: AgentID, ordinal: int) -> str:
    """Format the per-instance-unique, human/agent-readable alias for a spawn."""
    return f"{agent_id}-{ordinal}"


@dataclass(frozen=True, slots=True)
class AgentInstance:
    """One admitted spawn of an agent definition.

    `instance_id`/`parent_instance_id`/`replaces_id` are real `uuid.UUID` —
    a deliberate departure from this codebase's usual string `NewType` ID
    idiom, since spawn identity is security-relevant (spoofing prevention,
    cross-run uniqueness) and warrants a stronger type. `display_name` is a
    directory-assigned alias, never caller-supplied — see
    `format_display_name`.
    """

    instance_id: UUID
    agent_id: AgentID
    display_name: str
    capabilities: frozenset[str]
    task_id: TaskID
    run_id: RunID
    status: InstanceStatus
    created_at: datetime
    attempt_id: AttemptID
    tenant_id: TenantID | None = None
    project_id: ProjectID | None = None
    node_id: NodeID | None = None
    council_member_slot: str | None = None
    parent_instance_id: UUID | None = None
    terminal_at: datetime | None = None
    replaces_id: UUID | None = None

    def to_dict(self) -> JSON:
        """Serialize to a JSON-compatible dict."""
        return {
            "instance_id": str(self.instance_id),
            "agent_id": str(self.agent_id),
            "display_name": self.display_name,
            "capabilities": sorted(self.capabilities),
            "task_id": str(self.task_id),
            "run_id": str(self.run_id),
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "attempt_id": str(self.attempt_id),
            "tenant_id": str(self.tenant_id) if self.tenant_id is not None else None,
            "project_id": str(self.project_id) if self.project_id is not None else None,
            "node_id": str(self.node_id) if self.node_id is not None else None,
            "council_member_slot": self.council_member_slot,
            "parent_instance_id": (
                str(self.parent_instance_id) if self.parent_instance_id is not None else None
            ),
            "terminal_at": self.terminal_at.isoformat() if self.terminal_at is not None else None,
            "replaces_id": str(self.replaces_id) if self.replaces_id is not None else None,
        }
