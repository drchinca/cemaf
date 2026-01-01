"""
Unit tests for the Memory module.

Tests:
- MemoryItem creation
- InMemoryStore operations
- Scope filtering

Uses fixtures from conftest.py:
- memory_store: Fresh InMemoryStore
- sample_memory_item: Pre-configured MemoryItem
- populated_memory_store: Store with test data
"""

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.memory.base import InMemoryStore, MemoryItem


class TestMemoryItem:
    """Tests for MemoryItem."""

    def test_item_creation(self):
        """MemoryItem can be created."""
        item = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="test_key",
            value={"data": "test"},
        )

        assert item.scope == MemoryScope.PROJECT
        assert item.key == "test_key"
        assert item.value == {"data": "test"}

    def test_full_key_includes_scope(self):
        """full_key includes scope prefix."""
        item = MemoryItem(
            scope=MemoryScope.BRAND,
            key="guidelines",
            value={},
        )

        assert item.full_key == "brand:guidelines"

    def test_with_update_creates_new_item(self):
        """with_update creates new item with updated value."""
        original = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="counter",
            value={"count": 1},
        )

        updated = original.with_update(value={"count": 2})

        # Original unchanged
        assert original.value == {"count": 1}
        # New item has updated value
        assert updated.value == {"count": 2}
        # Keys preserved
        assert updated.key == original.key
        assert updated.scope == original.scope

    def test_item_is_immutable(self):
        """MemoryItem is frozen/immutable."""
        item = MemoryItem(
            scope=MemoryScope.SESSION,
            key="test",
            value={},
        )

        with pytest.raises((TypeError, AttributeError)):
            item.value = {"new": "value"}  # type: ignore


class TestInMemoryStore:
    """Tests for InMemoryStore."""

    @pytest.mark.asyncio
    async def test_set_and_get(self, memory_store: InMemoryStore):
        """Can set and get items."""
        item = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="test",
            value={"data": 123},
        )

        await memory_store.set(item)
        retrieved = await memory_store.get(MemoryScope.PROJECT, "test")

        assert retrieved is not None
        assert retrieved.value == {"data": 123}

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, memory_store: InMemoryStore):
        """Getting nonexistent item returns None."""
        result = await memory_store.get(MemoryScope.PROJECT, "nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_existing(self, memory_store: InMemoryStore):
        """Delete removes existing item."""
        item = MemoryItem(scope=MemoryScope.BRAND, key="to_delete", value={})
        await memory_store.set(item)

        deleted = await memory_store.delete(MemoryScope.BRAND, "to_delete")

        assert deleted is True
        assert await memory_store.get(MemoryScope.BRAND, "to_delete") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, memory_store: InMemoryStore):
        """Delete returns False for nonexistent item."""
        deleted = await memory_store.delete(MemoryScope.BRAND, "nonexistent")

        assert deleted is False

    @pytest.mark.asyncio
    async def test_list_by_scope(self, memory_store: InMemoryStore):
        """Can list items by scope."""
        await memory_store.set(MemoryItem(scope=MemoryScope.BRAND, key="a", value={}))
        await memory_store.set(MemoryItem(scope=MemoryScope.BRAND, key="b", value={}))
        await memory_store.set(MemoryItem(scope=MemoryScope.PROJECT, key="c", value={}))

        brand_items = await memory_store.list_by_scope(MemoryScope.BRAND)

        assert len(brand_items) == 2

    @pytest.mark.asyncio
    async def test_search_by_value(self, memory_store: InMemoryStore):
        """Can search by value content."""
        await memory_store.set(
            MemoryItem(
                scope=MemoryScope.PROJECT,
                key="user_prefs",
                value={"color": "blue", "font": "Arial"},
            )
        )
        await memory_store.set(
            MemoryItem(
                scope=MemoryScope.PROJECT,
                key="other",
                value={"unrelated": "data"},
            )
        )

        results = await memory_store.search("blue")

        assert len(results) == 1
        assert results[0].key == "user_prefs"

    @pytest.mark.asyncio
    async def test_search_with_scope_filter(self, memory_store: InMemoryStore):
        """Search can be filtered by scope."""
        await memory_store.set(
            MemoryItem(
                scope=MemoryScope.BRAND,
                key="brand_blue",
                value={"color": "blue"},
            )
        )
        await memory_store.set(
            MemoryItem(
                scope=MemoryScope.PROJECT,
                key="project_blue",
                value={"color": "blue"},
            )
        )

        results = await memory_store.search("blue", scope=MemoryScope.BRAND)

        assert len(results) == 1
        assert results[0].scope == MemoryScope.BRAND

    @pytest.mark.asyncio
    async def test_clear(self, memory_store: InMemoryStore):
        """Clear removes all items."""
        await memory_store.set(MemoryItem(scope=MemoryScope.SESSION, key="a", value={}))
        await memory_store.set(MemoryItem(scope=MemoryScope.SESSION, key="b", value={}))

        memory_store.clear()

        assert await memory_store.get(MemoryScope.SESSION, "a") is None
        assert await memory_store.get(MemoryScope.SESSION, "b") is None
