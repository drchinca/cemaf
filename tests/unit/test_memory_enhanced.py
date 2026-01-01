"""Tests for enhanced memory store with TTL and hooks."""

import asyncio
from datetime import timedelta

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.core.utils import utc_now
from cemaf.memory.base import InMemoryStore, MemoryItem


class TestMemoryItemTTL:
    """Tests for MemoryItem TTL features."""

    def test_item_without_ttl(self) -> None:
        """Test item without TTL."""
        item = MemoryItem(
            scope=MemoryScope.SESSION,
            key="test",
            value={"data": 1},
        )

        assert item.ttl is None
        assert item.expires_at is None
        assert item.is_expired is False
        assert item.remaining_ttl is None

    def test_item_with_ttl(self) -> None:
        """Test item with TTL."""
        item = MemoryItem(
            scope=MemoryScope.SESSION,
            key="test",
            value={"data": 1},
            ttl=timedelta(hours=1),
        )

        assert item.ttl == timedelta(hours=1)
        assert item.expires_at is not None
        assert item.is_expired is False

        # Should have roughly 1 hour remaining
        remaining = item.remaining_ttl
        assert remaining is not None
        # Allow some tolerance
        assert remaining.total_seconds() > 3500

    def test_with_ttl(self) -> None:
        """Test creating item with new TTL."""
        original = MemoryItem(
            scope=MemoryScope.SESSION,
            key="test",
            value={"data": 1},
        )

        with_ttl = original.with_ttl(timedelta(minutes=30))

        assert with_ttl.ttl == timedelta(minutes=30)
        assert with_ttl.expires_at is not None
        assert with_ttl.value == original.value

    def test_without_expiration(self) -> None:
        """Test removing expiration from item."""
        item = MemoryItem(
            scope=MemoryScope.SESSION,
            key="test",
            value={"data": 1},
            ttl=timedelta(hours=1),
        )

        no_expiry = item.without_expiration()

        assert no_expiry.ttl is None
        assert no_expiry.expires_at is None
        assert no_expiry.is_expired is False

    def test_with_update_preserves_ttl(self) -> None:
        """Test that with_update preserves TTL."""
        item = MemoryItem(
            scope=MemoryScope.SESSION,
            key="test",
            value={"data": 1},
            ttl=timedelta(hours=1),
        )

        updated = item.with_update(value={"data": 2})

        assert updated.ttl == item.ttl
        assert updated.expires_at == item.expires_at


class TestInMemoryStoreHooks:
    """Tests for InMemoryStore hooks."""

    @pytest.mark.asyncio
    async def test_redaction_hook(self) -> None:
        """Test redaction hook on get."""
        store = InMemoryStore()

        # Set redaction hook
        def redact(item: MemoryItem) -> MemoryItem:
            value = dict(item.value)
            if "secret" in value:
                value["secret"] = "***REDACTED***"
            return MemoryItem(
                scope=item.scope,
                key=item.key,
                value=value,
                confidence=item.confidence,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )

        store.set_redaction_hook(redact)

        # Store item with secret
        await store.set(
            MemoryItem(
                scope=MemoryScope.SESSION,
                key="credentials",
                value={"username": "admin", "secret": "test_secret_placeholder"},
            )
        )

        # Get should return redacted
        item = await store.get(MemoryScope.SESSION, "credentials")
        assert item is not None
        assert item.value["username"] == "admin"
        assert item.value["secret"] == "***REDACTED***"

    @pytest.mark.asyncio
    async def test_serialization_hook(self) -> None:
        """Test serialization hook."""
        store = InMemoryStore()

        # Set serialization hook
        def serialize(item: MemoryItem) -> dict:
            return {
                "key": item.full_key,
                "value": item.value,
                "age_seconds": (utc_now() - item.created_at).total_seconds(),
            }

        store.set_serialization_hook(serialize)

        # Store item
        item = MemoryItem(
            scope=MemoryScope.SESSION,
            key="test",
            value={"data": 1},
        )
        await store.set(item)

        # Serialize using hook
        data = store.serialize_item(item)
        assert data["key"] == "session:test"
        assert data["value"] == {"data": 1}
        assert "age_seconds" in data

    @pytest.mark.asyncio
    async def test_clear_hooks(self) -> None:
        """Test clearing hooks."""
        store = InMemoryStore()

        # Set hook
        store.set_redaction_hook(lambda x: x)

        # Clear hook
        store.set_redaction_hook(None)

        # Store and get - should work without hook
        await store.set(
            MemoryItem(
                scope=MemoryScope.SESSION,
                key="test",
                value={"data": 1},
            )
        )

        item = await store.get(MemoryScope.SESSION, "test")
        assert item is not None


class TestInMemoryStoreTTL:
    """Tests for InMemoryStore TTL handling."""

    @pytest.mark.asyncio
    async def test_expired_items_not_returned(self) -> None:
        """Test that expired items are not returned on get."""
        store = InMemoryStore()

        # Create item that expires immediately (negative ttl trick)
        # We'll use a very short TTL and wait
        item = MemoryItem(
            scope=MemoryScope.SESSION,
            key="test",
            value={"data": 1},
            ttl=timedelta(milliseconds=1),
        )
        await store.set(item)

        # Wait for expiration
        await asyncio.sleep(0.01)

        # Should return None
        result = await store.get(MemoryScope.SESSION, "test")
        assert result is None

    @pytest.mark.asyncio
    async def test_non_expired_items_returned(self) -> None:
        """Test that non-expired items are returned."""
        store = InMemoryStore()

        item = MemoryItem(
            scope=MemoryScope.SESSION,
            key="test",
            value={"data": 1},
            ttl=timedelta(hours=1),
        )
        await store.set(item)

        result = await store.get(MemoryScope.SESSION, "test")
        assert result is not None
        assert result.value == {"data": 1}

    @pytest.mark.asyncio
    async def test_list_by_scope_excludes_expired(self) -> None:
        """Test that list_by_scope excludes expired items."""
        store = InMemoryStore()

        # Add one expired item
        expired_item = MemoryItem(
            scope=MemoryScope.SESSION,
            key="expired",
            value={"data": 1},
            ttl=timedelta(milliseconds=1),
        )
        await store.set(expired_item)

        # Add one non-expired item
        valid_item = MemoryItem(
            scope=MemoryScope.SESSION,
            key="valid",
            value={"data": 2},
            ttl=timedelta(hours=1),
        )
        await store.set(valid_item)

        # Wait for expiration
        await asyncio.sleep(0.01)

        items = await store.list_by_scope(MemoryScope.SESSION)
        assert len(items) == 1
        assert items[0].key == "valid"

    @pytest.mark.asyncio
    async def test_cleanup_expired(self) -> None:
        """Test cleanup_expired method."""
        store = InMemoryStore()

        # Add expired items
        for i in range(3):
            await store.set(
                MemoryItem(
                    scope=MemoryScope.SESSION,
                    key=f"expired_{i}",
                    value={"data": i},
                    ttl=timedelta(milliseconds=1),
                )
            )

        # Add non-expired items
        for i in range(2):
            await store.set(
                MemoryItem(
                    scope=MemoryScope.SESSION,
                    key=f"valid_{i}",
                    value={"data": i},
                    ttl=timedelta(hours=1),
                )
            )

        # Wait for expiration
        await asyncio.sleep(0.01)

        # Run cleanup
        removed = await store.cleanup_expired()

        assert removed == 3

        # Check remaining items
        items = await store.list_by_scope(MemoryScope.SESSION)
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_get_all_expired(self) -> None:
        """Test get_all_expired method."""
        store = InMemoryStore()

        # Add expired item
        await store.set(
            MemoryItem(
                scope=MemoryScope.SESSION,
                key="expired",
                value={"data": 1},
                ttl=timedelta(milliseconds=1),
            )
        )

        # Add non-expired item
        await store.set(
            MemoryItem(
                scope=MemoryScope.SESSION,
                key="valid",
                value={"data": 2},
                ttl=timedelta(hours=1),
            )
        )

        # Wait for expiration
        await asyncio.sleep(0.01)

        expired = await store.get_all_expired()
        assert len(expired) == 1
        assert expired[0].key == "expired"


class TestInMemoryStoreSearch:
    """Tests for InMemoryStore search with TTL."""

    @pytest.mark.asyncio
    async def test_search_excludes_expired(self) -> None:
        """Test that search excludes expired items."""
        store = InMemoryStore()

        # Add expired item
        await store.set(
            MemoryItem(
                scope=MemoryScope.SESSION,
                key="expired",
                value={"search": "term"},
                ttl=timedelta(milliseconds=1),
            )
        )

        # Add non-expired item
        await store.set(
            MemoryItem(
                scope=MemoryScope.SESSION,
                key="valid",
                value={"search": "term"},
                ttl=timedelta(hours=1),
            )
        )

        # Wait for expiration
        await asyncio.sleep(0.01)

        results = await store.search("term")
        assert len(results) == 1
        assert results[0].key == "valid"

    @pytest.mark.asyncio
    async def test_search_with_redaction_hook(self) -> None:
        """Test that search applies redaction hook."""
        store = InMemoryStore()

        def redact(item: MemoryItem) -> MemoryItem:
            return MemoryItem(
                scope=item.scope,
                key=item.key,
                value={"redacted": True},
                confidence=item.confidence,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )

        store.set_redaction_hook(redact)

        await store.set(
            MemoryItem(
                scope=MemoryScope.SESSION,
                key="test",
                value={"data": "searchable"},
            )
        )

        results = await store.search("data")
        assert len(results) == 1
        assert results[0].value == {"redacted": True}
