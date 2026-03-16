"""Session lifecycle — bootstrap/ingest/compact/dispose."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable

from cemaf.core.enums import MemoryScope
from cemaf.core.types import JSON
from cemaf.core.utils import utc_now
from cemaf.memory.base import MemoryItem
from cemaf.memory.compaction import CompactedMemory, MemoryCompactor
from cemaf.memory.episodic import EpisodicEvent
from cemaf.memory.extraction_pipeline import ExtractionPipeline
from cemaf.memory.manager import MemoryManager
from cemaf.memory.semantic import MemoryQuery


class SessionPhase(str, Enum):
    """Lifecycle phases for a memory session."""

    CREATED = "created"
    BOOTSTRAPPED = "bootstrapped"
    ACTIVE = "active"
    COMPACTING = "compacting"
    DISPOSED = "disposed"


# Valid phase transitions
_VALID_TRANSITIONS: dict[SessionPhase, tuple[SessionPhase, ...]] = {
    SessionPhase.CREATED: (SessionPhase.BOOTSTRAPPED, SessionPhase.DISPOSED),
    SessionPhase.BOOTSTRAPPED: (SessionPhase.ACTIVE, SessionPhase.DISPOSED),
    SessionPhase.ACTIVE: (SessionPhase.COMPACTING, SessionPhase.DISPOSED),
    SessionPhase.COMPACTING: (SessionPhase.ACTIVE, SessionPhase.DISPOSED),
    SessionPhase.DISPOSED: (),
}


@dataclass(frozen=True)
class SessionState:
    """Tracks the current state of a memory session."""

    session_id: str
    phase: SessionPhase
    episode_id: str | None = None
    started_at: datetime = field(default_factory=utc_now)
    memory_count: int = 0

    def with_memory_count(self, count: int) -> SessionState:
        """Return a new state with updated memory count (same phase)."""
        return SessionState(
            session_id=self.session_id,
            phase=self.phase,
            episode_id=self.episode_id,
            started_at=self.started_at,
            memory_count=count,
        )

    def _transition(self, target: SessionPhase, **kwargs: object) -> SessionState:
        """Create a new state with validated phase transition."""
        valid = _VALID_TRANSITIONS.get(self.phase, ())
        if target not in valid:
            raise ValueError(f"Invalid transition: {self.phase.value} -> {target.value}")
        return SessionState(
            session_id=self.session_id,
            phase=target,
            episode_id=kwargs.get("episode_id", self.episode_id),  # type: ignore[arg-type]
            started_at=self.started_at,
            memory_count=kwargs.get("memory_count", self.memory_count),  # type: ignore[arg-type]
        )


@runtime_checkable
class SessionManager(Protocol):
    """Protocol for session lifecycle management."""

    async def bootstrap(
        self,
        session_id: str,
        *,
        scopes: tuple[MemoryScope, ...] = (MemoryScope.BRAND, MemoryScope.PROJECT),
    ) -> SessionState: ...

    async def ingest(
        self,
        session_id: str,
        key: str,
        value: JSON,
        *,
        confidence: float = 1.0,
    ) -> MemoryItem: ...

    async def compact(
        self,
        session_id: str,
    ) -> tuple[CompactedMemory, ...]: ...

    async def dispose(self, session_id: str) -> int: ...

    async def get_state(self, session_id: str) -> SessionState | None: ...


class DefaultSessionManager:
    """Manages session lifecycle with bootstrap/ingest/compact/dispose."""

    def __init__(
        self,
        *,
        memory_manager: MemoryManager,
        compactor: MemoryCompactor,
        extraction_pipeline: ExtractionPipeline | None = None,
    ) -> None:
        self._manager = memory_manager
        self._compactor = compactor
        self._extraction_pipeline = extraction_pipeline
        self._sessions: dict[str, SessionState] = {}

    async def bootstrap(
        self,
        session_id: str,
        *,
        scopes: tuple[MemoryScope, ...] = (MemoryScope.BRAND, MemoryScope.PROJECT),
    ) -> SessionState:
        """Initialize session: load memories from scopes, start episode."""
        state = SessionState(
            session_id=session_id,
            phase=SessionPhase.CREATED,
        )

        # Load existing memories from specified scopes
        memory_count = 0
        for scope in scopes:
            results = await self._manager.recall(
                query=MemoryQuery(scope=scope, limit=1000),
            )
            memory_count += len(results)

        # Start episode
        episode = await self._manager.start_episode(session_id=session_id)

        # Transition CREATED -> BOOTSTRAPPED -> ACTIVE
        state = state._transition(
            SessionPhase.BOOTSTRAPPED,
            episode_id=episode.id,
            memory_count=memory_count,
        )
        state = state._transition(SessionPhase.ACTIVE)

        self._sessions[session_id] = state
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
        state = self._sessions.get(session_id)
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

        # Record episodic event
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

        # Update memory count (same-phase update, not a transition)
        self._sessions[session_id] = state.with_memory_count(
            count=state.memory_count + 1,
        )

        return item

    async def compact(
        self,
        session_id: str,
    ) -> tuple[CompactedMemory, ...]:
        """Compact session memories using the configured compactor."""
        state = self._require_state(session_id=session_id)
        if state.phase not in (SessionPhase.ACTIVE,):
            raise ValueError(f"Cannot compact in phase {state.phase.value}, must be active")

        # Transition to COMPACTING
        state = state._transition(SessionPhase.COMPACTING)
        self._sessions[session_id] = state

        # Gather session memories
        results = await self._manager.recall(
            query=MemoryQuery(scope=MemoryScope.SESSION, limit=1000),
        )
        items = tuple(r.item for r in results)

        # Compact
        compacted = await self._compactor.compact_batch_to_budget(
            items=items,
            token_budget=4096,
        )

        # Transition back to ACTIVE
        state = state._transition(SessionPhase.ACTIVE)
        self._sessions[session_id] = state

        return compacted

    async def dispose(self, session_id: str) -> int:
        """Run extraction (if configured), close episode, clean up SESSION items."""
        state = self._sessions.get(session_id)
        if state is None:
            return 0
        if state.phase == SessionPhase.DISPOSED:
            return 0

        # Run extraction pipeline before cleanup
        if self._extraction_pipeline is not None:
            session_results = await self._manager.recall(
                query=MemoryQuery(scope=MemoryScope.SESSION, limit=1000),
            )
            session_memories = tuple(r.item for r in session_results)
            episodes = ()
            recent_events = await self._manager.get_recent_history(
                session_id=session_id,
                limit=100,
            )
            await self._extraction_pipeline.run(
                session_memories=session_memories,
                episodes=episodes,
                recent_events=recent_events,
            )

        # Close episode
        if state.episode_id:
            await self._manager.end_episode(episode_id=state.episode_id)

        # Clean up session-scoped memories explicitly (not global cleanup)
        session_results = await self._manager.recall(
            query=MemoryQuery(scope=MemoryScope.SESSION, limit=10000),
        )
        removed = 0
        for result in session_results:
            if await self._manager.forget(scope=result.item.scope, key=result.item.key):
                removed += 1

        # Transition to DISPOSED
        state = state._transition(SessionPhase.DISPOSED, memory_count=0)
        self._sessions[session_id] = state

        # Lazy cleanup: purge other disposed sessions to prevent unbounded growth
        self._cleanup_disposed(keep_session_id=session_id)

        return removed

    async def get_state(self, session_id: str) -> SessionState | None:
        """Get the current session state."""
        return self._sessions.get(session_id)

    def _require_state(self, session_id: str) -> SessionState:
        """Get state or raise if session not found."""
        state = self._sessions.get(session_id)
        if state is None:
            raise KeyError(f"Session not found: {session_id}")
        return state

    def _cleanup_disposed(self, *, keep_session_id: str) -> None:
        """Remove disposed sessions from tracking, except the one just disposed."""
        disposed = [
            sid
            for sid, s in self._sessions.items()
            if s.phase == SessionPhase.DISPOSED and sid != keep_session_id
        ]
        for sid in disposed:
            del self._sessions[sid]
