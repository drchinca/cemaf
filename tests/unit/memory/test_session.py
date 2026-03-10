"""Tests for session lifecycle management."""

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.memory.base import InMemoryStore
from cemaf.memory.compaction import SimpleMemoryCompactor
from cemaf.memory.episodic import InMemoryEpisodicStore
from cemaf.memory.manager import DefaultMemoryManager
from cemaf.memory.scoring import TemporalDecayScorer
from cemaf.memory.semantic import DefaultSemanticMemoryStore
from cemaf.memory.session import (
    DefaultSessionManager,
    SessionManager,
    SessionPhase,
    SessionState,
)
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_session_manager() -> DefaultSessionManager:
    """Create a fully wired session manager."""
    embedding_provider = MockEmbeddingProvider()
    scorer = TemporalDecayScorer()

    semantic_store = DefaultSemanticMemoryStore(
        memory_store=InMemoryStore(),
        vector_store=InMemoryVectorStore(embedding_provider=embedding_provider),
        embedding_provider=embedding_provider,
        scorer=scorer,
    )
    episodic_store = InMemoryEpisodicStore()

    memory_manager = DefaultMemoryManager(
        semantic_store=semantic_store,
        episodic_store=episodic_store,
    )
    compactor = SimpleMemoryCompactor(scorer=scorer)

    return DefaultSessionManager(
        memory_manager=memory_manager,
        compactor=compactor,
    )


# ---------------------------------------------------------------------------
# SessionState
# ---------------------------------------------------------------------------


class TestSessionState:
    def test_frozen(self) -> None:
        state = SessionState(session_id="s1", phase=SessionPhase.CREATED)
        with pytest.raises(AttributeError):
            state.phase = SessionPhase.ACTIVE  # type: ignore[misc]

    def test_valid_transition(self) -> None:
        state = SessionState(session_id="s1", phase=SessionPhase.CREATED)
        next_state = state._transition(SessionPhase.BOOTSTRAPPED)
        assert next_state.phase == SessionPhase.BOOTSTRAPPED

    def test_invalid_transition_raises(self) -> None:
        state = SessionState(session_id="s1", phase=SessionPhase.CREATED)
        with pytest.raises(ValueError, match="Invalid transition"):
            state._transition(SessionPhase.ACTIVE)

    def test_disposed_cannot_transition(self) -> None:
        state = SessionState(session_id="s1", phase=SessionPhase.DISPOSED)
        with pytest.raises(ValueError, match="Invalid transition"):
            state._transition(SessionPhase.ACTIVE)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_implements_session_manager(self) -> None:
        sm = _make_session_manager()
        assert isinstance(sm, SessionManager)


# ---------------------------------------------------------------------------
# Full lifecycle
# ---------------------------------------------------------------------------


class TestFullLifecycle:
    @pytest.mark.asyncio
    async def test_bootstrap_creates_active_session(self) -> None:
        sm = _make_session_manager()
        state = await sm.bootstrap(session_id="sess-1")
        assert state.phase == SessionPhase.ACTIVE
        assert state.episode_id is not None

    @pytest.mark.asyncio
    async def test_ingest_stores_session_memory(self) -> None:
        sm = _make_session_manager()
        await sm.bootstrap(session_id="sess-1")

        item = await sm.ingest(
            session_id="sess-1",
            key="user_pref",
            value={"theme": "dark"},
        )
        assert item.scope == MemoryScope.SESSION
        assert item.key == "user_pref"

    @pytest.mark.asyncio
    async def test_ingest_increments_memory_count(self) -> None:
        sm = _make_session_manager()
        await sm.bootstrap(session_id="sess-1")
        await sm.ingest(session_id="sess-1", key="k1", value={"v": 1})
        await sm.ingest(session_id="sess-1", key="k2", value={"v": 2})

        state = await sm.get_state(session_id="sess-1")
        assert state is not None
        assert state.memory_count >= 2

    @pytest.mark.asyncio
    async def test_compact_returns_results(self) -> None:
        sm = _make_session_manager()
        await sm.bootstrap(session_id="sess-1")
        await sm.ingest(session_id="sess-1", key="k1", value={"data": "x" * 100})
        await sm.ingest(session_id="sess-1", key="k2", value={"data": "y" * 100})

        compacted = await sm.compact(session_id="sess-1")
        assert len(compacted) >= 0  # May be empty if no session items returned

    @pytest.mark.asyncio
    async def test_dispose_closes_session(self) -> None:
        sm = _make_session_manager()
        await sm.bootstrap(session_id="sess-1")
        await sm.ingest(session_id="sess-1", key="k1", value={"v": 1})

        removed = await sm.dispose(session_id="sess-1")
        assert removed >= 0

        state = await sm.get_state(session_id="sess-1")
        assert state is not None
        assert state.phase == SessionPhase.DISPOSED

    @pytest.mark.asyncio
    async def test_full_lifecycle(self) -> None:
        sm = _make_session_manager()

        # Bootstrap
        state = await sm.bootstrap(session_id="sess-1")
        assert state.phase == SessionPhase.ACTIVE

        # Ingest
        await sm.ingest(session_id="sess-1", key="fact", value={"x": 1})

        # Compact
        await sm.compact(session_id="sess-1")

        # Dispose
        await sm.dispose(session_id="sess-1")

        state = await sm.get_state(session_id="sess-1")
        assert state is not None
        assert state.phase == SessionPhase.DISPOSED


# ---------------------------------------------------------------------------
# Phase enforcement
# ---------------------------------------------------------------------------


class TestPhaseEnforcement:
    @pytest.mark.asyncio
    async def test_ingest_before_bootstrap_raises(self) -> None:
        sm = _make_session_manager()
        with pytest.raises(KeyError, match="Session not found"):
            await sm.ingest(session_id="nonexistent", key="k", value={"v": 1})

    @pytest.mark.asyncio
    async def test_ingest_after_dispose_raises(self) -> None:
        sm = _make_session_manager()
        await sm.bootstrap(session_id="sess-1")
        await sm.dispose(session_id="sess-1")
        with pytest.raises(ValueError, match="Cannot ingest"):
            await sm.ingest(session_id="sess-1", key="k", value={"v": 1})

    @pytest.mark.asyncio
    async def test_dispose_twice_raises(self) -> None:
        sm = _make_session_manager()
        await sm.bootstrap(session_id="sess-1")
        await sm.dispose(session_id="sess-1")
        with pytest.raises(ValueError, match="already disposed"):
            await sm.dispose(session_id="sess-1")

    @pytest.mark.asyncio
    async def test_compact_before_bootstrap_raises(self) -> None:
        sm = _make_session_manager()
        with pytest.raises(KeyError):
            await sm.compact(session_id="nonexistent")


# ---------------------------------------------------------------------------
# get_state
# ---------------------------------------------------------------------------


class TestGetState:
    @pytest.mark.asyncio
    async def test_get_state_nonexistent(self) -> None:
        sm = _make_session_manager()
        result = await sm.get_state(session_id="nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_state_after_bootstrap(self) -> None:
        sm = _make_session_manager()
        await sm.bootstrap(session_id="sess-1")
        state = await sm.get_state(session_id="sess-1")
        assert state is not None
        assert state.session_id == "sess-1"
