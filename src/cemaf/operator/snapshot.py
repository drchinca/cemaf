"""cemaf.session.v1 — a versioned, read-only operator snapshot of a run (SPEC-14).

A pure, deterministic projection of CEMAF's internal runtime objects (RunRecord,
ExecutionResult) into one public, JSON-serializable contract. Realizes P0 of the ECC
enhancement roadmap: a stable target every later operator surface (CLI, service, MCP,
benchmarks) projects from, so downstream code stops coupling to internal dataclasses.

Contract discipline: required top-level fields are validated; unknown *nested* metadata is
tolerated; a new *top-level* field requires a schema-version bump. Absent optional services
are represented as "absent", never errors. The adapters mutate nothing.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Any, Final, Literal

from pydantic import BaseModel, Field

from cemaf.core.enums import RunStatus
from cemaf.observability.health import HealthStatus
from cemaf.observability.run_logger import RunRecord
from cemaf.orchestration.results import ExecutionResult, NodeResult

# The operator layer sits ABOVE both observability and orchestration — importing
# RunRecord (observability) and ExecutionResult (orchestration) here is a correct
# top-down edge, not a cycle.

SCHEMA_VERSION: Final[Literal["cemaf.session.v1"]] = "cemaf.session.v1"

# Sentinels for signals not yet wired.
UNKNOWN = "unknown"
CLEAR = "clear"

# Defaults promoted to constants (used across both adapters).
DEFAULT_PROFILE = "standard"
DEFAULT_ADAPTER_ID = "cemaf-dag"
WORKER_KIND_NODE = "dag-node"
WORKER_KIND_RUN = "run"


class SnapshotRunState(StrEnum):
    """Operator-facing run/worker state (superset of RunStatus + AgentStatus)."""

    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STOPPED = "stopped"
    UNKNOWN = "unknown"


class SnapshotHealth(StrEnum):
    """Operator-facing health classification."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ServicePresence(StrEnum):
    """Whether an optional RuntimeServices dependency was wired for this run."""

    ENABLED = "enabled"
    ABSENT = "absent"


_RUN_STATUS_MAP: dict[RunStatus, SnapshotRunState] = {
    RunStatus.PENDING: SnapshotRunState.PENDING,
    RunStatus.RUNNING: SnapshotRunState.RUNNING,
    RunStatus.COMPLETED: SnapshotRunState.COMPLETED,
    RunStatus.FAILED: SnapshotRunState.FAILED,
    RunStatus.CANCELLED: SnapshotRunState.CANCELLED,
}

_HEALTH_MAP: dict[HealthStatus, SnapshotHealth] = {
    HealthStatus.HEALTHY: SnapshotHealth.HEALTHY,
    HealthStatus.DEGRADED: SnapshotHealth.DEGRADED,
    HealthStatus.UNHEALTHY: SnapshotHealth.FAILED,
}


def map_run_status(status: RunStatus) -> SnapshotRunState:
    """Map a core RunStatus to an operator SnapshotRunState (unknowns → UNKNOWN)."""
    return _RUN_STATUS_MAP.get(status, SnapshotRunState.UNKNOWN)


def map_health_status(status: HealthStatus) -> SnapshotHealth:
    """Map a core HealthStatus to an operator SnapshotHealth (unknowns → UNKNOWN)."""
    return _HEALTH_MAP.get(status, SnapshotHealth.UNKNOWN)


class WorkerIntent(BaseModel):
    """What a worker (DAG node) intends — for operator legibility."""

    model_config = {"frozen": True}

    objective: str = ""
    input_keys: tuple[str, ...] = ()
    output_keys: tuple[str, ...] = ()


class WorkerSnapshot(BaseModel):
    """One worker (DAG node) projection. Unknown nested keys live in metadata."""

    model_config = {"frozen": True}

    id: str
    kind: str = WORKER_KIND_NODE
    state: SnapshotRunState
    health: SnapshotHealth = SnapshotHealth.UNKNOWN
    intent: WorkerIntent = Field(default_factory=WorkerIntent)
    duration_ms: float = 0.0
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunSummary(BaseModel):
    """Top-level run identity + lifecycle."""

    model_config = {"frozen": True}

    id: str
    state: SnapshotRunState
    dag_name: str = ""
    started_at: str | None = None
    ended_at: str | None = None


class ContextPressure(BaseModel):
    """Context-budget pressure summary."""

    model_config = {"frozen": True}

    patch_count: int = 0
    input_tokens: int = 0
    total_tokens_budget: int | None = None
    pressure: str = UNKNOWN


class RiskSummary(BaseModel):
    """Per-dimension risk signals; CLEAR/UNKNOWN until a service wires them."""

    model_config = {"frozen": True}

    budget: str = UNKNOWN
    quality: str = UNKNOWN
    moderation: str = CLEAR
    collision: str = CLEAR
    governance: str = CLEAR


class RuntimeSummary(BaseModel):
    """Which runtime policy profile + which optional services were present."""

    model_config = {"frozen": True}

    profile: str = DEFAULT_PROFILE
    services: dict[str, ServicePresence] = Field(default_factory=dict)


class Aggregates(BaseModel):
    """Roll-ups across workers + run totals."""

    model_config = {"frozen": True}

    worker_count: int = 0
    states: dict[str, int] = Field(default_factory=dict)
    healths: dict[str, int] = Field(default_factory=dict)
    tool_calls: int = 0
    llm_calls: int = 0
    total_cost_usd: float = 0.0
    total_tokens: int = 0


class SessionSnapshot(BaseModel):
    """The cemaf.session.v1 contract — a public, read-only projection of a run."""

    model_config = {"frozen": True}

    schema_version: Literal["cemaf.session.v1"] = SCHEMA_VERSION
    adapter_id: str = DEFAULT_ADAPTER_ID
    run: RunSummary
    workers: tuple[WorkerSnapshot, ...] = ()
    runtime: RuntimeSummary = Field(default_factory=RuntimeSummary)
    context: ContextPressure = Field(default_factory=ContextPressure)
    risk: RiskSummary = Field(default_factory=RiskSummary)
    aggregates: Aggregates = Field(default_factory=Aggregates)

    def to_json(self) -> str:
        """Serialize to JSON with stable key order (deterministic)."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True)

    @classmethod
    def json_schema(cls) -> dict[str, Any]:
        """Export the JSON Schema for this contract."""
        return cls.model_json_schema()


# Known optional RuntimeServices fields an operator cares about (for presence reporting).
_KNOWN_SERVICES: tuple[str, ...] = (
    "run_logger",
    "event_bus",
    "budget_guard",
    "health_monitor",
    "quality_police",
    "moderation_pipeline",
    "collision_coordinator",
)


def _services_presence(present: tuple[str, ...]) -> dict[str, ServicePresence]:
    """Build the services presence map — every known service shown ENABLED or ABSENT."""
    present_set = set(present)
    return {
        name: (ServicePresence.ENABLED if name in present_set else ServicePresence.ABSENT)
        for name in _KNOWN_SERVICES
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _aggregate_states(workers: tuple[WorkerSnapshot, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for worker in workers:
        counts[worker.state.value] = counts.get(worker.state.value, 0) + 1
    return counts


def _aggregate_healths(workers: tuple[WorkerSnapshot, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for worker in workers:
        counts[worker.health.value] = counts.get(worker.health.value, 0) + 1
    return counts


def _worker_from_node_result(result: NodeResult) -> WorkerSnapshot:
    state = SnapshotRunState.COMPLETED if result.success else SnapshotRunState.FAILED
    health = SnapshotHealth.HEALTHY if result.success else SnapshotHealth.FAILED
    return WorkerSnapshot(
        id=str(result.node_id),
        state=state,
        health=health,
        duration_ms=result.duration_ms,
        error=result.error,
        metadata=dict(result.metadata),
    )


def snapshot_from_execution_result(
    result: ExecutionResult,
    *,
    services_present: tuple[str, ...] = (),
    profile: str = DEFAULT_PROFILE,
    adapter_id: str = DEFAULT_ADAPTER_ID,
    total_cost_usd: float = 0.0,
    total_tokens: int = 0,
    tool_calls: int = 0,
    llm_calls: int = 0,
) -> SessionSnapshot:
    """Project an ExecutionResult into a cemaf.session.v1 snapshot (read-only, deterministic).

    ExecutionResult carries no cost/token totals — pass them via the kwargs (default 0) when
    you have them, e.g. from the run's RunRecord or BudgetGuard.
    """
    workers = tuple(_worker_from_node_result(node) for node in result.node_results)
    run = RunSummary(
        id=str(result.run_id),
        state=map_run_status(result.status),
        dag_name=result.dag_name,
        started_at=_iso(result.started_at),
        ended_at=_iso(result.completed_at),
    )
    aggregates = Aggregates(
        worker_count=len(workers),
        states=_aggregate_states(workers),
        healths=_aggregate_healths(workers),
        tool_calls=tool_calls,
        llm_calls=llm_calls,
        total_cost_usd=total_cost_usd,
        total_tokens=total_tokens,
    )
    return SessionSnapshot(
        adapter_id=adapter_id,
        run=run,
        workers=workers,
        runtime=RuntimeSummary(profile=profile, services=_services_presence(services_present)),
        context=ContextPressure(pressure=UNKNOWN),
        risk=RiskSummary(),
        aggregates=aggregates,
    )


def snapshot_from_run_record(
    record: RunRecord,
    *,
    services_present: tuple[str, ...] = (),
    profile: str = DEFAULT_PROFILE,
    adapter_id: str = DEFAULT_ADAPTER_ID,
) -> SessionSnapshot:
    """Project a RunRecord into a cemaf.session.v1 snapshot (read-only, deterministic).

    A RunRecord has no per-node results, so it yields a single run-level worker summarizing
    the whole run. Use snapshot_from_execution_result for per-node workers.
    """
    state = SnapshotRunState.COMPLETED if record.success else SnapshotRunState.FAILED
    health = SnapshotHealth.HEALTHY if record.success else SnapshotHealth.FAILED
    worker = WorkerSnapshot(
        id=record.run_id,
        kind=WORKER_KIND_RUN,
        state=state,
        health=health,
        intent=WorkerIntent(objective=record.dag_name),
        duration_ms=record.duration_ms,
        error=record.error,
    )
    run = RunSummary(
        id=record.run_id,
        state=state,
        dag_name=record.dag_name,
        started_at=_iso(record.started_at),
        ended_at=_iso(record.completed_at),
    )
    aggregates = Aggregates(
        worker_count=1,
        states={state.value: 1},
        healths={health.value: 1},
        tool_calls=record.total_tool_calls,
        llm_calls=record.total_llm_calls,
        total_cost_usd=record.total_cost_usd,
        total_tokens=record.total_tokens,
    )
    return SessionSnapshot(
        adapter_id=adapter_id,
        run=run,
        workers=(worker,),
        runtime=RuntimeSummary(profile=profile, services=_services_presence(services_present)),
        context=ContextPressure(patch_count=record.total_patches, pressure=UNKNOWN),
        risk=RiskSummary(),
        aggregates=aggregates,
    )
