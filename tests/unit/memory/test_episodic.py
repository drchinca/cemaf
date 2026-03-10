"""Tests for episodic memory."""

import pytest

from cemaf.core.types import JSON
from cemaf.core.utils import utc_now
from cemaf.memory.episodic import (
    Episode,
    EpisodicEvent,
    EpisodicStore,
    InMemoryEpisodicStore,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_event(
    *,
    event_type: str = "agent.completed",
    actor: str = "agent-1",
    action: str = "test_action",
    importance: float = 0.5,
) -> EpisodicEvent:
    return EpisodicEvent(
        timestamp=utc_now(),
        event_type=event_type,
        actor=actor,
        action=action,
        importance=importance,
    )


# ---------------------------------------------------------------------------
# EpisodicEvent
# ---------------------------------------------------------------------------


class TestEpisodicEvent:
    def test_frozen(self) -> None:
        event = _make_event()
        with pytest.raises(AttributeError):
            event.action = "modified"  # type: ignore[misc]

    def test_default_content_is_empty_dict(self) -> None:
        event = _make_event()
        assert event.content == {}

    def test_default_importance(self) -> None:
        event = _make_event()
        assert event.importance == 0.5

    def test_custom_content(self) -> None:
        content: JSON = {"key": "value"}
        event = EpisodicEvent(
            timestamp=utc_now(),
            event_type="test",
            actor="system",
            action="store",
            content=content,
        )
        assert event.content == {"key": "value"}


# ---------------------------------------------------------------------------
# Episode
# ---------------------------------------------------------------------------


class TestEpisode:
    def test_frozen(self) -> None:
        ep = Episode(id="ep-1", session_id="sess-1")
        with pytest.raises(AttributeError):
            ep.summary = "modified"  # type: ignore[misc]

    def test_with_event_appends(self) -> None:
        ep = Episode(id="ep-1", session_id="sess-1")
        event = _make_event()
        updated = ep.with_event(event=event)
        assert len(updated.events) == 1
        assert updated.events[0] is event
        # Original unchanged
        assert len(ep.events) == 0

    def test_with_event_preserves_order(self) -> None:
        ep = Episode(id="ep-1", session_id="sess-1")
        e1 = _make_event(action="first")
        e2 = _make_event(action="second")
        updated = ep.with_event(event=e1).with_event(event=e2)
        assert updated.events[0].action == "first"
        assert updated.events[1].action == "second"

    def test_with_summary(self) -> None:
        ep = Episode(id="ep-1", session_id="sess-1")
        updated = ep.with_summary(summary="Test summary")
        assert updated.summary == "Test summary"
        assert ep.summary is None

    def test_close_sets_ended_at(self) -> None:
        ep = Episode(id="ep-1", session_id="sess-1")
        assert ep.ended_at is None
        closed = ep.close()
        assert closed.ended_at is not None
        assert ep.ended_at is None  # Original unchanged

    def test_defaults(self) -> None:
        ep = Episode(id="ep-1", session_id="sess-1")
        assert ep.events == ()
        assert ep.ended_at is None
        assert ep.summary is None
        assert ep.metadata == {}


# ---------------------------------------------------------------------------
# InMemoryEpisodicStore — protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_implements_episodic_store(self) -> None:
        store = InMemoryEpisodicStore()
        assert isinstance(store, EpisodicStore)


# ---------------------------------------------------------------------------
# InMemoryEpisodicStore — start/close lifecycle
# ---------------------------------------------------------------------------


class TestEpisodeLifecycle:
    @pytest.mark.asyncio
    async def test_start_episode(self) -> None:
        store = InMemoryEpisodicStore()
        ep = await store.start_episode(session_id="sess-1")
        assert ep.session_id == "sess-1"
        assert ep.id.startswith("ep_")
        assert ep.ended_at is None

    @pytest.mark.asyncio
    async def test_start_with_metadata(self) -> None:
        store = InMemoryEpisodicStore()
        ep = await store.start_episode(
            session_id="sess-1",
            metadata={"source": "test"},
        )
        assert ep.metadata == {"source": "test"}

    @pytest.mark.asyncio
    async def test_close_episode(self) -> None:
        store = InMemoryEpisodicStore()
        ep = await store.start_episode(session_id="sess-1")
        closed = await store.close_episode(episode_id=ep.id)
        assert closed.ended_at is not None

    @pytest.mark.asyncio
    async def test_close_nonexistent_raises(self) -> None:
        store = InMemoryEpisodicStore()
        with pytest.raises(KeyError):
            await store.close_episode(episode_id="nonexistent")


# ---------------------------------------------------------------------------
# InMemoryEpisodicStore — event recording
# ---------------------------------------------------------------------------


class TestEventRecording:
    @pytest.mark.asyncio
    async def test_append_event(self) -> None:
        store = InMemoryEpisodicStore()
        ep = await store.start_episode(session_id="sess-1")
        event = _make_event()
        updated = await store.append_event(episode_id=ep.id, event=event)
        assert len(updated.events) == 1

    @pytest.mark.asyncio
    async def test_append_multiple_events(self) -> None:
        store = InMemoryEpisodicStore()
        ep = await store.start_episode(session_id="sess-1")
        for i in range(3):
            await store.append_event(
                episode_id=ep.id,
                event=_make_event(action=f"action_{i}"),
            )
        retrieved = await store.get_episode(episode_id=ep.id)
        assert retrieved is not None
        assert len(retrieved.events) == 3

    @pytest.mark.asyncio
    async def test_append_to_closed_raises(self) -> None:
        store = InMemoryEpisodicStore()
        ep = await store.start_episode(session_id="sess-1")
        await store.close_episode(episode_id=ep.id)
        with pytest.raises(ValueError, match="already closed"):
            await store.append_event(
                episode_id=ep.id,
                event=_make_event(),
            )

    @pytest.mark.asyncio
    async def test_append_to_nonexistent_raises(self) -> None:
        store = InMemoryEpisodicStore()
        with pytest.raises(KeyError):
            await store.append_event(
                episode_id="nonexistent",
                event=_make_event(),
            )


# ---------------------------------------------------------------------------
# InMemoryEpisodicStore — retrieval
# ---------------------------------------------------------------------------


class TestRetrieval:
    @pytest.mark.asyncio
    async def test_get_episode(self) -> None:
        store = InMemoryEpisodicStore()
        ep = await store.start_episode(session_id="sess-1")
        retrieved = await store.get_episode(episode_id=ep.id)
        assert retrieved is not None
        assert retrieved.id == ep.id

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self) -> None:
        store = InMemoryEpisodicStore()
        result = await store.get_episode(episode_id="nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_episodes_newest_first(self) -> None:
        store = InMemoryEpisodicStore()
        ep1 = await store.start_episode(session_id="sess-1")
        ep2 = await store.start_episode(session_id="sess-1")
        episodes = await store.list_episodes(session_id="sess-1")
        assert len(episodes) == 2
        assert episodes[0].id == ep2.id
        assert episodes[1].id == ep1.id

    @pytest.mark.asyncio
    async def test_list_episodes_respects_limit(self) -> None:
        store = InMemoryEpisodicStore()
        for _ in range(5):
            await store.start_episode(session_id="sess-1")
        episodes = await store.list_episodes(session_id="sess-1", limit=3)
        assert len(episodes) == 3

    @pytest.mark.asyncio
    async def test_list_episodes_scoped_to_session(self) -> None:
        store = InMemoryEpisodicStore()
        await store.start_episode(session_id="sess-1")
        await store.start_episode(session_id="sess-2")
        episodes = await store.list_episodes(session_id="sess-1")
        assert len(episodes) == 1


# ---------------------------------------------------------------------------
# InMemoryEpisodicStore — get_recent_events
# ---------------------------------------------------------------------------


class TestRecentEvents:
    @pytest.mark.asyncio
    async def test_recent_events_across_episodes(self) -> None:
        store = InMemoryEpisodicStore()
        ep1 = await store.start_episode(session_id="sess-1")
        await store.append_event(
            episode_id=ep1.id,
            event=_make_event(action="ep1_action"),
        )
        await store.close_episode(episode_id=ep1.id)

        ep2 = await store.start_episode(session_id="sess-1")
        await store.append_event(
            episode_id=ep2.id,
            event=_make_event(action="ep2_action"),
        )

        events = await store.get_recent_events(session_id="sess-1")
        assert len(events) == 2
        # Chronological order (oldest first)
        assert events[0].action == "ep1_action"
        assert events[1].action == "ep2_action"

    @pytest.mark.asyncio
    async def test_recent_events_respects_limit(self) -> None:
        store = InMemoryEpisodicStore()
        ep = await store.start_episode(session_id="sess-1")
        for i in range(10):
            await store.append_event(
                episode_id=ep.id,
                event=_make_event(action=f"action_{i}"),
            )
        events = await store.get_recent_events(session_id="sess-1", limit=5)
        assert len(events) == 5

    @pytest.mark.asyncio
    async def test_recent_events_empty_session(self) -> None:
        store = InMemoryEpisodicStore()
        events = await store.get_recent_events(session_id="nonexistent")
        assert events == ()
