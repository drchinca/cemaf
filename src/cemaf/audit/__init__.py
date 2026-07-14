"""Audit module — immutable audit trail for framework operations."""

from typing import Any

from cemaf.audit.factories import (
    audit_log_registry,
    audit_trail_registry,
    create_audit_log,
    create_audit_system,
    create_audit_trail,
)
from cemaf.audit.models import Actor, ActorKind, AuditEntry, AuditEntryType, AuditReport
from cemaf.audit.protocols import AuditLog, AuditTrail
from cemaf.audit.subscriber import EventBusAuditLog
from cemaf.audit.trail import InMemoryAuditTrail


def __getattr__(name: str) -> Any:
    if name == "build_trace_analysis":
        from cemaf.audit.analysis import build_trace_analysis

        return build_trace_analysis
    if name == "build_trace_analysis_sync":
        from cemaf.audit.analysis import build_trace_analysis_sync

        return build_trace_analysis_sync
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Models
    "Actor",
    "ActorKind",
    "AuditEntryType",
    "AuditEntry",
    "AuditReport",
    # Protocols
    "AuditLog",
    "AuditTrail",
    # Implementations
    "EventBusAuditLog",
    "InMemoryAuditTrail",
    # Analysis helpers
    "build_trace_analysis",
    "build_trace_analysis_sync",
    # Factories
    "audit_log_registry",
    "audit_trail_registry",
    "create_audit_log",
    "create_audit_system",
    "create_audit_trail",
]
