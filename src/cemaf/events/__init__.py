"""
Events module.

Provides event-driven architecture with pub/sub pattern,
webhooks, and third-party notifiers.
"""

from cemaf.events.protocols import (
    Event,
    EventHandler,
    EventBus,
    Notifier,
    NotifyResult,
    EventType,
)
from cemaf.events.bus import (
    InMemoryEventBus,
    AsyncEventBus,
)
from cemaf.events.notifiers import (
    WebhookNotifier,
    CompositeNotifier,
    LoggingNotifier,
)
from cemaf.events.mock import MockEventBus, MockNotifier

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

