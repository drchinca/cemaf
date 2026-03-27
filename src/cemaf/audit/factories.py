"""Audit factories — composition root for the audit system."""

from __future__ import annotations

from cemaf.audit.subscriber import EventBusAuditLog
from cemaf.audit.trail import InMemoryAuditTrail
from cemaf.events.protocols import EventBus


def create_audit_system(
    *,
    event_bus: EventBus,
) -> tuple[EventBusAuditLog, InMemoryAuditTrail]:
    """Create and wire an audit system from an EventBus."""
    audit_log = EventBusAuditLog()
    audit_log.subscribe(event_bus=event_bus)
    trail = InMemoryAuditTrail(audit_log=audit_log)
    return audit_log, trail
