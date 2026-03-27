"""Audit data models — entry types, entries, and reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from cemaf.core.types import JSON
from cemaf.core.utils import generate_id, utc_now


class AuditEntryType(str, Enum):
    """Categories of auditable events in the framework."""

    NODE_EXECUTED = "node.executed"
    AGENT_COMPLETED = "agent.completed"
    CONTEXT_PATCHED = "context.patched"
    EVAL_RESULT = "eval.result"
    QUALITY_ALERT = "quality.alert"
    DAG_COMPLETED = "dag.completed"
    MEMORY_EXTRACTED = "memory.extracted"


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """Immutable record of a single auditable event."""

    id: str
    type: AuditEntryType
    timestamp: datetime
    run_id: str
    source: str  # agent_id, tool_id, or "system"
    correlation_id: str | None = None
    payload: JSON = field(default_factory=dict)
    metadata: JSON = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        type: AuditEntryType,
        run_id: str,
        source: str,
        payload: JSON | None = None,
        correlation_id: str | None = None,
        metadata: JSON | None = None,
    ) -> AuditEntry:
        """Factory that auto-generates id and timestamp."""
        return cls(
            id=generate_id(prefix="audit"),
            type=type,
            timestamp=utc_now(),
            run_id=run_id,
            source=source,
            correlation_id=correlation_id,
            payload=payload or {},
            metadata=metadata or {},
        )


@dataclass(frozen=True, slots=True)
class AuditReport:
    """Summary report generated from audit entries."""

    run_id: str | None
    generated_at: datetime
    total_entries: int
    quality_scores: tuple[float, ...]
    quality_mean: float
    anomalies: tuple[AuditEntry, ...]
    coverage_gaps: tuple[str, ...]  # node_ids without eval
    metadata: JSON = field(default_factory=dict)
