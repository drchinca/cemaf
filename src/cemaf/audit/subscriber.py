"""EventBus-backed audit log — converts events into typed AuditEntry records."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from cemaf.audit.models import AuditEntry, AuditEntryType
from cemaf.events.protocols import Event, EventBus, EventType

_EVENT_TO_AUDIT: dict[EventType, AuditEntryType] = {
    EventType.AGENT_COMPLETED: AuditEntryType.AGENT_COMPLETED,
    # DAG nodes emit TASK_* events with node_id/run_id payloads; map them so
    # the audit trail captures per-step execution, not just DAG-level events.
    EventType.TASK_COMPLETED: AuditEntryType.NODE_EXECUTED,
    EventType.TASK_FAILED: AuditEntryType.NODE_EXECUTED,
    EventType.CONTEXT_PATCH_APPLIED: AuditEntryType.CONTEXT_PATCHED,
    EventType.EVAL_COMPLETED: AuditEntryType.EVAL_RESULT,
    EventType.QUALITY_ALERT: AuditEntryType.QUALITY_ALERT,
    EventType.DAG_COMPLETED: AuditEntryType.DAG_COMPLETED,
    EventType.MEMORY_EXTRACTED: AuditEntryType.MEMORY_EXTRACTED,
    EventType.TOOL_CALL_COMPLETED: AuditEntryType.NODE_EXECUTED,
}


class EventBusAuditLog:
    """Converts EventBus events into typed AuditEntry records."""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []
        self._unsubscribers: list[Callable[[], None]] = []

    def subscribe(self, *, event_bus: EventBus) -> None:
        """Wire up subscriptions to convert events to audit entries."""
        for event_type, audit_type in _EVENT_TO_AUDIT.items():
            handler = self._make_handler(audit_type=audit_type)
            unsub = event_bus.subscribe(
                event_type=event_type,
                handler=handler,
            )
            self._unsubscribers.append(unsub)

    def unsubscribe(self) -> None:
        """Remove all subscriptions."""
        for unsub in self._unsubscribers:
            unsub()
        self._unsubscribers.clear()

    async def append(self, entry: AuditEntry) -> None:
        """Manually append an audit entry."""
        self._entries.append(entry)

    async def query(
        self,
        *,
        run_id: str | None = None,
        entry_type: AuditEntryType | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> tuple[AuditEntry, ...]:
        """Filter entries by criteria."""
        results: list[AuditEntry] = []
        for entry in self._entries:
            if run_id is not None and entry.run_id != run_id:
                continue
            if entry_type is not None and entry.type != entry_type:
                continue
            if since is not None and entry.timestamp < since:
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return tuple(results)

    async def count(self, *, run_id: str | None = None) -> int:
        """Count entries, optionally filtered by run_id."""
        if run_id is None:
            return len(self._entries)
        return sum(1 for e in self._entries if e.run_id == run_id)

    def _make_handler(self, *, audit_type: AuditEntryType) -> Callable[[Event], None]:
        """Create a sync handler that converts an Event to an AuditEntry."""

        def _handler(event: Event) -> None:
            entry = AuditEntry.create(
                type=audit_type,
                run_id=event.payload.get("run_id", event.correlation_id or "unknown"),
                source=event.source or "system",
                payload=dict(event.payload),
                correlation_id=event.correlation_id,
                metadata=dict(event.metadata),
            )
            self._entries.append(entry)

        return _handler
