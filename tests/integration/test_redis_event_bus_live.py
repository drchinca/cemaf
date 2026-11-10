"""RedisEventBus against a real Redis.

Run with a Redis reachable at CEMAF_TEST_REDIS_URL (CI provides one):
    CEMAF_TEST_REDIS_URL=redis://localhost:6379/15 \
        uv run pytest -q tests/integration/test_redis_event_bus_live.py

Before this file RedisEventBus had no test of any kind. The URL should point at a
database index reserved for tests: every test flushes it.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Callable

import pytest

from cemaf.events.protocols import Event
from cemaf.events.redis_event_bus import RedisEventBus

_URL = os.getenv("CEMAF_TEST_REDIS_URL")

pytestmark = pytest.mark.skipif(_URL is None, reason="set CEMAF_TEST_REDIS_URL to run against Redis")

DELIVERY_TIMEOUT_S = 5.0
FAST_REDELIVERY_MS = 200


@pytest.fixture
async def bus() -> AsyncIterator[RedisEventBus]:
    """A bus on a flushed test database, closed afterwards."""
    assert _URL is not None
    event_bus = RedisEventBus(redis_url=_URL, redelivery_idle_ms=FAST_REDELIVERY_MS)
    await event_bus._redis.flushdb()
    try:
        yield event_bus
    finally:
        await event_bus.close()


def _event(*, event_type: str, n: int) -> Event:
    return Event.create(type=event_type, payload={"n": n}, source="test")


async def _wait_until(*, condition: Callable[[], bool]) -> None:
    """Poll until condition() holds or the delivery timeout passes."""
    deadline = asyncio.get_running_loop().time() + DELIVERY_TIMEOUT_S
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            return
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_a_published_event_reaches_its_subscriber(bus: RedisEventBus) -> None:
    """Basic delivery: publish after subscribing, the handler sees the payload."""
    event_type = f"test.{uuid.uuid4().hex[:8]}"
    seen: list[int] = []

    async def handler(event: Event) -> None:
        seen.append(event.payload["n"])

    bus.subscribe(event_type=event_type, handler=handler, subscriber_name="recorder")
    await asyncio.sleep(0.3)
    await bus.publish(_event(event_type=event_type, n=1))

    await _wait_until(condition=lambda: seen == [1])
    assert seen == [1]


@pytest.mark.asyncio
async def test_every_subscriber_of_a_type_receives_every_event(bus: RedisEventBus) -> None:
    """Fan-out, as the class promises: two subscribers to one type each see both events."""
    event_type = f"test.{uuid.uuid4().hex[:8]}"
    audit: list[int] = []
    metrics: list[int] = []

    async def to_audit(event: Event) -> None:
        audit.append(event.payload["n"])

    async def to_metrics(event: Event) -> None:
        metrics.append(event.payload["n"])

    bus.subscribe(event_type=event_type, handler=to_audit, subscriber_name="audit")
    bus.subscribe(event_type=event_type, handler=to_metrics, subscriber_name="metrics")
    await asyncio.sleep(0.3)
    await bus.publish(_event(event_type=event_type, n=1))
    await bus.publish(_event(event_type=event_type, n=2))

    await _wait_until(condition=lambda: sorted(audit) == [1, 2] and sorted(metrics) == [1, 2])
    assert sorted(audit) == [1, 2]
    assert sorted(metrics) == [1, 2]


@pytest.mark.asyncio
async def test_an_event_published_before_subscribing_is_still_delivered(bus: RedisEventBus) -> None:
    """Durability: a subscriber that starts late still gets events already in its stream."""
    event_type = f"test.{uuid.uuid4().hex[:8]}"
    seen: list[int] = []

    async def handler(event: Event) -> None:
        seen.append(event.payload["n"])

    await bus.publish(_event(event_type=event_type, n=7))
    bus.subscribe(event_type=event_type, handler=handler, subscriber_name="recorder")

    await _wait_until(condition=lambda: seen == [7])
    assert seen == [7]


@pytest.mark.asyncio
async def test_a_message_whose_handler_keeps_failing_ends_in_the_dead_letter_stream(
    bus: RedisEventBus,
) -> None:
    """After the maximum deliveries the message moves to the DLQ instead of staying pending forever."""
    event_type = f"test.{uuid.uuid4().hex[:8]}"
    attempts: list[int] = []

    async def always_fails(event: Event) -> None:
        attempts.append(event.payload["n"])
        raise RuntimeError("downstream is down")

    bus.subscribe(event_type=event_type, handler=always_fails, subscriber_name="flaky")
    await asyncio.sleep(0.3)
    await bus.publish(_event(event_type=event_type, n=3))

    async def dlq_length() -> int:
        return int(await bus._redis.xlen("cemaf:events:dlq"))

    deadline = asyncio.get_running_loop().time() + 15.0
    while await dlq_length() == 0 and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.2)

    assert len(attempts) >= 3
    assert await dlq_length() == 1


@pytest.mark.asyncio
async def test_replicas_of_one_subscriber_split_the_events(bus: RedisEventBus) -> None:
    """Two processes subscribing under the same name share a group: each event is handled exactly once."""
    assert _URL is not None
    event_type = f"test.{uuid.uuid4().hex[:8]}"
    handled: list[tuple[str, int]] = []
    replica = RedisEventBus(redis_url=_URL, worker_id="replica-2")

    def worker(name: str) -> Callable[[Event], object]:
        async def handle(event: Event) -> None:
            handled.append((name, event.payload["n"]))

        return handle

    try:
        bus.subscribe(event_type=event_type, handler=worker("replica-1"), subscriber_name="indexer")
        replica.subscribe(event_type=event_type, handler=worker("replica-2"), subscriber_name="indexer")
        await asyncio.sleep(0.3)
        for n in range(20):
            await bus.publish(_event(event_type=event_type, n=n))

        await _wait_until(condition=lambda: len(handled) >= 20)
        await asyncio.sleep(0.5)
    finally:
        await replica.close()

    assert sorted(n for _, n in handled) == list(range(20))


@pytest.mark.asyncio
async def test_a_lambda_needs_an_explicit_subscriber_name(bus: RedisEventBus) -> None:
    """Every lambda shares one qualname, so an automatic name would merge unrelated subscribers."""
    with pytest.raises(ValueError, match="subscriber_name"):
        bus.subscribe(event_type="test.lambda", handler=lambda event: None)


@pytest.mark.asyncio
async def test_two_handlers_cannot_share_one_subscriber_name(bus: RedisEventBus) -> None:
    """Reusing a subscriber name for a different handler would silently split its events."""

    async def first(event: Event) -> None:
        return None

    async def second(event: Event) -> None:
        return None

    bus.subscribe(event_type="test.dup", handler=first, subscriber_name="indexer")
    with pytest.raises(ValueError, match="indexer"):
        bus.subscribe(event_type="test.dup", handler=second, subscriber_name="indexer")


class AuditWriter:
    """A module-level handler object: its class name is a stable automatic subscriber name."""

    def __init__(self) -> None:
        self.seen: list[int] = []

    async def handle(self, event: Event) -> None:
        self.seen.append(event.payload["n"])


@pytest.mark.asyncio
async def test_a_named_handler_class_subscribes_without_an_explicit_name(bus: RedisEventBus) -> None:
    """Handlers with a stable module-qualified name get their group automatically."""
    event_type = f"test.{uuid.uuid4().hex[:8]}"
    writer = AuditWriter()

    bus.subscribe(event_type=event_type, handler=writer)
    bus.subscribe(event_type=event_type, handler=writer)
    await bus.publish(_event(event_type=event_type, n=5))

    await _wait_until(condition=lambda: writer.seen == [5, 5] or writer.seen == [5])
    await asyncio.sleep(0.3)
    assert writer.seen == [5]
