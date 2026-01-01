"""
Event bus implementations.

Simple, focused pub/sub for CEMAF events.
"""

import asyncio
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from cemaf.events.protocols import Event, EventHandler, EventType

# Type alias for handler functions
Handler = Callable[[Event], Any]


class _BaseEventBus:
    """Common functionality for event buses."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._global: list[Handler] = []

    def subscribe(self, event_type: str | EventType, handler: EventHandler | Handler) -> Callable[[], None]:
        """Subscribe to events. Returns unsubscribe function."""
        key = event_type.value if isinstance(event_type, EventType) else event_type
        fn = handler.handle if hasattr(handler, "handle") else handler  # type: ignore
        self._handlers[key].append(fn)
        return lambda: self._handlers[key].remove(fn) if fn in self._handlers[key] else None

    def subscribe_all(self, handler: EventHandler | Handler) -> Callable[[], None]:
        """Subscribe to all events. Returns unsubscribe function."""
        fn = handler.handle if hasattr(handler, "handle") else handler  # type: ignore
        self._global.append(fn)
        return lambda: self._global.remove(fn) if fn in self._global else None

    def _get_handlers(self, event: Event) -> list[Handler]:
        """Get all handlers for an event."""
        return list(self._handlers.get(event.type, [])) + self._global


class InMemoryEventBus(_BaseEventBus):
    """
    Simple in-memory event bus.

    Executes handlers in order, awaiting async handlers.
    """

    async def publish(self, event: Event) -> None:
        """Publish event to all subscribers."""
        for handler in self._get_handlers(event):
            result = handler(event)
            if asyncio.iscoroutine(result):
                await result

    async def publish_batch(self, events: list[Event]) -> None:
        """Publish multiple events."""
        for event in events:
            await self.publish(event)


class AsyncEventBus(_BaseEventBus):
    """
    Async event bus with concurrent execution.

    Better performance for IO-bound handlers.
    """

    def __init__(
        self, max_concurrent: int = 10, on_error: Callable[[Exception, Event], None] | None = None
    ) -> None:
        super().__init__()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._on_error = on_error

    async def publish(self, event: Event) -> None:
        """Publish event, executing handlers concurrently."""
        handlers = self._get_handlers(event)
        if handlers:
            await asyncio.gather(*[self._execute(h, event) for h in handlers], return_exceptions=True)

    async def publish_batch(self, events: list[Event]) -> None:
        """Publish multiple events concurrently."""
        await asyncio.gather(*[self.publish(e) for e in events], return_exceptions=True)

    async def _execute(self, handler: Handler, event: Event) -> None:
        """Execute handler with concurrency control."""
        async with self._semaphore:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                if self._on_error:
                    self._on_error(e, event)
