"""Tests for event bus factory composition roots."""

from cemaf.events import (
    AsyncEventBus,
    CompositeNotifier,
    Event,
    InMemoryEventBus,
    LoggingNotifier,
    Notifier,
    WebhookNotifier,
    create_event_bus,
    create_event_bus_from_config,
    create_notifier,
    create_notifiers,
    event_bus_registry,
    notifier_registry,
)


class CustomEventBus:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def publish(self, event: Event) -> None:
        self.events.append(event)

    async def publish_batch(self, events: list[Event]) -> None:
        self.events.extend(events)

    def subscribe(self, event_type, handler):  # noqa: ANN001, ANN201
        return lambda: None

    def subscribe_all(self, handler):  # noqa: ANN001, ANN201
        return lambda: None


def test_create_event_bus_defaults_to_async_bus() -> None:
    bus = create_event_bus()

    assert isinstance(bus, AsyncEventBus)


def test_create_event_bus_supports_memory_backend() -> None:
    bus = create_event_bus(backend="memory")

    assert isinstance(bus, InMemoryEventBus)


def test_create_event_bus_supports_custom_registered_backend() -> None:
    created: dict[str, object] = {}

    def _factory(**kwargs):
        created["args"] = kwargs
        return CustomEventBus()

    event_bus_registry.register(backend="custom-event-bus", factory=_factory)

    bus = create_event_bus(
        backend="custom-event-bus",
        max_queue_size=7,
        enable_async_handlers=False,
        region="local",
    )

    assert isinstance(bus, CustomEventBus)
    assert created["args"]["max_queue_size"] == 7
    assert created["args"]["enable_async_handlers"] is False
    assert created["args"]["region"] == "local"


def test_create_event_bus_from_config_supports_env_backend(monkeypatch) -> None:  # noqa: ANN001
    event_bus_registry.register(backend="env-event-bus", factory=lambda **_: CustomEventBus())
    monkeypatch.setenv("CEMAF_EVENTS_BACKEND", "env-event-bus")

    bus = create_event_bus_from_config()

    assert isinstance(bus, CustomEventBus)


def test_redis_backend_requires_url(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("CEMAF_EVENTS_REDIS_URL", raising=False)

    try:
        create_event_bus(backend="redis")
    except ValueError as exc:
        assert "redis event bus backend requires redis_url" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected redis backend to require a URL")


def test_create_logging_notifier() -> None:
    notifier = create_notifier("logging", name="audit-log")

    assert isinstance(notifier, LoggingNotifier)
    assert notifier.name == "audit-log"


def test_create_webhook_notifier() -> None:
    notifier = create_notifier("webhook", url="https://example.test/webhook", name="alerts")

    assert isinstance(notifier, WebhookNotifier)
    assert notifier.name == "alerts"


def test_webhook_notifier_requires_url(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("CEMAF_EVENTS_WEBHOOK_URL", raising=False)

    try:
        create_notifier("webhook")
    except ValueError as exc:
        assert "webhook notifier backend requires url" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected webhook notifier to require a URL")


def test_create_composite_notifier_from_direct_notifiers() -> None:
    notifier = create_notifier(
        "composite",
        notifiers=(create_notifier("logging", name="one"),),
        name="fanout",
    )

    assert isinstance(notifier, CompositeNotifier)
    assert notifier.name == "fanout"


def test_create_notifiers_from_specs() -> None:
    notifiers = create_notifiers(
        (
            {"backend": "logging", "name": "events"},
            {"type": "webhook", "url": "https://example.test/hook", "name": "hook"},
        )
    )

    assert len(notifiers) == 2
    assert isinstance(notifiers[0], LoggingNotifier)
    assert isinstance(notifiers[1], WebhookNotifier)


def test_composite_notifier_supports_nested_specs() -> None:
    notifier = create_notifier(
        "composite",
        notifier_specs=(
            {"backend": "logging", "name": "nested-log"},
            {"backend": "webhook", "url": "https://example.test/hook", "name": "nested-hook"},
        ),
    )

    assert isinstance(notifier, CompositeNotifier)


def test_notifier_spec_requires_backend() -> None:
    try:
        create_notifiers(({"name": "missing"},))
    except ValueError as exc:
        assert "Notifier spec requires" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected notifier spec to require a backend")


def test_unknown_notifier_backend_mentions_registry() -> None:
    try:
        create_notifier("slack")
    except ValueError as exc:
        assert "notifier_registry.register" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected unknown notifier backend to fail")


def test_create_notifier_supports_custom_registered_backend() -> None:
    created: dict[str, object] = {}

    class CustomNotifier:
        @property
        def name(self) -> str:
            return "custom"

        async def notify(self, event: Event):  # noqa: ANN201
            return None

    def _factory(**kwargs):
        created["args"] = kwargs
        return CustomNotifier()

    notifier_registry.register(backend="custom-notifier", factory=_factory)

    notifier = create_notifier("custom-notifier", channel="ops")

    assert isinstance(notifier, Notifier)
    assert created["args"]["channel"] == "ops"
