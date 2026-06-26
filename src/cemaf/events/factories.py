"""
Factory functions for event bus components.

Provides convenient ways to create event buses with sensible defaults
while maintaining dependency injection principles.
"""

import os
from typing import Any

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.events.bus import AsyncEventBus, InMemoryEventBus
from cemaf.events.notifiers import CompositeNotifier, LoggingNotifier, WebhookNotifier
from cemaf.events.protocols import EventBus, Notifier

event_bus_registry: ProviderRegistry[EventBus] = ProviderRegistry(name="event_bus")
notifier_registry: ProviderRegistry[Notifier] = ProviderRegistry(name="notifier")


def _create_async_event_bus(**kwargs: Any) -> EventBus:
    max_queue_size = int(kwargs.get("max_queue_size", 10000))
    return AsyncEventBus(max_concurrent=max_queue_size)


def _create_memory_event_bus(**kwargs: Any) -> EventBus:
    return InMemoryEventBus()


def _create_redis_event_bus(**kwargs: Any) -> EventBus:
    redis_url = kwargs.get("redis_url") or os.getenv("CEMAF_EVENTS_REDIS_URL")
    if not redis_url:
        raise ValueError("redis event bus backend requires redis_url (or CEMAF_EVENTS_REDIS_URL env).")

    from cemaf.events.redis_event_bus import RedisEventBus

    return RedisEventBus(
        redis_url=str(redis_url),
        worker_id=kwargs.get("worker_id") or os.getenv("CEMAF_EVENTS_WORKER_ID"),
        max_stream_length=int(kwargs.get("max_stream_length", 100_000)),
    )


event_bus_registry.register(backend="async", factory=_create_async_event_bus)
event_bus_registry.register(backend="memory", factory=_create_memory_event_bus)
event_bus_registry.register(backend="redis", factory=_create_redis_event_bus)


def _create_logging_notifier(**kwargs: Any) -> Notifier:
    return LoggingNotifier(
        logger_name=str(kwargs.get("logger_name", "cemaf.events")),
        level=int(kwargs.get("level", 20)),
        name=str(kwargs.get("name", "logging")),
    )


def _create_webhook_notifier(**kwargs: Any) -> Notifier:
    url = kwargs.get("url") or os.getenv("CEMAF_EVENTS_WEBHOOK_URL")
    if not url:
        raise ValueError("webhook notifier backend requires url (or CEMAF_EVENTS_WEBHOOK_URL env).")
    headers = kwargs.get("headers")
    if headers is not None and not isinstance(headers, dict):
        raise ValueError("webhook notifier headers must be a dict when provided.")
    return WebhookNotifier(
        url=str(url),
        headers=headers,
        timeout_seconds=float(kwargs.get("timeout_seconds", 30.0)),
        name=str(kwargs["name"]) if kwargs.get("name") else None,
        http_client=kwargs.get("http_client"),
    )


def _create_composite_notifier(**kwargs: Any) -> Notifier:
    notifiers = list(kwargs.get("notifiers") or ())
    notifier_specs = kwargs.get("notifier_specs") or kwargs.get("children") or ()
    notifiers.extend(create_notifiers(notifier_specs))
    return CompositeNotifier(
        notifiers=tuple(notifiers),
        fail_fast=bool(kwargs.get("fail_fast", False)),
        name=str(kwargs.get("name", "composite")),
    )


notifier_registry.register(backend="logging", factory=_create_logging_notifier)
notifier_registry.register(backend="webhook", factory=_create_webhook_notifier)
notifier_registry.register(backend="composite", factory=_create_composite_notifier)


def create_event_bus(
    backend: str = "async",
    max_queue_size: int = 10000,
    enable_async_handlers: bool = True,
    **backend_options: Any,
) -> EventBus:
    """
    Factory for EventBus with sensible defaults.

    Args:
        backend: Event bus backend (async, memory, redis, or registered custom backend)
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
    return event_bus_registry.create(
        backend=backend,
        max_queue_size=max_queue_size,
        enable_async_handlers=enable_async_handlers,
        **backend_options,
    )


def create_notifier(
    backend: str = "logging",
    **backend_options: Any,
) -> Notifier:
    """Create a `Notifier` through the registry."""
    return notifier_registry.create(backend=backend, **backend_options)


def create_notifiers(
    notifier_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> tuple[Notifier, ...]:
    """Create multiple notifiers from declarative specs."""
    created: list[Notifier] = []
    for spec in notifier_specs or ():
        spec_copy = dict(spec)
        backend = str(spec_copy.pop("backend", spec_copy.pop("type", "")))
        if not backend:
            raise ValueError("Notifier spec requires 'backend' or 'type'.")
        created.append(create_notifier(backend, **spec_copy))
    return tuple(created)


def create_event_bus_from_config(settings: Settings | None = None) -> EventBus:
    """
    Create EventBus from environment configuration.

    Reads from environment variables:
    - CEMAF_EVENTS_MAX_QUEUE_SIZE: Max queue size (default: 10000)
    - CEMAF_EVENTS_ENABLE_ASYNC_HANDLERS: Enable async handlers (default: True)
    - CEMAF_EVENTS_BACKEND: Event bus backend (default: async)

    Returns:
        Configured EventBus instance

    Example:
        # From environment
        bus = create_event_bus_from_config()
    """
    cfg = settings or load_settings_from_env_sync()

    backend = os.getenv("CEMAF_EVENTS_BACKEND", "async")
    max_queue_size = int(os.getenv("CEMAF_EVENTS_MAX_QUEUE_SIZE", str(cfg.events.max_queue_size)))
    enable_async = (
        os.getenv("CEMAF_EVENTS_ENABLE_ASYNC_HANDLERS", str(cfg.events.enable_async_handlers)).lower()
        == "true"
    )

    return create_event_bus(
        backend=backend,
        max_queue_size=max_queue_size,
        enable_async_handlers=enable_async,
        redis_url=os.getenv("CEMAF_EVENTS_REDIS_URL"),
        worker_id=os.getenv("CEMAF_EVENTS_WORKER_ID"),
        max_stream_length=int(os.getenv("CEMAF_EVENTS_REDIS_MAX_STREAM_LENGTH", "100000")),
    )
