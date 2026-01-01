"""
Events module.

Provides event-driven architecture with pub/sub pattern,
webhooks, and third-party notifiers.
"""

from cemaf.events.bus import (
    AsyncEventBus,
    InMemoryEventBus,
)
from cemaf.events.mock import MockEventBus, MockNotifier
from cemaf.events.notifiers import (
    CompositeNotifier,
    LoggingNotifier,
    WebhookNotifier,
)
from cemaf.events.protocols import (
    Event,
    EventBus,
    EventHandler,
    EventType,
    Notifier,
    NotifyResult,
)

__all__ = [
    # Protocols
    "Event",
    "EventHandler",
    "EventBus",
    "Notifier",
    "NotifyResult",
    "EventType",
    # Bus implementations
    "InMemoryEventBus",
    "AsyncEventBus",
    # Notifiers
    "WebhookNotifier",
    "CompositeNotifier",
    "LoggingNotifier",
    # Mock
    "MockEventBus",
    "MockNotifier",
]
