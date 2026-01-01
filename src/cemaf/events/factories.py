"""
Factory functions for event bus components.

Provides convenient ways to create event buses with sensible defaults
while maintaining dependency injection principles.
"""

import os

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.events.bus import EventBus


def create_event_bus(
    max_queue_size: int = 10000,
    enable_async_handlers: bool = True,
) -> EventBus:
    """
    Factory for EventBus with sensible defaults.

    Args:
        max_queue_size: Maximum events in queue
        enable_async_handlers: Enable async event handlers

    Returns:
        Configured EventBus instance

    Example:
        # With defaults
        bus = create_event_bus()

        # Custom configuration
        bus = create_event_bus(max_queue_size=5000)
    """
    return EventBus(
        max_queue_size=max_queue_size,
        enable_async_handlers=enable_async_handlers,
    )


def create_event_bus_from_config(settings: Settings | None = None) -> EventBus:
    """
    Create EventBus from environment configuration.

    Reads from environment variables:
    - CEMAF_EVENTS_MAX_QUEUE_SIZE: Max queue size (default: 10000)
    - CEMAF_EVENTS_ENABLE_ASYNC_HANDLERS: Enable async handlers (default: True)

    Returns:
        Configured EventBus instance

    Example:
        # From environment
        bus = create_event_bus_from_config()
    """
    cfg = settings or load_settings_from_env_sync()  # noqa: F841

    max_queue_size = int(os.getenv("CEMAF_EVENTS_MAX_QUEUE_SIZE", "10000"))
    enable_async = os.getenv("CEMAF_EVENTS_ENABLE_ASYNC_HANDLERS", "true").lower() == "true"

    return create_event_bus(
        max_queue_size=max_queue_size,
        enable_async_handlers=enable_async,
    )
