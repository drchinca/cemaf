"""
Mock implementations for testing events.
"""

from collections.abc import Callable
from typing import Any

from cemaf.events.protocols import Event, EventType, NotifyResult


class MockEventBus:
    """
    Mock event bus for testing.

    Records published events and allows inspection.
    """

    def __init__(self) -> None:
        """Initialize mock event bus."""
        self._published: list[Event] = []
        self._handlers: dict[str, list[Callable[[Event], Any]]] = {}
        self._global_handlers: list[Callable[[Event], Any]] = []

    @property
    def published_events(self) -> list[Event]:
        """Get all published events."""
        return list(self._published)

    @property
    def event_count(self) -> int:
        """Get number of published events."""
        return len(self._published)

    def get_events_by_type(self, event_type: str | EventType) -> list[Event]:
        """Get events of a specific type."""
        type_str = event_type.value if isinstance(event_type, EventType) else event_type
        return [e for e in self._published if e.type == type_str]

    async def publish(self, event: Event) -> None:
        """Record published event."""
        self._published.append(event)

        # Still call handlers for integration testing
        for handler in self._handlers.get(event.type, []):
            await self._call_handler(handler, event)

        for handler in self._global_handlers:
            await self._call_handler(handler, event)

    async def publish_batch(self, events: list[Event]) -> None:
        """Record multiple events."""
        for event in events:
            await self.publish(event)

    def subscribe(
        self,
        event_type: str | EventType,
        handler: Callable[[Event], Any],
    ) -> Callable[[], None]:
        """Subscribe to events."""
        type_str = event_type.value if isinstance(event_type, EventType) else event_type

        if type_str not in self._handlers:
            self._handlers[type_str] = []
        self._handlers[type_str].append(handler)

        def unsubscribe() -> None:
            if handler in self._handlers.get(type_str, []):
                self._handlers[type_str].remove(handler)

        return unsubscribe

    def subscribe_all(
        self,
        handler: Callable[[Event], Any],
    ) -> Callable[[], None]:
        """Subscribe to all events."""
        self._global_handlers.append(handler)

        def unsubscribe() -> None:
            if handler in self._global_handlers:
                self._global_handlers.remove(handler)

        return unsubscribe

    async def _call_handler(
        self,
        handler: Callable[[Event], Any],
        event: Event,
    ) -> None:
        """Call handler."""
        import asyncio

        result = handler(event)
        if asyncio.iscoroutine(result):
            await result

    def reset(self) -> None:
        """Reset recorded events."""
        self._published.clear()

    def assert_published(
        self,
        event_type: str | EventType,
        count: int | None = None,
    ) -> None:
        """
        Assert that events were published.

        Args:
            event_type: Expected event type.
            count: Expected count (None = at least one).

        Raises:
            AssertionError: If assertion fails.
        """
        events = self.get_events_by_type(event_type)
        type_str = event_type.value if isinstance(event_type, EventType) else event_type

        if count is not None:
            assert len(events) == count, f"Expected {count} events of type '{type_str}', got {len(events)}"
        else:
            assert len(events) > 0, f"Expected at least one event of type '{type_str}', got none"


class MockNotifier:
    """
    Mock notifier for testing.

    Records all notification attempts.
    """

    def __init__(
        self,
        should_succeed: bool = True,
        name: str = "mock_notifier",
    ) -> None:
        """
        Initialize mock notifier.

        Args:
            should_succeed: Whether notifications should succeed.
            name: Notifier name.
        """
        self._should_succeed = should_succeed
        self._name = name
        self._notifications: list[Event] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def notifications(self) -> list[Event]:
        """Get all notification attempts."""
        return list(self._notifications)

    @property
    def notification_count(self) -> int:
        """Get number of notifications."""
        return len(self._notifications)

    def set_success(self, should_succeed: bool) -> None:
        """Set whether notifications should succeed."""
        self._should_succeed = should_succeed

    async def notify(self, event: Event) -> NotifyResult:
        """Record notification attempt."""
        self._notifications.append(event)

        if self._should_succeed:
            return NotifyResult.ok("Mock notification sent")
        return NotifyResult.fail("Mock failure")

    def reset(self) -> None:
        """Reset recorded notifications."""
        self._notifications.clear()
