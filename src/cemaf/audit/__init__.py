"""Audit module — immutable audit trail for framework operations."""

from cemaf.audit.factories import create_audit_system
from cemaf.audit.models import AuditEntry, AuditEntryType, AuditReport
from cemaf.audit.protocols import AuditLog, AuditTrail
from cemaf.audit.subscriber import EventBusAuditLog
from cemaf.audit.trail import InMemoryAuditTrail

__all__ = [
    # Models
    "AuditEntryType",
    "AuditEntry",
    "AuditReport",
    # Protocols
    "AuditLog",
    "AuditTrail",
    # Implementations
    "EventBusAuditLog",
    "InMemoryAuditTrail",
    # Factories
    "create_audit_system",
]
