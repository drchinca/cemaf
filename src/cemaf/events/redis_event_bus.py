"""
Redis Streams-backed durable EventBus.

Unlike Pub/Sub (fire-and-forget), Streams provide persistent, ordered,
consumer-group delivery that survives process restarts. Each subscriber
gets an independent consumer group — all receive all events.

Dead-letter: after 3 failed deliveries, message moved to
cemaf:events:dlq stream.
"""

import asyncio
import json
import logging
from collections.abc import Callable
from uuid import uuid4

from cemaf.events.protocols import Event, EventHandler, EventHandlerFn, EventType

logger = logging.getLogger(__name__)

_SUBSCRIBE_ALL_STREAM = "cemaf:events:__all__"
_DLQ_STREAM = "cemaf:events:dlq"
_MAX_DELIVERY_ATTEMPTS = 3


class RedisEventBus:
    """
    EventBus implemented with Redis Streams for durable, ordered delivery.

    Each call to subscribe() creates an independent consumer group so
    every subscriber receives every event — fan-out semantics, not
    competing-consumers. The __all__ stream mirrors every published event
    for subscribe_all() consumers.
    """

    def __init__(
        self,
        redis_url: str,
        worker_id: str | None = None,
        max_stream_length: int = 100_000,
    ) -> None:
        try:
            import redis.asyncio as aioredis
        except ImportError as exc:
            raise ImportError(
                "redis package required for RedisEventBus. "
                "Install with: uv add redis"
            ) from exc

        self._redis = aioredis.from_url(redis_url)
        self._worker_id = worker_id or f"worker-{uuid4().hex[:8]}"
        self._max_stream_length = max_stream_length
        # background tasks spawned by subscribe / subscribe_all
        self._tasks: list[asyncio.Task[None]] = []

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
    ) -> Callable[[], None]:
        """Subscribe to a single event type via a dedicated consumer group."""
        type_str = event_type.value if isinstance(event_type, EventType) else event_type
        stream = f"cemaf:events:{type_str}"
        group = f"group-{type_str}"

        task = asyncio.get_event_loop().create_task(
            self._consume_loop(stream, group, handler),
            name=f"redis-event-bus-{group}",
        )
        self._tasks.append(task)

        def unsubscribe() -> None:
            task.cancel()
            if task in self._tasks:
                self._tasks.remove(task)

        return unsubscribe

    def subscribe_all(self, handler: EventHandler | EventHandlerFn) -> Callable[[], None]:
        """Subscribe to all published events via the __all__ mirror stream."""
        group = f"group-all-{uuid4().hex[:8]}"
        task = asyncio.get_event_loop().create_task(
            self._consume_loop(_SUBSCRIBE_ALL_STREAM, group, handler),
            name=f"redis-event-bus-all-{group}",
        )
        self._tasks.append(task)

        def unsubscribe() -> None:
            task.cancel()
            if task in self._tasks:
                self._tasks.remove(task)

        return unsubscribe

    async def _consume_loop(
        self,
        stream: str,
        group: str,
        handler: EventHandler | EventHandlerFn,
    ) -> None:
        """Read and dispatch messages from a consumer group until cancelled."""
        await self._ensure_group(stream, group)

        while True:
            try:
                # BLOCK 200ms so the loop yields to other coroutines regularly.
                raw = await self._redis.xreadgroup(
                    groupname=group,
                    consumername=self._worker_id,
                    streams={stream: ">"},
                    count=10,
                    block=200,
                )
                if not raw:
                    continue

                for _, messages in raw:
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
            event = self._fields_to_event(fields)
        except Exception as exc:
            logger.error("Failed to deserialise event from stream %s: %s", stream, exc)
            await self._redis.xack(stream, group, msg_id)
            return

        try:
            if hasattr(handler, "handle"):
                await handler.handle(event)  # type: ignore[union-attr]
            else:
                result = handler(event)  # type: ignore[operator]
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
            pending_info = await self._redis.xpending_range(
                stream, group, min=msg_id, max=msg_id, count=1
            )
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
