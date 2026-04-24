"""Distributed session manager backed by Redis for session state.

Drop-in replacement for DefaultSessionManager:
- Session state stored in Redis (RedisSessionStore) instead of in-process dict
- set_nx ensures idempotent bootstrap across horizontally-scaled replicas
- acquire_lock prevents concurrent compaction races across processes
- Redis TTL handles session cleanup; no _cleanup_disposed bookkeeping needed
- All other logic (episode management, compaction, extraction) is identical
  to DefaultSessionManager
"""

from cemaf.core.enums import MemoryScope
from cemaf.core.types import JSON
from cemaf.core.utils import utc_now
from cemaf.memory.base import MemoryItem
from cemaf.memory.compaction import CompactedMemory, MemoryCompactor
from cemaf.memory.episodic import EpisodicEvent
from cemaf.memory.extraction_pipeline import ExtractionPipeline
from cemaf.memory.manager import MemoryManager
from cemaf.memory.redis_session_store import RedisSessionStore
from cemaf.memory.semantic import MemoryQuery
from cemaf.memory.session import SessionPhase, SessionState, _VALID_TRANSITIONS


class DistributedSessionManager:
    """Session manager with Redis-backed state for multi-process deployments."""

    def __init__(
        self,
        *,
        memory_manager: MemoryManager,
        compactor: MemoryCompactor,
        session_store: RedisSessionStore,
        extraction_pipeline: ExtractionPipeline | None = None,
    ) -> None:
        self._manager = memory_manager
        self._compactor = compactor
        self._session_store = session_store
        self._extraction_pipeline = extraction_pipeline

    async def bootstrap(
        self,
        session_id: str,
        *,
        scopes: tuple[MemoryScope, ...] = (MemoryScope.BRAND, MemoryScope.PROJECT),
    ) -> SessionState:
        """Initialize session, idempotent across replicas.

        If the session already exists and is ACTIVE, returns the existing state
        without re-running bootstrap to avoid double-counting memory_count and
        creating duplicate episodes.
        """
        existing = await self._session_store.get_state(session_id)
        if existing is not None and existing.phase == SessionPhase.ACTIVE:
            return existing

        state = SessionState(
            session_id=session_id,
            phase=SessionPhase.CREATED,
        )

        memory_count = 0
        for scope in scopes:
            results = await self._manager.recall(
                query=MemoryQuery(scope=scope, limit=1000),
            )
            memory_count += len(results)

        episode = await self._manager.start_episode(session_id=session_id)

        state = state._transition(
            SessionPhase.BOOTSTRAPPED,
            episode_id=episode.id,
            memory_count=memory_count,
        )
        state = state._transition(SessionPhase.ACTIVE)

        # NX: only creates the key if absent; if a concurrent replica beat us
        # and the key exists (ACTIVE), we discard our local state and return theirs.
        set_ok = await self._session_store.set_nx(session_id, state)
        if not set_ok:
            winner = await self._session_store.get_state(session_id)
            if winner is not None:
                return winner

        return state

    async def ingest(
        self,
        session_id: str,
        key: str,
        value: JSON,
        *,
        confidence: float = 1.0,
    ) -> MemoryItem:
        """Store to SESSION scope and record episodic event."""
        state = await self._session_store.get_state(session_id)
        if state is None:
            return await self._manager.remember(
                scope=MemoryScope.SESSION,
                key=key,
                value=value,
                confidence=confidence,
            )
        if state.phase != SessionPhase.ACTIVE:
            raise ValueError(f"Cannot ingest in phase {state.phase.value}, must be active")

        item = await self._manager.remember(
            scope=MemoryScope.SESSION,
            key=key,
            value=value,
            confidence=confidence,
        )

        if state.episode_id:
            event = EpisodicEvent(
                timestamp=utc_now(),
                event_type="memory.item.set",
                actor="session_manager",
                action="ingest",
                content={"key": key},
            )
            await self._manager.record_event(
                episode_id=state.episode_id,
                event=event,
            )

        updated = state.with_memory_count(count=state.memory_count + 1)
        await self._session_store.set_state(session_id, updated)

        return item

    async def compact(
        self,
        session_id: str,
    ) -> tuple[CompactedMemory, ...]:
        """Compact session memories; distributed lock prevents concurrent runs."""
        state = await self._require_state(session_id=session_id)
        if state.phase not in (SessionPhase.ACTIVE,):
            raise ValueError(f"Cannot compact in phase {state.phase.value}, must be active")

        async with self._session_store.acquire_lock(session_id) as lock_acquired:
            if not lock_acquired:
                # Another replica is already compacting; return empty to signal back-off
                return ()

            # Re-read state under lock in case it changed
            state = await self._require_state(session_id=session_id)
            if state.phase != SessionPhase.ACTIVE:
                return ()

            compacting_state = state._transition(SessionPhase.COMPACTING)
            await self._session_store.set_state(session_id, compacting_state)

            results = await self._manager.recall(
                query=MemoryQuery(scope=MemoryScope.SESSION, limit=1000),
            )
            items = tuple(r.item for r in results)

            compacted = await self._compactor.compact_batch_to_budget(
                items=items,
                token_budget=4096,
            )

            active_state = compacting_state._transition(SessionPhase.ACTIVE)
            await self._session_store.set_state(session_id, active_state)

        return compacted

    async def dispose(self, session_id: str) -> int:
        """Run extraction, close episode, clean up SESSION-scoped memories."""
        state = await self._session_store.get_state(session_id)
        if state is None:
            return 0
        if state.phase == SessionPhase.DISPOSED:
            return 0

        if self._extraction_pipeline is not None:
            session_results = await self._manager.recall(
                query=MemoryQuery(scope=MemoryScope.SESSION, limit=1000),
            )
            session_memories = tuple(r.item for r in session_results)
            recent_events = await self._manager.get_recent_history(
                session_id=session_id,
                limit=100,
            )
            await self._extraction_pipeline.run(
                session_memories=session_memories,
                episodes=(),
                recent_events=recent_events,
            )

        if state.episode_id:
            await self._manager.end_episode(episode_id=state.episode_id)

        session_results = await self._manager.recall(
            query=MemoryQuery(scope=MemoryScope.SESSION, limit=10000),
        )
        removed = 0
        for result in session_results:
            if await self._manager.forget(scope=result.item.scope, key=result.item.key):
                removed += 1

        disposed_state = state._transition(SessionPhase.DISPOSED, memory_count=0)
        await self._session_store.set_state(session_id, disposed_state)
        # Redis TTL will evict this key naturally; no manual cleanup dict needed.

        return removed

    async def get_state(self, session_id: str) -> SessionState | None:
        """Get the current session state from Redis."""
        return await self._session_store.get_state(session_id)

    async def _require_state(self, session_id: str) -> SessionState:
        """Get state or raise KeyError if the session is not found."""
        state = await self._session_store.get_state(session_id)
        if state is None:
            raise KeyError(f"Session not found: {session_id}")
        return state
