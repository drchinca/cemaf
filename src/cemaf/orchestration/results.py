"""Execution result value types — leaf module to avoid import cycles.

`NodeResult` / `ExecutionResult` previously lived in `executor.py`. They are leaf
value objects (depend only on core types), but `executor.py` imports heavy
machinery (services, interceptors, …), so importing them from there created
cycles for any module that needs only the types. They live here; `executor.py`
re-exports them for backward-compatible imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cemaf.context.context import Context
from cemaf.core.enums import RunStatus
from cemaf.core.types import JSON, NodeID, RunID
from cemaf.core.utils import utc_now


@dataclass(frozen=True)
class NodeResult:
    """Result of executing a single node."""

    node_id: NodeID
    success: bool
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    metadata: JSON = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    """Result of executing an entire DAG."""

    run_id: RunID
    dag_name: str
    status: RunStatus
    node_results: tuple[NodeResult, ...] = field(default_factory=tuple)
    final_context: Context = field(default_factory=Context)
    error: str | None = None
    started_at: datetime = field(default_factory=utc_now)
    health_check_metadata: JSON = field(default_factory=dict)
    completed_at: datetime | None = None
    metadata: JSON = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status == RunStatus.COMPLETED

    @property
    def duration_ms(self) -> float:
        if not self.completed_at:
            return 0.0
        delta = self.completed_at - self.started_at
        return delta.total_seconds() * 1000
