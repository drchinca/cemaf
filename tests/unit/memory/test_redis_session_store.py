"""Unit tests for RedisSessionStore using fakeredis (no live Redis required)."""

import pytest

fakeredis = pytest.importorskip("fakeredis", reason="fakeredis not installed")

from datetime import UTC, datetime

from cemaf.core.utils import utc_now
from cemaf.memory.redis_session_store import RedisSessionStore
from cemaf.memory.session import SessionPhase, SessionState


def _make_state(
    session_id: str = "sess_001",
    phase: SessionPhase = SessionPhase.ACTIVE,
    memory_count: int = 5,
) -> SessionState:
    return SessionState(
        session_id=session_id,
        phase=phase,
        episode_id="ep_001",
        started_at=utc_now(),
        memory_count=memory_count,
    )


@pytest.fixture
def fake_redis_store() -> "RedisSessionStore":
    """RedisSessionStore wired to a fakeredis server; no external dependency."""
    server = fakeredis.FakeServer()

    store = RedisSessionStore(
        redis_url="redis://localhost:6379",
        ttl_seconds=300,
        key_prefix="cemaf:test:session",
    )
    # Replace the internal client with a fakeredis instance
    import fakeredis.aioredis as fake_aio

    store._redis = fake_aio.FakeRedis(server=server, decode_responses=True)
    return store


async def test_set_get_roundtrip(fake_redis_store: RedisSessionStore) -> None:
    """SessionState survives serialization to Redis and back."""
    state = _make_state(session_id="sess_rt", phase=SessionPhase.ACTIVE, memory_count=10)
    await fake_redis_store.set_state("sess_rt", state)

    retrieved = await fake_redis_store.get_state("sess_rt")

    assert retrieved is not None
    assert retrieved.session_id == "sess_rt"
    assert retrieved.phase == SessionPhase.ACTIVE
    assert retrieved.memory_count == 10
    assert retrieved.episode_id == "ep_001"


async def test_set_nx_idempotent(fake_redis_store: RedisSessionStore) -> None:
    """set_nx returns True on first call, False on subsequent calls for same session."""
    state = _make_state(session_id="sess_nx")

    first = await fake_redis_store.set_nx("sess_nx", state)
    second = await fake_redis_store.set_nx("sess_nx", state)

    assert first is True
    assert second is False


async def test_ttl_set_on_state(fake_redis_store: RedisSessionStore) -> None:
    """set_state writes a TTL so the key expires automatically."""
    state = _make_state(session_id="sess_ttl")
    await fake_redis_store.set_state("sess_ttl", state)

    redis = fake_redis_store._redis
    key = f"{fake_redis_store._key_prefix}:sess_ttl"
    ttl = await redis.ttl(key)

    # fakeredis returns -1 for no TTL, positive int for remaining seconds
    assert ttl > 0


async def test_delete_state_returns_true_then_false(fake_redis_store: RedisSessionStore) -> None:
    """delete_state returns True when the key existed, False when already gone."""
    state = _make_state(session_id="sess_del")
    await fake_redis_store.set_state("sess_del", state)

    first = await fake_redis_store.delete_state("sess_del")
    second = await fake_redis_store.delete_state("sess_del")

    assert first is True
    assert second is False


async def test_get_state_returns_none_for_missing(fake_redis_store: RedisSessionStore) -> None:
    """get_state returns None for a session that was never written."""
    result = await fake_redis_store.get_state("sess_unknown")
    assert result is None


async def test_all_session_phases_survive_roundtrip(fake_redis_store: RedisSessionStore) -> None:
    """Every SessionPhase enum value serializes and deserializes without loss."""
    for phase in SessionPhase:
        session_id = f"sess_phase_{phase.value}"
        state = SessionState(
            session_id=session_id,
            phase=phase,
            started_at=utc_now(),
        )
        await fake_redis_store.set_state(session_id, state)
        retrieved = await fake_redis_store.get_state(session_id)
        assert retrieved is not None
        assert retrieved.phase == phase


async def test_acquire_lock_returns_true_when_free(fake_redis_store: RedisSessionStore) -> None:
    """acquire_lock yields True when no other holder exists."""
    async with fake_redis_store.acquire_lock("sess_lock_free") as acquired:
        assert acquired is True


async def test_acquire_lock_yields_false_when_held(fake_redis_store: RedisSessionStore) -> None:
    """acquire_lock yields False when another coroutine holds the lock."""
    lock_key = f"{fake_redis_store._key_prefix}:lock:sess_held"
    redis = fake_redis_store._redis
    # Simulate an existing holder by setting the key manually
    await redis.set(lock_key, "holder", ex=30)

    async with fake_redis_store.acquire_lock("sess_held") as acquired:
        assert acquired is False
