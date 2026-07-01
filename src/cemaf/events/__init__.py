"""
Events module.

Provides event-driven architecture with pub/sub pattern,
webhooks, and third-party notifiers.
"""

from cemaf.events.bus import (
    AsyncEventBus,
    InMemoryEventBus,
)
from cemaf.events.factories import (
    create_event_bus,
    create_event_bus_from_config,
    create_notifier,
    create_notifiers,
    event_bus_registry,
    notifier_registry,
)
from cemaf.events.memory_subscriber import (
    RECORDABLE_EVENTS,
    RUN_SCOPED_RECORDABLE_EVENTS,
    record_event_to_memory,
    record_event_to_session_memory,
    subscribe_memory_recording,
    subscribe_session_memory_recording,
)
from cemaf.events.mock import MockEventBus, MockNotifier
from cemaf.events.notifiers import (
    CompositeNotifier,
    HttpClient,
    HttpResponse,
    LoggingNotifier,
    WebhookNotifier,
)
from cemaf.events.protocols import (
    Event,
    EventBus,
    EventHandler,
    EventHandlerFn,
    EventType,
    Notifier,
    NotifyResult,
)

__all__ = [
    # Protocols
    "Event",
    "EventHandler",
    "EventHandlerFn",
    "EventBus",
    "Notifier",
    "NotifyResult",
    "EventType",
    # Bus implementations
    "InMemoryEventBus",
    "AsyncEventBus",
    "create_event_bus",
    "create_event_bus_from_config",
    "event_bus_registry",
    "create_notifier",
    "create_notifiers",
    "notifier_registry",
    # Notifiers
    "HttpClient",
    "HttpResponse",
    "WebhookNotifier",
    "CompositeNotifier",
    "LoggingNotifier",
    # Mock
    "MockEventBus",
    "MockNotifier",
    # Memory subscriber helpers
    "RECORDABLE_EVENTS",
    "RUN_SCOPED_RECORDABLE_EVENTS",
    "record_event_to_memory",
    "record_event_to_session_memory",
    "subscribe_memory_recording",
    "subscribe_session_memory_recording",
]
