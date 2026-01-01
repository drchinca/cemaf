"""Tests for events module."""

from __future__ import annotations

import asyncio

import pytest

from cemaf.events.bus import AsyncEventBus, InMemoryEventBus
from cemaf.events.mock import MockEventBus, MockNotifier
from cemaf.events.notifiers import (
    CompositeNotifier,
    LoggingNotifier,
    WebhookNotifier,
)
from cemaf.events.protocols import (
    Event,
    EventType,
    NotifyResult,
)

# =============================================================================
# Event Tests
# =============================================================================


class TestEvent:
    """Tests for Event model."""

    def test_create_event(self) -> None:
        """Test creating an event."""
        event = Event(
            type="test.event",
            payload={"key": "value"},
            source="test",
        )
        assert event.type == "test.event"
        assert event.payload == {"key": "value"}
        assert event.source == "test"
        assert event.id  # Auto-generated

    def test_create_with_enum_type(self) -> None:
        """Test creating event with enum type."""
        event = Event.create(
            type=EventType.TASK_COMPLETED,
            payload={"task_id": "123"},
        )
        assert event.type == "task.completed"

    def test_create_factory(self) -> None:
        """Test Event.create factory method."""
        event = Event.create(
            type="custom.event",
            payload={"data": "value"},
            source="factory",
            correlation_id="corr-123",
        )
        assert event.type == "custom.event"
        assert event.source == "factory"
        assert event.correlation_id == "corr-123"

    def test_event_is_frozen(self) -> None:
        """Test event is immutable."""
        event = Event.create(type="test")
        with pytest.raises(Exception):
            event.type = "modified"  # type: ignore


# =============================================================================
# NotifyResult Tests
# =============================================================================


class TestNotifyResult:
    """Tests for NotifyResult model."""

    def test_ok_factory(self) -> None:
        """Test NotifyResult.ok factory."""
        result = NotifyResult.ok("All good")
        assert result.success is True
        assert result.message == "All good"

    def test_fail_factory(self) -> None:
        """Test NotifyResult.fail factory."""
        result = NotifyResult.fail("Error occurred", retry_after=60)
        assert result.success is False
        assert result.error == "Error occurred"
        assert result.retry_after == 60


# =============================================================================
# InMemoryEventBus Tests
# =============================================================================


class TestInMemoryEventBus:
    """Tests for InMemoryEventBus."""

    async def test_publish_and_subscribe(self) -> None:
        """Test basic pub/sub."""
        bus = InMemoryEventBus()
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe("test.event", handler)

        event = Event.create(type="test.event")
        await bus.publish(event)

        assert len(received) == 1
        assert received[0].type == "test.event"

    async def test_type_specific_subscription(self) -> None:
        """Test subscriptions are type-specific."""
        bus = InMemoryEventBus()
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe("type.a", handler)

        await bus.publish(Event.create(type="type.a"))
        await bus.publish(Event.create(type="type.b"))

        assert len(received) == 1

    async def test_subscribe_with_enum(self) -> None:
        """Test subscribing with EventType enum."""
        bus = InMemoryEventBus()
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe(EventType.TASK_COMPLETED, handler)

        await bus.publish(Event.create(type=EventType.TASK_COMPLETED))

        assert len(received) == 1

    async def test_unsubscribe(self) -> None:
        """Test unsubscribing from events."""
        bus = InMemoryEventBus()
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        unsubscribe = bus.subscribe("test", handler)

        await bus.publish(Event.create(type="test"))
        assert len(received) == 1

        unsubscribe()

        await bus.publish(Event.create(type="test"))
        assert len(received) == 1  # No new events

    async def test_subscribe_all(self) -> None:
        """Test global subscription."""
        bus = InMemoryEventBus()
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe_all(handler)

        await bus.publish(Event.create(type="type.a"))
        await bus.publish(Event.create(type="type.b"))

        assert len(received) == 2

    async def test_publish_batch(self) -> None:
        """Test publishing multiple events."""
        bus = InMemoryEventBus()
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe_all(handler)

        events = [
            Event.create(type="test"),
            Event.create(type="test"),
            Event.create(type="test"),
        ]
        await bus.publish_batch(events)

        assert len(received) == 3

    async def test_sync_handler(self) -> None:
        """Test with synchronous handler."""
        bus = InMemoryEventBus()
        received: list[Event] = []

        def sync_handler(event: Event) -> None:
            received.append(event)

        bus.subscribe("test", sync_handler)

        await bus.publish(Event.create(type="test"))
        assert len(received) == 1


# =============================================================================
# AsyncEventBus Tests
# =============================================================================


class TestAsyncEventBus:
    """Tests for AsyncEventBus."""

    async def test_concurrent_execution(self) -> None:
        """Test handlers run concurrently."""
        bus = AsyncEventBus(max_concurrent=10)
        results: list[float] = []

        async def slow_handler(event: Event) -> None:
            await asyncio.sleep(0.01)
            results.append(asyncio.get_event_loop().time())

        bus.subscribe("test", slow_handler)
        bus.subscribe("test", slow_handler)
        bus.subscribe("test", slow_handler)

        await bus.publish(Event.create(type="test"))

        assert len(results) == 3
        # All should complete around the same time (concurrent)

    async def test_error_isolation(self) -> None:
        """Test handler errors don't affect other handlers."""
        errors: list[Exception] = []
        bus = AsyncEventBus(on_error=lambda e, ev: errors.append(e))

        received: list[Event] = []

        async def failing_handler(event: Event) -> None:
            raise ValueError("Handler error")

        async def good_handler(event: Event) -> None:
            received.append(event)

        bus.subscribe("test", failing_handler)
        bus.subscribe("test", good_handler)

        await bus.publish(Event.create(type="test"))

        assert len(received) == 1  # Good handler still ran
        assert len(errors) == 1  # Error was captured


# =============================================================================
# WebhookNotifier Tests
# =============================================================================


class TestWebhookNotifier:
    """Tests for WebhookNotifier."""

    async def test_without_client(self) -> None:
        """Test without HTTP client configured."""
        notifier = WebhookNotifier(url="https://example.com/webhook")

        event = Event.create(type="test", payload={"key": "value"})
        result = await notifier.notify(event)

        # Should succeed but indicate no client
        assert result.success is True
        assert "no HTTP client" in result.message

    def test_name_property(self) -> None:
        """Test notifier name."""
        notifier = WebhookNotifier(
            url="https://example.com/webhook",
            name="custom_webhook",
        )
        assert notifier.name == "custom_webhook"


# =============================================================================
# LoggingNotifier Tests
# =============================================================================


class TestLoggingNotifier:
    """Tests for LoggingNotifier."""

    async def test_notify_success(self) -> None:
        """Test logging notification always succeeds."""
        notifier = LoggingNotifier()

        event = Event.create(type="test", payload={"key": "value"})
        result = await notifier.notify(event)

        assert result.success is True

    def test_name_property(self) -> None:
        """Test notifier name."""
        notifier = LoggingNotifier(name="custom_logger")
        assert notifier.name == "custom_logger"


# =============================================================================
# CompositeNotifier Tests
# =============================================================================


class TestCompositeNotifier:
    """Tests for CompositeNotifier."""

    async def test_notifies_all(self) -> None:
        """Test all notifiers are called."""
        mock1 = MockNotifier(name="mock1")
        mock2 = MockNotifier(name="mock2")

        composite = CompositeNotifier([mock1, mock2])

        event = Event.create(type="test")
        result = await composite.notify(event)

        assert result.success is True
        assert mock1.notification_count == 1
        assert mock2.notification_count == 1

    async def test_fail_fast(self) -> None:
        """Test fail-fast mode."""
        mock1 = MockNotifier(should_succeed=False, name="mock1")
        mock2 = MockNotifier(name="mock2")

        composite = CompositeNotifier([mock1, mock2], fail_fast=True)

        event = Event.create(type="test")
        result = await composite.notify(event)

        assert result.success is False
        assert mock2.notification_count == 0  # Not called

    async def test_collect_all(self) -> None:
        """Test collect-all mode (default)."""
        mock1 = MockNotifier(should_succeed=False, name="mock1")
        mock2 = MockNotifier(name="mock2")

        composite = CompositeNotifier([mock1, mock2], fail_fast=False)

        event = Event.create(type="test")
        result = await composite.notify(event)

        assert result.success is False  # Overall fails
        assert mock2.notification_count == 1  # But all were called


# =============================================================================
# MockEventBus Tests
# =============================================================================


class TestMockEventBus:
    """Tests for MockEventBus."""

    async def test_records_events(self) -> None:
        """Test mock records published events."""
        bus = MockEventBus()

        event = Event.create(type="test")
        await bus.publish(event)

        assert bus.event_count == 1
        assert bus.published_events[0].type == "test"

    async def test_get_events_by_type(self) -> None:
        """Test filtering events by type."""
        bus = MockEventBus()

        await bus.publish(Event.create(type="type.a"))
        await bus.publish(Event.create(type="type.b"))
        await bus.publish(Event.create(type="type.a"))

        events = bus.get_events_by_type("type.a")
        assert len(events) == 2

    async def test_assert_published(self) -> None:
        """Test assertion helper."""
        bus = MockEventBus()

        await bus.publish(Event.create(type="test"))
        await bus.publish(Event.create(type="test"))

        bus.assert_published("test", count=2)  # Should not raise

        with pytest.raises(AssertionError):
            bus.assert_published("test", count=5)

    async def test_reset(self) -> None:
        """Test reset clears events."""
        bus = MockEventBus()

        await bus.publish(Event.create(type="test"))
        bus.reset()

        assert bus.event_count == 0


# =============================================================================
# MockNotifier Tests
# =============================================================================


class TestMockNotifier:
    """Tests for MockNotifier."""

    async def test_records_notifications(self) -> None:
        """Test mock records notifications."""
        notifier = MockNotifier()

        event = Event.create(type="test")
        await notifier.notify(event)

        assert notifier.notification_count == 1
        assert notifier.notifications[0].type == "test"

    async def test_configurable_success(self) -> None:
        """Test success can be configured."""
        notifier = MockNotifier(should_succeed=False)

        result = await notifier.notify(Event.create(type="test"))
        assert result.success is False

        notifier.set_success(True)

        result = await notifier.notify(Event.create(type="test"))
        assert result.success is True

    async def test_reset(self) -> None:
        """Test reset clears notifications."""
        notifier = MockNotifier()

        await notifier.notify(Event.create(type="test"))
        notifier.reset()

        assert notifier.notification_count == 0
