"""Redis-backed session state store for distributed session management.

Replaces the in-process dict in DefaultSessionManager with a Redis backend:
- from_url auto-detects cluster vs single-node topology
- SessionState serialized to JSON; enums stored as their .value strings
- NX (set-if-not-exists) for idempotent session creation across replicas
- EX TTL on every write so Redis evicts stale sessions automatically
- Distributed lock uses SET NX EX for single-node safety; document that
  multi-node Redlock requires the redlock-py package
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from cemaf.core.utils import utc_now
from cemaf.memory.session import SessionPhase, SessionState


class RedisSessionStore:
    """Redis-backed store for SessionState with TTL and distributed locking."""

    def __init__(
        self,
        redis_url: str,
        ttl_seconds: int = 86400,
        key_prefix: str = "cemaf:session",
    ) -> None:
        self._redis_url = redis_url
        self._ttl_seconds = ttl_seconds
        self._key_prefix = key_prefix
        self._redis: object | None = None

    async def _client(self) -> object:
        if self._redis is not None:
            return self._redis
        try:
            from redis.asyncio import from_url
        except ImportError as exc:
            raise ImportError(
                "redis[asyncio] is required for RedisSessionStore. "
                "Install it with: pip install 'cemaf[redis]'"
            ) from exc
        self._redis = from_url(self._redis_url, decode_responses=True)
        return self._redis

    def _session_key(self, session_id: str) -> str:
        return f"{self._key_prefix}:{session_id}"

    def _lock_key(self, session_id: str) -> str:
        return f"{self._key_prefix}:lock:{session_id}"

    @staticmethod
    def _serialize(state: SessionState) -> str:
        return json.dumps(
            {
                "session_id": state.session_id,
                "phase": state.phase.value,
                "episode_id": state.episode_id,
                "started_at": state.started_at.isoformat(),
                "memory_count": state.memory_count,
            }
        )

    @staticmethod
    def _deserialize(raw: str) -> SessionState:
        data = json.loads(raw)
        started_at_raw = data["started_at"]
        started_at = (
            datetime.fromisoformat(started_at_raw)
            if isinstance(started_at_raw, str)
            else started_at_raw
        )
        return SessionState(
            session_id=data["session_id"],
            phase=SessionPhase(data["phase"]),
            episode_id=data.get("episode_id"),
            started_at=started_at,
            memory_count=int(data.get("memory_count", 0)),
        )

    async def set_nx(self, session_id: str, state: SessionState) -> bool:
        """Store state only if the key does not already exist.

        Returns True if the key was set (new session), False if it already existed.
        """

        client = await self._client()
        key = self._session_key(session_id)
        payload = self._serialize(state)
        # SET NX EX: atomic create-only with TTL
        result = await client.set(key, payload, nx=True, ex=self._ttl_seconds)  # type: ignore[union-attr]
        return result is not None

    async def get_state(self, session_id: str) -> SessionState | None:
        """Retrieve session state, returning None if absent or expired."""
        client = await self._client()
        key = self._session_key(session_id)
        raw = await client.get(key)  # type: ignore[union-attr]
        if raw is None:
            return None
        return self._deserialize(raw)

    async def set_state(self, session_id: str, state: SessionState) -> None:
        """Overwrite session state and reset TTL."""
        client = await self._client()
        key = self._session_key(session_id)
        payload = self._serialize(state)
        await client.set(key, payload, ex=self._ttl_seconds)  # type: ignore[union-attr]

    async def delete_state(self, session_id: str) -> bool:
        """Delete session state, returning True if the key existed."""
        client = await self._client()
        key = self._session_key(session_id)
        deleted = await client.delete(key)  # type: ignore[union-attr]
        return bool(deleted > 0)

    async def renew_ttl(self, session_id: str) -> None:
        """Reset the TTL for an existing session key without touching the value."""
        client = await self._client()
        key = self._session_key(session_id)
        await client.expire(key, self._ttl_seconds)  # type: ignore[union-attr]

    @asynccontextmanager
    async def acquire_lock(
        self,
        session_id: str,
        *,
        timeout_seconds: int = 30,
    ) -> AsyncIterator[bool]:
        """Distributed lock for a session using SET NX EX.

        Yields True if the lock was acquired, False if it was not (already held).
        Lock is released in the finally block regardless of outcome.

        Single-node safety only. For multi-node Redlock semantics use redlock-py.
        """
        client = await self._client()
        lock_key = self._lock_key(session_id)
        lock_value = f"{utc_now().isoformat()}:{session_id}"

        acquired = await client.set(  # type: ignore[union-attr]
            lock_key,
            lock_value,
            nx=True,
            ex=timeout_seconds,
        )
        try:
            yield acquired is not None
        finally:
            if acquired is not None:
                # Only delete if we still own the lock (value matches)
                current = await client.get(lock_key)  # type: ignore[union-attr]
                if current == lock_value:
                    await client.delete(lock_key)  # type: ignore[union-attr]

    async def close(self) -> None:
        """Close the Redis connection. Idempotent."""
        if self._redis is not None:
            await self._redis.aclose()  # type: ignore[union-attr]
            self._redis = None
