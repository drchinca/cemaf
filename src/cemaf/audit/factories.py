"""Audit factories — composition root for the audit system."""

from __future__ import annotations

import os
from typing import Any

from cemaf.audit.protocols import AuditLog, AuditTrail
from cemaf.audit.subscriber import EventBusAuditLog
from cemaf.audit.trail import InMemoryAuditTrail
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.events.protocols import EventBus

audit_log_registry: ProviderRegistry[AuditLog] = ProviderRegistry(name="audit_log")
audit_trail_registry: ProviderRegistry[AuditTrail] = ProviderRegistry(name="audit_trail")


def _create_event_bus_audit_log(**kwargs: Any) -> AuditLog:
    audit_log = EventBusAuditLog()
    event_bus = kwargs.get("event_bus")
    subscribe = bool(kwargs.get("subscribe", True))
    if event_bus is not None and subscribe:
        audit_log.subscribe(event_bus=event_bus)
    return audit_log


def _create_postgres_audit_log(**kwargs: Any) -> AuditLog:
    dsn = kwargs.get("dsn") or os.getenv("CEMAF_AUDIT_POSTGRES_DSN") or os.getenv("CEMAF_POSTGRES_DSN")
    if not dsn:
        raise ValueError("postgres audit log backend requires dsn (or CEMAF_AUDIT_POSTGRES_DSN env).")
    from cemaf.audit.postgres_audit_log import PostgresAuditLog

    return PostgresAuditLog(
        dsn=str(dsn),
        signing_registry=kwargs.get("signing_registry"),
        schema=str(kwargs.get("schema", "cemaf")),
        pool_min=int(kwargs.get("pool_min", 2)),
        pool_max=int(kwargs.get("pool_max", 5)),
    )


def _create_in_memory_audit_trail(**kwargs: Any) -> AuditTrail:
    audit_log = kwargs.get("audit_log")
    if audit_log is None:
        raise ValueError("memory audit trail backend requires audit_log.")
    return InMemoryAuditTrail(audit_log=audit_log)


audit_log_registry.register(backend="event_bus", factory=_create_event_bus_audit_log)
audit_log_registry.register(backend="memory", factory=_create_event_bus_audit_log)
audit_log_registry.register(backend="postgres", factory=_create_postgres_audit_log)
audit_trail_registry.register(backend="memory", factory=_create_in_memory_audit_trail)


def create_audit_log(
    backend: str = "event_bus",
    *,
    event_bus: EventBus | None = None,
    subscribe: bool = True,
    **backend_options: Any,
) -> AuditLog:
    """Create an `AuditLog` through the registry."""
    return audit_log_registry.create(
        backend=backend,
        event_bus=event_bus,
        subscribe=subscribe,
        **backend_options,
    )


def create_audit_trail(
    backend: str = "memory",
    *,
    audit_log: AuditLog,
    **backend_options: Any,
) -> AuditTrail:
    """Create an `AuditTrail` through the registry."""
    return audit_trail_registry.create(
        backend=backend,
        audit_log=audit_log,
        **backend_options,
    )


def create_audit_system(
    *,
    event_bus: EventBus,
    log_backend: str = "event_bus",
    trail_backend: str = "memory",
    log_options: dict[str, Any] | None = None,
    trail_options: dict[str, Any] | None = None,
) -> tuple[AuditLog, AuditTrail]:
    """Create and wire an audit system from an EventBus."""
    audit_log = create_audit_log(
        backend=log_backend,
        event_bus=event_bus,
        **(log_options or {}),
    )
    trail = create_audit_trail(
        backend=trail_backend,
        audit_log=audit_log,
        **(trail_options or {}),
    )
    return audit_log, trail
