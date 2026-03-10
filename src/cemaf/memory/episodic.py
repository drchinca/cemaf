"""Episodic memory — time-ordered event sequences within sessions."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from cemaf.core.types import JSON
from cemaf.core.utils import generate_id, utc_now


@dataclass(frozen=True)
class EpisodicEvent:
    """A single event within an episode."""

    timestamp: datetime
    event_type: str  # Maps to EventType values (e.g. "agent.completed")
    actor: str  # agent_id, tool_id, "system"
    action: str
    content: JSON = field(default_factory=dict)
    importance: float = 0.5  # 0.0-1.0 for compaction decisions


@dataclass(frozen=True)
class Episode:
    """A sequence of events within a session."""

    id: str
    session_id: str
    events: tuple[EpisodicEvent, ...] = ()
    started_at: datetime = field(default_factory=utc_now)
    ended_at: datetime | None = None
    summary: str | None = None
    metadata: JSON = field(default_factory=dict)

    def with_event(self, event: EpisodicEvent) -> Episode:
        """Return a new episode with the event appended."""
        return Episode(
            id=self.id,
            session_id=self.session_id,
            events=(*self.events, event),
            started_at=self.started_at,
            ended_at=self.ended_at,
            summary=self.summary,
            metadata=self.metadata,
        )

    def with_summary(self, summary: str) -> Episode:
        """Return a new episode with the given summary."""
        return Episode(
            id=self.id,
            session_id=self.session_id,
            events=self.events,
            started_at=self.started_at,
            ended_at=self.ended_at,
            summary=summary,
            metadata=self.metadata,
        )

    def close(self) -> Episode:
        """Return a closed copy with ended_at set."""
        return Episode(
            id=self.id,
            session_id=self.session_id,
            events=self.events,
            started_at=self.started_at,
            ended_at=utc_now(),
            summary=self.summary,
            metadata=self.metadata,
        )


@runtime_checkable
class EpisodicStore(Protocol):
    """Protocol for episodic memory storage."""

    async def start_episode(
        self,
        session_id: str,
        *,
        metadata: JSON | None = None,
    ) -> Episode: ...

    async def append_event(
        self,
        episode_id: str,
        event: EpisodicEvent,
    ) -> Episode: ...

    async def close_episode(self, episode_id: str) -> Episode: ...

    async def get_episode(self, episode_id: str) -> Episode | None: ...

    async def list_episodes(
        self,
        session_id: str,
        *,
        limit: int = 50,
    ) -> tuple[Episode, ...]: ...

    async def get_recent_events(
        self,
        session_id: str,
        *,
        limit: int = 20,
    ) -> tuple[EpisodicEvent, ...]: ...


class InMemoryEpisodicStore:
    """In-memory episodic store for testing and session-scoped use."""

    def __init__(self) -> None:
        self._episodes: dict[str, Episode] = {}
        self._session_index: dict[str, list[str]] = {}

    async def start_episode(
        self,
        session_id: str,
        *,
        metadata: JSON | None = None,
    ) -> Episode:
        """Create and store a new episode."""
        episode = Episode(
            id=generate_id(prefix="ep"),
            session_id=session_id,
            metadata=metadata or {},
        )
        self._episodes[episode.id] = episode
        self._session_index.setdefault(session_id, []).append(episode.id)
        return episode

    async def append_event(
        self,
        episode_id: str,
        event: EpisodicEvent,
    ) -> Episode:
        """Append an event to an episode."""
        episode = self._episodes.get(episode_id)
        if episode is None:
            raise KeyError(f"Episode not found: {episode_id}")
        if episode.ended_at is not None:
            raise ValueError(f"Episode already closed: {episode_id}")
        updated = episode.with_event(event=event)
        self._episodes[episode_id] = updated
        return updated

    async def close_episode(self, episode_id: str) -> Episode:
        """Close an episode."""
        episode = self._episodes.get(episode_id)
        if episode is None:
            raise KeyError(f"Episode not found: {episode_id}")
        closed = episode.close()
        self._episodes[episode_id] = closed
        return closed

    async def get_episode(self, episode_id: str) -> Episode | None:
        """Retrieve an episode by ID."""
        return self._episodes.get(episode_id)

    async def list_episodes(
        self,
        session_id: str,
        *,
        limit: int = 50,
    ) -> tuple[Episode, ...]:
        """List episodes for a session, newest first."""
        episode_ids = self._session_index.get(session_id, [])
        episodes = [self._episodes[eid] for eid in reversed(episode_ids) if eid in self._episodes]
        return tuple(episodes[:limit])

    async def get_recent_events(
        self,
        session_id: str,
        *,
        limit: int = 20,
    ) -> tuple[EpisodicEvent, ...]:
        """Get recent events across all episodes in a session."""
        episode_ids = self._session_index.get(session_id, [])
        all_events: list[EpisodicEvent] = []
        # Walk episodes newest-first, collect events
        for eid in reversed(episode_ids):
            episode = self._episodes.get(eid)
            if episode is None:
                continue
            # Events within episode are already time-ordered
            all_events.extend(reversed(episode.events))
            if len(all_events) >= limit:
                break
        # Return in chronological order (oldest first), limited
        return tuple(reversed(all_events[:limit]))
