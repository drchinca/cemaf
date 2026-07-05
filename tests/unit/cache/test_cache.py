"""Tests for cache module."""

import asyncio
from datetime import timedelta
from typing import get_args

import pytest

from cemaf.cache.decorators import cache_key, cached
from cemaf.cache.factories import cache_registry, create_cache, create_cache_from_config
from cemaf.cache.mock import MockCache
from cemaf.cache.protocols import CacheEntry, CacheStats
from cemaf.cache.stores import InMemoryCache, TTLCache
from cemaf.config.protocols import CacheSettings, Settings
from cemaf.core.utils import utc_now

# =============================================================================
# CacheEntry Tests
# =============================================================================


class TestCacheEntry:
    """Tests for CacheEntry."""

    def test_create_entry(self) -> None:
        """Test creating a cache entry."""
        entry = CacheEntry(
            key="test",
            value="value",
            created_at=utc_now(),
        )
        assert entry.key == "test"
        assert entry.value == "value"
        assert entry.hit_count == 0

    def test_entry_not_expired(self) -> None:
        """Test entry without expiry is not expired."""
        entry = CacheEntry(
            key="test",
            value="value",
            created_at=utc_now(),
            expires_at=None,
        )
        assert entry.is_expired is False

    def test_entry_expired(self) -> None:
        """Test entry with past expiry is expired."""
        entry = CacheEntry(
            key="test",
            value="value",
            created_at=utc_now() - timedelta(hours=1),
            expires_at=utc_now() - timedelta(minutes=1),
        )
        assert entry.is_expired is True

    def test_entry_not_yet_expired(self) -> None:
        """Test entry with future expiry is not expired."""
        entry = CacheEntry(
            key="test",
            value="value",
            created_at=utc_now(),
            expires_at=utc_now() + timedelta(hours=1),
        )
        assert entry.is_expired is False

    def test_with_hit_increments(self) -> None:
        """Test with_hit creates new entry with incremented count."""
        entry = CacheEntry(
            key="test",
            value="value",
            created_at=utc_now(),
            hit_count=5,
        )
        updated = entry.with_hit()
        assert updated.hit_count == 6
        assert entry.hit_count == 5  # Original unchanged


# =============================================================================
# CacheStats Tests
# =============================================================================


class TestCacheStats:
    """Tests for CacheStats."""

    def test_hit_rate_zero_total(self) -> None:
        """Test hit rate with no requests."""
        stats = CacheStats()
        assert stats.hit_rate == 0.0

    def test_hit_rate_all_hits(self) -> None:
        """Test hit rate with all hits."""
        stats = CacheStats(hits=10, misses=0)
        assert stats.hit_rate == 100.0

    def test_hit_rate_all_misses(self) -> None:
        """Test hit rate with all misses."""
        stats = CacheStats(hits=0, misses=10)
        assert stats.hit_rate == 0.0

    def test_hit_rate_mixed(self) -> None:
        """Test hit rate with mixed results."""
        stats = CacheStats(hits=7, misses=3)
        assert stats.hit_rate == 70.0


# =============================================================================
# InMemoryCache Tests
# =============================================================================


class TestInMemoryCache:
    """Tests for InMemoryCache."""

    async def test_get_nonexistent(self) -> None:
        """Test getting non-existent key."""
        cache = InMemoryCache()
        result = await cache.get("nonexistent")
        assert result is None

    async def test_set_and_get(self) -> None:
        """Test setting and getting a value."""
        cache = InMemoryCache()
        await cache.set("key", "value")
        result = await cache.get("key")
        assert result == "value"

    async def test_get_entry(self) -> None:
        """Test getting entry with metadata."""
        cache = InMemoryCache()
        await cache.set("key", "value", metadata={"custom": "data"})
        entry = await cache.get_entry("key")
        assert entry is not None
        assert entry.value == "value"
        assert entry.metadata == {"custom": "data"}

    async def test_delete(self) -> None:
        """Test deleting a key."""
        cache = InMemoryCache()
        await cache.set("key", "value")

        result = await cache.delete("key")
        assert result is True

        value = await cache.get("key")
        assert value is None

    async def test_delete_nonexistent(self) -> None:
        """Test deleting non-existent key."""
        cache = InMemoryCache()
        result = await cache.delete("nonexistent")
        assert result is False

    async def test_clear(self) -> None:
        """Test clearing all entries."""
        cache = InMemoryCache()
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")

        await cache.clear()

        assert await cache.get("key1") is None
        assert await cache.get("key2") is None

    async def test_exists(self) -> None:
        """Test existence check."""
        cache = InMemoryCache()
        await cache.set("key", "value")

        assert await cache.exists("key") is True
        assert await cache.exists("nonexistent") is False

    async def test_ttl_expiry(self) -> None:
        """Test TTL expiration."""
        cache = InMemoryCache()
        await cache.set("key", "value", ttl_seconds=0)  # Immediate expiry

        # Small delay to ensure expiry
        await asyncio.sleep(0.01)

        result = await cache.get("key")
        assert result is None

    async def test_max_size_eviction(self) -> None:
        """Test max size eviction."""
        cache = InMemoryCache(max_size=2)
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.set("key3", "value3")

        # One of the first two should be evicted
        stats = await cache.stats()
        assert stats.size == 2
        assert stats.evictions == 1

    async def test_stats_tracking(self) -> None:
        """Test statistics tracking."""
        cache = InMemoryCache()
        await cache.set("key", "value")

        await cache.get("key")  # Hit
        await cache.get("key")  # Hit
        await cache.get("nonexistent")  # Miss

        stats = await cache.stats()
        assert stats.hits == 2
        assert stats.misses == 1
        assert stats.size == 1


# =============================================================================
# TTLCache Tests
# =============================================================================


class TestTTLCache:
    """Tests for TTLCache."""

    async def test_default_ttl(self) -> None:
        """Test that entries get default TTL."""
        cache = TTLCache(default_ttl_seconds=3600)
        await cache.set("key", "value")

        entry = await cache.get_entry("key")
        assert entry is not None
        assert entry.expires_at is not None

    async def test_override_ttl(self) -> None:
        """Test overriding default TTL."""
        cache = TTLCache(default_ttl_seconds=3600)
        await cache.set("key", "value", ttl_seconds=1)

        entry = await cache.get_entry("key")
        assert entry is not None
        # Entry should expire much sooner than default


# =============================================================================
# Cache Factory Tests
# =============================================================================


class TestCacheFactories:
    """Tests for registry-backed cache factories."""

    def test_configured_cache_backends_are_registered(self) -> None:
        backend_annotation = CacheSettings.model_fields["backend"].annotation
        configured = set(get_args(backend_annotation))

        assert configured == {"memory", "ttl"}
        assert all(cache_registry.has(backend=backend) for backend in configured)

    def test_create_cache_defaults_to_in_memory_backend(self) -> None:
        cache = create_cache()

        assert isinstance(cache, InMemoryCache)

    def test_create_cache_builds_ttl_backend(self) -> None:
        cache = create_cache(backend="ttl", max_size=10, ttl_seconds=5)

        assert isinstance(cache, TTLCache)

    def test_create_cache_supports_custom_registered_backend(self) -> None:
        created: dict[str, object] = {}

        def _factory(**kwargs):
            created["args"] = kwargs
            return MockCache(default_return="custom")

        cache_registry.register(backend="custom-test-cache", factory=_factory)

        cache = create_cache(
            backend="custom-test-cache",
            max_size=123,
            ttl_seconds=45,
            custom_option=True,
        )

        assert isinstance(cache, MockCache)
        assert created["args"] == {
            "max_size": 123,
            "ttl_seconds": 45,
            "custom_option": True,
        }

    def test_create_cache_supports_registered_redis_backend(self) -> None:
        created: dict[str, object] = {}

        def _factory(**kwargs):
            created["args"] = kwargs
            return MockCache(default_return="redis")

        cache_registry.register(backend="redis", factory=_factory)

        cache = create_cache(
            backend="redis",
            max_size=321,
            ttl_seconds=7.0,
        )

        assert isinstance(cache, MockCache)
        assert created["args"] == {
            "max_size": 321,
            "ttl_seconds": 7.0,
        }

    def test_create_cache_from_config_uses_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CEMAF_CACHE_BACKEND", raising=False)
        monkeypatch.delenv("CEMAF_CACHE_MAX_SIZE", raising=False)
        monkeypatch.delenv("CEMAF_CACHE_DEFAULT_TTL_SECONDS", raising=False)
        settings = Settings(
            cache=CacheSettings(
                backend="ttl",
                max_size=17,
                default_ttl_seconds=23,
            )
        )

        cache = create_cache_from_config(settings=settings)

        assert isinstance(cache, TTLCache)
        assert cache._max_size == 17
        assert cache._default_ttl == 23

    def test_unsupported_cache_backend_mentions_registry(self) -> None:
        with pytest.raises(ValueError, match="cache_registry.register"):
            create_cache(backend="missing-cache")


# =============================================================================
# cache_key Function Tests
# =============================================================================


class TestCacheKey:
    """Tests for cache_key function."""

    def test_simple_args(self) -> None:
        """Test key generation with simple args."""
        key1 = cache_key("arg1", "arg2")
        key2 = cache_key("arg1", "arg2")
        assert key1 == key2

    def test_different_args_different_keys(self) -> None:
        """Test different args produce different keys."""
        key1 = cache_key("arg1")
        key2 = cache_key("arg2")
        assert key1 != key2

    def test_kwargs_included(self) -> None:
        """Test kwargs affect the key."""
        key1 = cache_key("arg", kwarg="value1")
        key2 = cache_key("arg", kwarg="value2")
        assert key1 != key2

    def test_order_independent_kwargs(self) -> None:
        """Test kwargs order doesn't affect key."""
        key1 = cache_key(a=1, b=2)
        key2 = cache_key(b=2, a=1)
        assert key1 == key2

    def test_complex_types(self) -> None:
        """Test with complex types."""
        key1 = cache_key([1, 2, 3], {"nested": "dict"})
        key2 = cache_key([1, 2, 3], {"nested": "dict"})
        assert key1 == key2


# =============================================================================
# @cached Decorator Tests
# =============================================================================


class TestCachedDecorator:
    """Tests for @cached decorator."""

    async def test_caches_result(self) -> None:
        """Test that results are cached."""
        cache = InMemoryCache()
        call_count = 0

        @cached(cache=cache)
        async def expensive_fn(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2

        result1 = await expensive_fn(5)
        result2 = await expensive_fn(5)

        assert result1 == 10
        assert result2 == 10
        assert call_count == 1  # Only called once

    async def test_different_args_not_cached(self) -> None:
        """Test different args are computed separately."""
        cache = InMemoryCache()
        call_count = 0

        @cached(cache=cache)
        async def fn(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x

        await fn(1)
        await fn(2)

        assert call_count == 2

    async def test_ttl_respected(self) -> None:
        """Test TTL is applied to cached values."""
        cache = InMemoryCache()

        @cached(cache=cache, ttl_seconds=0)
        async def fn() -> str:
            return "value"

        await fn()
        await asyncio.sleep(0.01)

        # Should be expired, will compute again
        entry = await cache.get_entry("fn:" + cache_key())
        assert entry is None or entry.is_expired

    async def test_key_prefix(self) -> None:
        """Test key prefix is applied."""
        cache = InMemoryCache()

        @cached(cache=cache, key_prefix="myprefix")
        async def fn() -> str:
            return "value"

        await fn()
        assert await cache.exists("myprefix:" + cache_key())

    async def test_custom_key_fn(self) -> None:
        """Test custom key function."""
        cache = InMemoryCache()

        @cached(cache=cache, key_fn=lambda x: f"custom_{x}")
        async def fn(x: int) -> int:
            return x

        await fn(5)
        assert await cache.exists("fn:custom_5")


# =============================================================================
# MockCache Tests
# =============================================================================


class TestMockCache:
    """Tests for MockCache."""

    async def test_records_operations(self) -> None:
        """Test mock records all operations."""
        cache = MockCache()

        await cache.set("key", "value")
        await cache.get("key")
        await cache.delete("key")

        assert len(cache.operations) == 3
        assert cache.operations[0] == ("set", "key", "value")
        assert cache.operations[1] == ("get", "key", None)
        assert cache.operations[2] == ("delete", "key", None)

    async def test_get_calls_property(self) -> None:
        """Test get_calls helper property."""
        cache = MockCache()
        await cache.get("key1")
        await cache.get("key2")

        assert cache.get_calls == ["key1", "key2"]

    async def test_set_calls_property(self) -> None:
        """Test set_calls helper property."""
        cache = MockCache()
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")

        assert cache.set_calls == [("key1", "value1"), ("key2", "value2")]

    async def test_preload(self) -> None:
        """Test preloading values."""
        cache = MockCache()
        cache.preload("key", "preloaded")

        result = await cache.get("key")
        assert result == "preloaded"

        # Preload shouldn't be in operations
        assert len([op for op in cache.operations if op[0] == "set"]) == 0

    async def test_reset(self) -> None:
        """Test reset clears state."""
        cache = MockCache()
        await cache.set("key", "value")
        cache.reset()

        assert len(cache.operations) == 0
        assert await cache.get("key") is None
