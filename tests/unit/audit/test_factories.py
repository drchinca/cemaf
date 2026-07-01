"""Tests for registry-backed audit factories."""

from __future__ import annotations

from datetime import datetime

import pytest

from cemaf.audit.factories import (
    audit_log_registry,
    audit_trail_registry,
    create_audit_log,
    create_audit_system,
    create_audit_trail,
)
from cemaf.audit.models import AuditEntry, AuditEntryType
from cemaf.audit.protocols import AuditLog, AuditTrail
from cemaf.audit.subscriber import EventBusAuditLog
from cemaf.audit.trail import InMemoryAuditTrail
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType


class FakeAuditLog:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def append(self, entry: AuditEntry) -> None:
        self.entries.append(entry)

    async def query(
        self,
        *,
        run_id: str | None = None,
        entry_type: AuditEntryType | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> tuple[AuditEntry, ...]:
        return tuple(self.entries[:limit])

    async def count(self, *, run_id: str | None = None) -> int:
        return len(self.entries)


class FakeAuditTrail:
    async def get_run_timeline(self, run_id: str) -> tuple[AuditEntry, ...]:
        return ()

    async def get_quality_trend(self, *, window: int = 20) -> tuple[float, ...]:
        return (1.0,)

    async def get_anomalies(self, *, threshold: float = 2.0) -> tuple[AuditEntry, ...]:
        return ()


class TestAuditFactories:
    def test_create_audit_log_default(self) -> None:
        audit_log = create_audit_log()

        assert isinstance(audit_log, EventBusAuditLog)
        assert isinstance(audit_log, AuditLog)

    def test_create_audit_trail_default(self) -> None:
        audit_log = FakeAuditLog()

        trail = create_audit_trail(audit_log=audit_log)

        assert isinstance(trail, InMemoryAuditTrail)
        assert isinstance(trail, AuditTrail)

    @pytest.mark.asyncio()
    async def test_create_audit_system_preserves_event_bus_subscription(self) -> None:
        event_bus = InMemoryEventBus()
        audit_log, audit_trail = create_audit_system(event_bus=event_bus)

        await event_bus.publish(
            event=Event.create(
                type=EventType.AGENT_COMPLETED,
                payload={"run_id": "run-1"},
                source="agent",
            )
        )

        assert isinstance(audit_log, EventBusAuditLog)
        assert isinstance(audit_trail, InMemoryAuditTrail)
        assert await audit_log.count(run_id="run-1") == 1

    def test_unknown_audit_log_backend_mentions_registry(self) -> None:
        with pytest.raises(ValueError, match="audit_log_registry.register"):
            create_audit_log("s3")

    def test_unknown_audit_trail_backend_mentions_registry(self) -> None:
        with pytest.raises(ValueError, match="audit_trail_registry.register"):
            create_audit_trail("warehouse", audit_log=FakeAuditLog())

    def test_postgres_audit_log_requires_dsn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CEMAF_AUDIT_POSTGRES_DSN", raising=False)
        monkeypatch.delenv("CEMAF_POSTGRES_DSN", raising=False)

        with pytest.raises(ValueError, match="postgres audit log backend requires dsn"):
            create_audit_log("postgres")

    def test_supports_custom_audit_log_backend(self) -> None:
        created: dict[str, object] = {}

        def _factory(**kwargs):
            created["args"] = kwargs
            return FakeAuditLog()

        audit_log_registry.register(backend="custom-test-audit-log", factory=_factory)

        audit_log = create_audit_log("custom-test-audit-log", retention_days=7)

        assert isinstance(audit_log, AuditLog)
        assert created["args"]["retention_days"] == 7

    def test_supports_custom_audit_trail_backend(self) -> None:
        created: dict[str, object] = {}
        audit_log = FakeAuditLog()

        def _factory(**kwargs):
            created["args"] = kwargs
            return FakeAuditTrail()

        audit_trail_registry.register(backend="custom-test-audit-trail", factory=_factory)

        trail = create_audit_trail("custom-test-audit-trail", audit_log=audit_log, window=50)

        assert isinstance(trail, AuditTrail)
        assert created["args"]["audit_log"] is audit_log
        assert created["args"]["window"] == 50
