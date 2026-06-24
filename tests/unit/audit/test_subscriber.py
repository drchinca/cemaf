"""Unit tests for EventBusAuditLog — event-to-audit conversion."""

from __future__ import annotations

from datetime import timedelta

import pytest

from cemaf.audit.models import AuditEntry, AuditEntryType
from cemaf.audit.protocols import AuditLog
from cemaf.audit.subscriber import EventBusAuditLog
from cemaf.core.utils import utc_now
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType


@pytest.fixture()
def event_bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture()
def audit_log(event_bus: InMemoryEventBus) -> EventBusAuditLog:
    log = EventBusAuditLog()
    log.subscribe(event_bus=event_bus)
    return log


class TestProtocolConformance:
    """EventBusAuditLog satisfies the AuditLog protocol."""

    def test_isinstance_audit_log(self) -> None:
        """EventBusAuditLog is a runtime-checkable AuditLog."""
        assert isinstance(EventBusAuditLog(), AuditLog)


class TestSubscribe:
    """Subscribing wires EventBus events to audit entries."""

    @pytest.mark.asyncio()
    async def test_agent_completed_creates_entry(
        self, event_bus: InMemoryEventBus, audit_log: EventBusAuditLog
    ) -> None:
        """Publishing AGENT_COMPLETED produces an AGENT_COMPLETED audit entry."""
        event = Event.create(
            type=EventType.AGENT_COMPLETED,
            payload={"run_id": "run_1", "agent_id": "agent_a"},
            source="agent_a",
            correlation_id="corr_1",
        )
        await event_bus.publish(event=event)

        entries = await audit_log.query()
        assert len(entries) == 1
        assert entries[0].type == AuditEntryType.AGENT_COMPLETED
        assert entries[0].run_id == "run_1"
        assert entries[0].source == "agent_a"

    @pytest.mark.asyncio()
    async def test_all_mapped_event_types(
        self, event_bus: InMemoryEventBus, audit_log: EventBusAuditLog
    ) -> None:
        """All mapped EventTypes produce corresponding AuditEntryTypes."""
        mappings: list[tuple[EventType, AuditEntryType]] = [
            (EventType.AGENT_COMPLETED, AuditEntryType.AGENT_COMPLETED),
            (EventType.TASK_COMPLETED, AuditEntryType.NODE_EXECUTED),
            (EventType.TASK_FAILED, AuditEntryType.NODE_EXECUTED),
            (EventType.CONTEXT_PATCH_APPLIED, AuditEntryType.CONTEXT_PATCHED),
            (EventType.EVAL_COMPLETED, AuditEntryType.EVAL_RESULT),
            (EventType.QUALITY_ALERT, AuditEntryType.QUALITY_ALERT),
            (EventType.DAG_COMPLETED, AuditEntryType.DAG_COMPLETED),
            (EventType.MEMORY_EXTRACTED, AuditEntryType.MEMORY_EXTRACTED),
            (EventType.TOOL_CALL_COMPLETED, AuditEntryType.NODE_EXECUTED),
        ]
        for event_type, _expected_audit_type in mappings:
            event = Event.create(
                type=event_type,
                payload={"run_id": "run_map"},
                source="test",
            )
            await event_bus.publish(event=event)

        entries = await audit_log.query(run_id="run_map", limit=100)
        actual_types = {e.type for e in entries}
        expected_types = {at for _, at in mappings}
        assert actual_types == expected_types

    @pytest.mark.asyncio()
    async def test_unmapped_event_ignored(
        self, event_bus: InMemoryEventBus, audit_log: EventBusAuditLog
    ) -> None:
        """Events without a mapping do not create audit entries."""
        event = Event.create(
            type=EventType.TASK_STARTED,
            payload={"run_id": "run_x"},
            source="system",
        )
        await event_bus.publish(event=event)

        count = await audit_log.count()
        assert count == 0

    @pytest.mark.asyncio()
    async def test_run_id_from_correlation_id_fallback(
        self, event_bus: InMemoryEventBus, audit_log: EventBusAuditLog
    ) -> None:
        """If payload has no run_id, correlation_id is used."""
        event = Event.create(
            type=EventType.EVAL_COMPLETED,
            payload={"score": 0.9},
            source="eval",
            correlation_id="corr_fallback",
        )
        await event_bus.publish(event=event)

        entries = await audit_log.query()
        assert entries[0].run_id == "corr_fallback"


class TestUnsubscribe:
    """Unsubscribing prevents further audit entries."""

    @pytest.mark.asyncio()
    async def test_no_entries_after_unsubscribe(
        self, event_bus: InMemoryEventBus, audit_log: EventBusAuditLog
    ) -> None:
        """After unsubscribe, publishing events creates no new entries."""
        event = Event.create(
            type=EventType.DAG_COMPLETED,
            payload={"run_id": "run_before"},
            source="dag",
        )
        await event_bus.publish(event=event)
        assert await audit_log.count() == 1

        audit_log.unsubscribe()

        event2 = Event.create(
            type=EventType.DAG_COMPLETED,
            payload={"run_id": "run_after"},
            source="dag",
        )
        await event_bus.publish(event=event2)
        assert await audit_log.count() == 1


class TestManualAppend:
    """Manual append bypasses EventBus."""

    @pytest.mark.asyncio()
    async def test_append_adds_entry(self, audit_log: EventBusAuditLog) -> None:
        """Manually appended entries appear in queries."""
        entry = AuditEntry.create(
            type=AuditEntryType.QUALITY_ALERT,
            run_id="run_manual",
            source="manual",
            payload={"reason": "test"},
        )
        await audit_log.append(entry=entry)

        entries = await audit_log.query(run_id="run_manual")
        assert len(entries) == 1
        assert entries[0].id == entry.id


class TestQuery:
    """Query filtering logic."""

    @pytest.mark.asyncio()
    async def test_filter_by_run_id(self, audit_log: EventBusAuditLog) -> None:
        """Query returns only entries matching run_id."""
        for run_id in ("run_a", "run_a", "run_b"):
            entry = AuditEntry.create(
                type=AuditEntryType.NODE_EXECUTED,
                run_id=run_id,
                source="test",
            )
            await audit_log.append(entry=entry)

        entries = await audit_log.query(run_id="run_a")
        assert len(entries) == 2
        assert all(e.run_id == "run_a" for e in entries)

    @pytest.mark.asyncio()
    async def test_filter_by_entry_type(self, audit_log: EventBusAuditLog) -> None:
        """Query returns only entries matching entry_type."""
        for t in (AuditEntryType.NODE_EXECUTED, AuditEntryType.EVAL_RESULT, AuditEntryType.NODE_EXECUTED):
            entry = AuditEntry.create(type=t, run_id="run_t", source="test")
            await audit_log.append(entry=entry)

        entries = await audit_log.query(entry_type=AuditEntryType.NODE_EXECUTED)
        assert len(entries) == 2

    @pytest.mark.asyncio()
    async def test_filter_by_since(self, audit_log: EventBusAuditLog) -> None:
        """Query returns only entries after the since timestamp."""
        now = utc_now()
        old_entry = AuditEntry(
            id="old_1",
            type=AuditEntryType.NODE_EXECUTED,
            timestamp=now - timedelta(hours=2),
            run_id="run_s",
            source="test",
        )
        new_entry = AuditEntry(
            id="new_1",
            type=AuditEntryType.NODE_EXECUTED,
            timestamp=now,
            run_id="run_s",
            source="test",
        )
        await audit_log.append(entry=old_entry)
        await audit_log.append(entry=new_entry)

        cutoff = now - timedelta(hours=1)
        entries = await audit_log.query(since=cutoff)
        assert len(entries) == 1
        assert entries[0].id == "new_1"

    @pytest.mark.asyncio()
    async def test_limit_respected(self, audit_log: EventBusAuditLog) -> None:
        """Query returns at most limit entries."""
        for _i in range(10):
            entry = AuditEntry.create(
                type=AuditEntryType.NODE_EXECUTED,
                run_id="run_lim",
                source="test",
            )
            await audit_log.append(entry=entry)

        entries = await audit_log.query(limit=3)
        assert len(entries) == 3


class TestCount:
    """Count returns correct totals."""

    @pytest.mark.asyncio()
    async def test_count_all(self, audit_log: EventBusAuditLog) -> None:
        """Count without filter returns total entries."""
        for _ in range(5):
            entry = AuditEntry.create(
                type=AuditEntryType.NODE_EXECUTED,
                run_id="run_c",
                source="test",
            )
            await audit_log.append(entry=entry)

        assert await audit_log.count() == 5

    @pytest.mark.asyncio()
    async def test_count_by_run_id(self, audit_log: EventBusAuditLog) -> None:
        """Count with run_id returns filtered count."""
        for run_id in ("run_x", "run_x", "run_y"):
            entry = AuditEntry.create(
                type=AuditEntryType.NODE_EXECUTED,
                run_id=run_id,
                source="test",
            )
            await audit_log.append(entry=entry)

        assert await audit_log.count(run_id="run_x") == 2
        assert await audit_log.count(run_id="run_y") == 1
        assert await audit_log.count(run_id="run_z") == 0
