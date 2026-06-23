"""Integration tests for previously untested cross-module seams.

Covers four required integrations from CLAUDE.md:
1. MemoryManager + EventBus — remember publishes events
2. ResilientLLMClient full stack — retry + circuit breaker + rate limiter
3. StructuredLogger JSON output — valid JSON lines with correct fields
4. SqliteMemoryStore round-trip — set/get/list_by_scope/cleanup_expired
"""

from __future__ import annotations

import io
import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.core.types import Confidence, TokenCount
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType
from cemaf.llm.protocols import CompletionResult, LLMConfig, Message, MessageRole
from cemaf.llm.resilient import ResilientLLMClient
from cemaf.memory.base import InMemoryStore, MemoryItem
from cemaf.memory.episodic import InMemoryEpisodicStore
from cemaf.memory.manager import DefaultMemoryManager
from cemaf.memory.scoring import TemporalDecayScorer
from cemaf.memory.semantic import DefaultSemanticMemoryStore
from cemaf.memory.sqlite_store import SqliteMemoryStore
from cemaf.observability.structured import StructuredLogger
from cemaf.resilience.circuit_breaker import CircuitBreaker, CircuitConfig
from cemaf.resilience.rate_limiter import RateLimitConfig, RateLimiter
from cemaf.resilience.retry import RetryConfig, RetryPolicy
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wire_memory_manager_with_event_bus() -> tuple[DefaultMemoryManager, InMemoryEventBus]:
    """Wire a real DefaultMemoryManager backed by InMemoryStore + InMemoryEventBus."""
    store = InMemoryStore()
    embedding_provider = MockEmbeddingProvider()
    scorer = TemporalDecayScorer()
    semantic_store = DefaultSemanticMemoryStore(
        memory_store=store,
        vector_store=InMemoryVectorStore(embedding_provider=embedding_provider),
        embedding_provider=embedding_provider,
        scorer=scorer,
    )
    episodic_store = InMemoryEpisodicStore()
    event_bus = InMemoryEventBus()
    manager = DefaultMemoryManager(
        semantic_store=semantic_store,
        episodic_store=episodic_store,
        event_bus=event_bus,
    )
    return manager, event_bus


def _make_mock_llm_client(*, side_effect: object = None) -> AsyncMock:
    """Create a mock LLMClient with correct protocol surface."""
    client = AsyncMock()
    client.config = LLMConfig(model="test-model")
    if side_effect is not None:
        client.complete = AsyncMock(side_effect=side_effect)
    else:
        client.complete = AsyncMock(
            return_value=CompletionResult.ok(
                message=Message(role=MessageRole.ASSISTANT, content="ok"),
                model="test-model",
                prompt_tokens=10,
                completion_tokens=5,
            ),
        )
    client.stream = AsyncMock()
    client.count_tokens = MagicMock(return_value=TokenCount(10))
    client.count_messages_tokens = MagicMock(return_value=TokenCount(20))
    return client


# ---------------------------------------------------------------------------
# 1. MemoryManager + EventBus
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_manager_publishes_event_on_remember() -> None:
    """Storing a memory item via DefaultMemoryManager emits MEMORY_ITEM_SET on EventBus."""
    manager, event_bus = _wire_memory_manager_with_event_bus()

    received_events: list[Event] = []
    event_bus.subscribe(
        event_type=EventType.MEMORY_ITEM_SET,
        handler=lambda e: received_events.append(e),
    )

    await manager.remember(
        scope=MemoryScope.PROJECT,
        key="test-fact",
        value={"insight": "integration tests matter"},
        confidence=0.95,
    )

    assert len(received_events) == 1
    event = received_events[0]
    assert event.type == EventType.MEMORY_ITEM_SET.value
    assert event.payload["scope"] == MemoryScope.PROJECT.value
    assert event.payload["key"] == "test-fact"
    assert event.source == "memory_manager"

    # Verify the item was actually stored (not just event fired)
    recalled = await manager.recall_by_key(
        scope=MemoryScope.PROJECT,
        key="test-fact",
    )
    assert recalled is not None
    assert recalled.value == {"insight": "integration tests matter"}


@pytest.mark.asyncio
async def test_memory_manager_publishes_cleanup_event() -> None:
    """Cleanup emits MEMORY_CLEANUP event with removed count."""
    manager, event_bus = _wire_memory_manager_with_event_bus()

    received_events: list[Event] = []
    event_bus.subscribe(
        event_type=EventType.MEMORY_CLEANUP,
        handler=lambda e: received_events.append(e),
    )

    removed = await manager.cleanup()

    assert len(received_events) == 1
    assert received_events[0].payload["removed"] == removed


# ---------------------------------------------------------------------------
# 2. ResilientLLMClient full stack
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resilient_client_retry_circuit_breaker_rate_limiter() -> None:
    """Wire all three resilience layers and verify retries recover from transient failures."""
    call_count = 0

    async def _fail_twice_then_succeed(**kwargs: object) -> CompletionResult:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("transient network error")
        return CompletionResult.ok(
            message=Message(role=MessageRole.ASSISTANT, content="recovered"),
            model="test-model",
            prompt_tokens=10,
            completion_tokens=5,
        )

    inner = _make_mock_llm_client(side_effect=_fail_twice_then_succeed)

    retry = RetryPolicy(
        config=RetryConfig(
            max_attempts=3,
            initial_delay_seconds=0.01,
            jitter=False,
        ),
    )
    circuit_breaker = CircuitBreaker(
        config=CircuitConfig(failure_threshold=10),
    )
    rate_limiter = RateLimiter(
        config=RateLimitConfig(rate=1000.0, burst=1000),
    )

    resilient = ResilientLLMClient(
        client=inner,
        retry=retry,
        circuit_breaker=circuit_breaker,
        rate_limiter=rate_limiter,
    )

    result = await resilient.complete(messages=[Message.user(content="hello")])

    assert result.success is True
    assert result.content == "recovered"
    assert call_count == 3  # 2 failures + 1 success


@pytest.mark.asyncio
async def test_resilient_client_circuit_opens_after_threshold() -> None:
    """Circuit breaker opens after threshold failures, preventing further calls."""
    inner = _make_mock_llm_client(
        side_effect=ConnectionError("persistent failure"),
    )

    circuit_breaker = CircuitBreaker(
        config=CircuitConfig(failure_threshold=3),
    )
    resilient = ResilientLLMClient(
        client=inner,
        circuit_breaker=circuit_breaker,
    )

    # Trip the circuit with 3 failures
    for _ in range(3):
        result = await resilient.complete(messages=[Message.user(content="hi")])
        assert result.success is False

    # Circuit is now open -- next call fails immediately without hitting inner client
    result = await resilient.complete(messages=[Message.user(content="hi")])
    assert result.success is False
    assert "Circuit breaker open" in (result.error or "")


# ---------------------------------------------------------------------------
# 3. StructuredLogger JSON output
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_structured_logger_emits_valid_json() -> None:
    """StructuredLogger writes valid JSON lines with required fields."""
    buffer = io.StringIO()
    logger = StructuredLogger(name="test-logger", context={"env": "test"})
    logger._stream = buffer  # Redirect output to buffer

    logger.info("User %s logged in", "alice", request_id="req-123")
    logger.warning("Slow query detected", duration_ms=450)

    lines = buffer.getvalue().strip().split("\n")
    assert len(lines) == 2

    # Validate first line (info)
    record_info = json.loads(lines[0])
    assert record_info["level"] == "INFO"
    assert record_info["logger"] == "test-logger"
    assert record_info["message"] == "User alice logged in"
    assert record_info["env"] == "test"
    assert record_info["request_id"] == "req-123"
    assert "timestamp" in record_info

    # Validate second line (warning)
    record_warn = json.loads(lines[1])
    assert record_warn["level"] == "WARNING"
    assert record_warn["duration_ms"] == 450


@pytest.mark.asyncio
async def test_structured_logger_with_context_merges_fields() -> None:
    """with_context returns a new logger that merges context fields."""
    buffer = io.StringIO()
    base_logger = StructuredLogger(name="base", context={"service": "cemaf"})
    child_logger = base_logger.with_context(run_id="run-42")
    child_logger._stream = buffer

    child_logger.info("Processing started")

    record = json.loads(buffer.getvalue().strip())
    assert record["service"] == "cemaf"
    assert record["run_id"] == "run-42"
    assert record["message"] == "Processing started"


# ---------------------------------------------------------------------------
# 4. SqliteMemoryStore round-trip
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_db_path(tmp_path: Path) -> str:
    """Provide a temporary file path for SqliteMemoryStore."""
    return str(tmp_path / "test_memory.db")


@pytest.mark.asyncio
async def test_sqlite_store_set_get_round_trip(sqlite_db_path: str) -> None:
    """Store an item and retrieve it by scope+key."""
    store = SqliteMemoryStore(db_path=sqlite_db_path)
    try:
        item = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="architecture-decision",
            value={"decision": "use protocols over ABCs"},
            confidence=Confidence(0.95),
        )
        await store.set(item=item)

        retrieved = await store.get(scope=MemoryScope.PROJECT, key="architecture-decision")
        assert retrieved is not None
        assert retrieved.scope == MemoryScope.PROJECT
        assert retrieved.key == "architecture-decision"
        assert retrieved.value == {"decision": "use protocols over ABCs"}
        assert float(retrieved.confidence) == pytest.approx(0.95)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_sqlite_store_list_by_scope(sqlite_db_path: str) -> None:
    """list_by_scope returns all non-expired items in the given scope."""
    store = SqliteMemoryStore(db_path=sqlite_db_path)
    try:
        items = [
            MemoryItem(scope=MemoryScope.PROJECT, key="fact-1", value={"data": "a"}),
            MemoryItem(scope=MemoryScope.PROJECT, key="fact-2", value={"data": "b"}),
            MemoryItem(scope=MemoryScope.SESSION, key="temp-1", value={"data": "c"}),
        ]
        for item in items:
            await store.set(item=item)

        project_items = await store.list_by_scope(scope=MemoryScope.PROJECT)
        assert len(project_items) == 2
        keys = {item.key for item in project_items}
        assert keys == {"fact-1", "fact-2"}

        session_items = await store.list_by_scope(scope=MemoryScope.SESSION)
        assert len(session_items) == 1
        assert session_items[0].key == "temp-1"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_sqlite_store_cleanup_expired(sqlite_db_path: str) -> None:
    """cleanup_expired removes items past their expiration time."""
    store = SqliteMemoryStore(db_path=sqlite_db_path)
    try:
        # Store an already-expired item (TTL in the past)
        expired_item = MemoryItem(
            scope=MemoryScope.SESSION,
            key="ephemeral",
            value={"temp": True},
            ttl=timedelta(seconds=-1),  # Already expired
        )
        await store.set(item=expired_item)

        # Store a non-expiring item
        permanent_item = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="permanent",
            value={"keep": True},
        )
        await store.set(item=permanent_item)

        removed = await store.cleanup_expired()
        assert removed == 1

        # Expired item is gone
        assert await store.get(scope=MemoryScope.SESSION, key="ephemeral") is None

        # Permanent item survives
        assert await store.get(scope=MemoryScope.PROJECT, key="permanent") is not None
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_sqlite_store_delete(sqlite_db_path: str) -> None:
    """Delete removes an item and returns True; missing key returns False."""
    store = SqliteMemoryStore(db_path=sqlite_db_path)
    try:
        item = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="to-delete",
            value={"disposable": True},
        )
        await store.set(item=item)

        assert await store.delete(scope=MemoryScope.PROJECT, key="to-delete") is True
        assert await store.get(scope=MemoryScope.PROJECT, key="to-delete") is None
        assert await store.delete(scope=MemoryScope.PROJECT, key="to-delete") is False
    finally:
        await store.close()
