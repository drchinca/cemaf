"""
Redis Streams-backed durable EventBus.

Unlike Pub/Sub (fire-and-forget), Streams provide persistent, ordered,
consumer-group delivery that survives process restarts. Each subscriber
(named by its handler, or explicitly) gets its own consumer group, so every
subscriber receives every event; replicas of one subscriber share the group and
split the work.

Retry and dead-letter: a failed message is redelivered after
``redelivery_idle_ms``; after 3 deliveries it moves to the cemaf:events:dlq
stream (SPEC-24).
"""

import asyncio
import json
import logging
from collections.abc import Callable
from typing import cast
from uuid import uuid4

from cemaf.events.protocols import Event, EventHandler, EventHandlerFn, EventType

logger = logging.getLogger(__name__)

_SUBSCRIBE_ALL_STREAM = "cemaf:events:__all__"
_DLQ_STREAM = "cemaf:events:dlq"
_MAX_DELIVERY_ATTEMPTS = 3
# Long enough that a slow handler on another replica still holds its messages;
# shorter values make the bus re-run in-flight work and burn delivery attempts.
DEFAULT_REDELIVERY_IDLE_MS = 60_000
_RECLAIM_FROM_START = "0-0"
# Automatic names containing these are shared by unrelated handlers. Closures are
# allowed: two different closures resolving to one group on a bus raise in _claim_group.
_AMBIGUOUS_NAME_MARKERS = ("<lambda>", "functools.partial")
_READ_BATCH = 10
_READ_BLOCK_MS = 200


def _subscriber_name(handler: EventHandler | EventHandlerFn) -> str:
    """A name for a handler that is stable across restarts: its module-qualified name.

    Raises ValueError for lambdas and partials, whose names are shared by unrelated
    handlers; those must pass subscriber_name explicitly.
    """
    target = type(handler) if hasattr(handler, "handle") else handler
    module = getattr(target, "__module__", "") or ""
    qualname = getattr(target, "__qualname__", "") or type(target).__qualname__
    name = f"{module}.{qualname}"
    if any(marker in name for marker in _AMBIGUOUS_NAME_MARKERS):
        raise ValueError(f"cannot derive a unique subscriber name from {name!r}; pass subscriber_name=")
    return name


class RedisEventBus:
    """
    EventBus implemented with Redis Streams for durable, ordered delivery.

    Each subscriber has its own consumer group (``group-<type>-<subscriber name>``),
    so every subscriber receives every event; processes subscribing under the same
    name compete for that group's messages. The __all__ stream mirrors every
    published event for subscribe_all() consumers.
    """

    def __init__(
        self,
        redis_url: str,
        worker_id: str | None = None,
        max_stream_length: int = 100_000,
        redelivery_idle_ms: int = DEFAULT_REDELIVERY_IDLE_MS,
    ) -> None:
        try:
            import redis.asyncio as aioredis
        except ImportError as exc:
            raise ImportError("redis package required for RedisEventBus. Install with: uv add redis") from exc

        self._redis = aioredis.from_url(redis_url)
        self._worker_id = worker_id or f"worker-{uuid4().hex[:8]}"
        self._max_stream_length = max_stream_length
        self._redelivery_idle_ms = redelivery_idle_ms
        # background tasks spawned by subscribe / subscribe_all
        self._tasks: list[asyncio.Task[None]] = []
        # consumer group -> the handler registered for it on this bus
        self._handlers_by_group: dict[str, EventHandler | EventHandlerFn] = {}

    async def publish(self, event: Event) -> None:
        """Append event to its type-specific stream and to the __all__ mirror."""
        stream = f"cemaf:events:{event.type}"
        fields = self._event_to_fields(event)

        pipe = self._redis.pipeline()
        pipe.xadd(stream, fields, maxlen=self._max_stream_length, approximate=True)
        pipe.xadd(_SUBSCRIBE_ALL_STREAM, fields, maxlen=self._max_stream_length, approximate=True)
        await pipe.execute()

    async def publish_batch(self, events: list[Event]) -> None:
        """Publish multiple events in a single pipeline round-trip."""
        if not events:
            return
        pipe = self._redis.pipeline()
        for event in events:
            fields = self._event_to_fields(event)
            stream = f"cemaf:events:{event.type}"
            pipe.xadd(stream, fields, maxlen=self._max_stream_length, approximate=True)
            pipe.xadd(_SUBSCRIBE_ALL_STREAM, fields, maxlen=self._max_stream_length, approximate=True)
        await pipe.execute()

    def subscribe(
        self,
        event_type: str | EventType,
        handler: EventHandler | EventHandlerFn,
        *,
        subscriber_name: str | None = None,
    ) -> Callable[[], None]:
        """Subscribe to one event type through this subscriber's own consumer group."""
        type_str = event_type.value if isinstance(event_type, EventType) else event_type
        stream = f"cemaf:events:{type_str}"
        group = f"group-{type_str}-{subscriber_name or _subscriber_name(handler)}"
        self._claim_group(group=group, handler=handler)

        task = asyncio.get_running_loop().create_task(
            self._consume_loop(stream, group, handler),
            name=f"redis-event-bus-{group}",
        )
        self._tasks.append(task)

        def unsubscribe() -> None:
            task.cancel()
            if task in self._tasks:
                self._tasks.remove(task)

        return unsubscribe

    def subscribe_all(
        self,
        handler: EventHandler | EventHandlerFn,
        *,
        subscriber_name: str | None = None,
    ) -> Callable[[], None]:
        """Subscribe to all published events via the __all__ mirror stream."""
        group = f"group-all-{subscriber_name or _subscriber_name(handler)}"
        self._claim_group(group=group, handler=handler)
        task = asyncio.get_running_loop().create_task(
            self._consume_loop(_SUBSCRIBE_ALL_STREAM, group, handler),
            name=f"redis-event-bus-all-{group}",
        )
        self._tasks.append(task)

        def unsubscribe() -> None:
            task.cancel()
            if task in self._tasks:
                self._tasks.remove(task)

        return unsubscribe

    def _claim_group(self, *, group: str, handler: EventHandler | EventHandlerFn) -> None:
        """Reserve a consumer group for one handler on this bus; a second handler would split its events."""
        existing = self._handlers_by_group.get(group)
        # == not `is`: each access to a bound method builds a new, equal object.
        if existing is not None and existing != handler:
            raise ValueError(f"subscriber name already used by another handler for {group!r}")
        self._handlers_by_group[group] = handler

    async def _consume_loop(
        self,
        stream: str,
        group: str,
        handler: EventHandler | EventHandlerFn,
    ) -> None:
        """Read and dispatch messages from a consumer group until cancelled."""
        await self._ensure_group(stream, group)

        reclaim_cursor = _RECLAIM_FROM_START
        while True:
            try:
                # Retry first: claim messages a failed (or crashed) delivery left
                # pending for longer than redelivery_idle_ms. Each claim counts as
                # another delivery, which is what lets _maybe_dlq reach its limit.
                # The cursor walks the whole pending list across passes, so a long
                # backlog at the head cannot hide later pending messages.
                claimed = await self._redis.xautoclaim(
                    stream,
                    group,
                    self._worker_id,
                    min_idle_time=self._redelivery_idle_ms,
                    start_id=reclaim_cursor,
                    count=_READ_BATCH,
                )
                # Redis 7 replies [cursor, messages, deleted]; Redis 6.2 omits deleted.
                next_cursor, reclaimed = claimed[0], claimed[1]
                reclaim_cursor = next_cursor.decode() if isinstance(next_cursor, bytes) else str(next_cursor)
                for msg_id, fields in reclaimed:
                    await self._dispatch(stream, group, msg_id, fields, handler)

                # BLOCK so the loop yields to other coroutines regularly.
                raw = await self._redis.xreadgroup(
                    groupname=group,
                    consumername=self._worker_id,
                    streams={stream: ">"},
                    count=_READ_BATCH,
                    block=_READ_BLOCK_MS,
                )
                for _, messages in raw or ():
                    for msg_id, fields in messages:
                        await self._dispatch(stream, group, msg_id, fields, handler)

            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("RedisEventBus consume error on %s: %s", stream, exc)
                await asyncio.sleep(1)

    async def _dispatch(
        self,
        stream: str,
        group: str,
        msg_id: bytes,
        fields: dict[bytes, bytes],
        handler: EventHandler | EventHandlerFn,
    ) -> None:
        """Deserialise, call handler, ACK on success, DLQ after max failures."""
        try:
            event = self._fields_to_event(cast("dict[bytes | str, bytes | str]", fields))
        except Exception as exc:
            logger.error("Failed to deserialise event from stream %s: %s", stream, exc)
            await self._redis.xack(stream, group, msg_id)
            return

        try:
            if hasattr(handler, "handle"):
                await handler.handle(event)
            else:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            await self._redis.xack(stream, group, msg_id)
        except Exception as exc:
            logger.warning(
                "Handler failed for message %s on %s: %s",
                msg_id,
                stream,
                exc,
            )
            await self._maybe_dlq(stream, group, msg_id, fields)

    async def _maybe_dlq(
        self,
        stream: str,
        group: str,
        msg_id: bytes,
        fields: dict[bytes, bytes],
    ) -> None:
        """Move message to DLQ after exceeding max delivery attempts."""
        # XPENDING gives delivery count; use XCLAIM approach: if pending
        # delivery count ≥ threshold, move to DLQ and ACK to clear PEL.
        try:
            pending_info = await self._redis.xpending_range(stream, group, min=msg_id, max=msg_id, count=1)
        except Exception:
            pending_info = []

        delivery_count = 0
        if pending_info:
            entry = pending_info[0]
            delivery_count = entry.get("times_delivered", 0) if isinstance(entry, dict) else 0

        if delivery_count >= _MAX_DELIVERY_ATTEMPTS:
            dlq_fields = {b"original_stream": stream.encode(), **fields}
            await self._redis.xadd(_DLQ_STREAM, dlq_fields)
            await self._redis.xack(stream, group, msg_id)

    async def _ensure_group(self, stream: str, group: str) -> None:
        """Create consumer group if it does not exist yet."""
        try:
            await self._redis.xgroup_create(stream, group, id="0", mkstream=True)
        except Exception as exc:
            # BUSYGROUP means it already exists — that is fine.
            if "BUSYGROUP" not in str(exc):
                logger.warning("xgroup_create error: %s", exc)

    @staticmethod
    def _event_to_fields(event: Event) -> dict[str, str]:
        return {
            "id": event.id,
            "type": event.type,
            "payload": json.dumps(event.payload),
            "source": event.source,
            "correlation_id": event.correlation_id or "",
            "timestamp": event.timestamp.isoformat(),
            "metadata": json.dumps(event.metadata),
        }

    @staticmethod
    def _fields_to_event(fields: dict[bytes | str, bytes | str]) -> Event:
        def _s(v: bytes | str) -> str:
            return v.decode() if isinstance(v, bytes) else v

        def _key(k: bytes | str) -> str:
            return k.decode() if isinstance(k, bytes) else k

        d = {_key(k): _s(v) for k, v in fields.items()}
        return Event(
            id=d.get("id", ""),
            type=d.get("type", ""),
            payload=json.loads(d.get("payload", "{}")),
            source=d.get("source", ""),
            correlation_id=d.get("correlation_id") or None,
            metadata=json.loads(d.get("metadata", "{}")),
        )

    async def close(self) -> None:
        """Cancel background tasks and close the Redis connection."""
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await self._redis.aclose()
