"""Operator plane — public, read-only contracts that project CEMAF runtime state.

Sits above both observability and orchestration. The first contract is the
``cemaf.session.v1`` snapshot (SPEC-14); later roadmap items (capability resolver,
runtime policy, improvement artifacts) land here too.
"""

from cemaf.operator.snapshot import (
    DEFAULT_ADAPTER_ID,
    DEFAULT_PROFILE,
    SCHEMA_VERSION,
    Aggregates,
    ContextPressure,
    RiskSummary,
    RunSummary,
    RuntimeSummary,
    ServicePresence,
    SessionSnapshot,
    SnapshotHealth,
    SnapshotRunState,
    WorkerIntent,
    WorkerSnapshot,
    map_health_status,
    map_run_status,
    snapshot_from_execution_result,
    snapshot_from_run_record,
)

__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_PROFILE",
    "DEFAULT_ADAPTER_ID",
    "SessionSnapshot",
    "SnapshotRunState",
    "SnapshotHealth",
    "ServicePresence",
    "WorkerSnapshot",
    "WorkerIntent",
    "RunSummary",
    "ContextPressure",
    "RiskSummary",
    "RuntimeSummary",
    "Aggregates",
    "map_run_status",
    "map_health_status",
    "snapshot_from_run_record",
    "snapshot_from_execution_result",
]
