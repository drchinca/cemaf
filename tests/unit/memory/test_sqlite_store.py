"""Tests for SqliteMemoryStore."""

import pytest

aiosqlite = pytest.importorskip("aiosqlite")

from datetime import timedelta

from cemaf.core.enums import MemoryScope
from cemaf.core.types import Confidence
from cemaf.core.utils import utc_now
from cemaf.memory.base import MemoryItem
from cemaf.memory.sqlite_store import SqliteMemoryStore


def _make_item(
    *,
    scope: MemoryScope = MemoryScope.TENANT,
    key: str = "test_key",
    value: dict | None = None,
    confidence: float = 0.9,
    ttl: timedelta | None = None,
    expires_at=None,
    scope_path: str | None = None,
) -> MemoryItem:
    return MemoryItem(
        scope=scope,
        key=key,
        value=value or {"data": "hello"},
        confidence=Confidence(confidence),
        ttl=ttl,
        expires_at=expires_at,
        scope_path=scope_path,
    )


@pytest.fixture
def db_path(tmp_path: object) -> str:
    return str(tmp_path / "test_memory.db")  # type: ignore[operator]


async def test_get_set_roundtrip(db_path: str) -> None:
    """Store and retrieve an item with all fields intact."""
    store = SqliteMemoryStore(db_path=db_path)
    item = _make_item(key="roundtrip", value={"nested": {"a": 1}}, confidence=0.75)

    await store.set(item=item)
    retrieved = await store.get(scope=MemoryScope.TENANT, key="roundtrip")

    assert retrieved is not None
    assert retrieved.key == "roundtrip"
    assert retrieved.value == {"nested": {"a": 1}}
    assert float(retrieved.confidence) == pytest.approx(0.75)
    assert retrieved.scope == MemoryScope.TENANT


async def test_get_missing_returns_none(db_path: str) -> None:
    """Get on a non-existent key returns None."""
    store = SqliteMemoryStore(db_path=db_path)
    result = await store.get(scope=MemoryScope.TENANT, key="nonexistent")
    assert result is None


async def test_set_overwrites_existing(db_path: str) -> None:
    """Setting the same scope+key replaces the item."""
    store = SqliteMemoryStore(db_path=db_path)
    await store.set(item=_make_item(key="dup", value={"v": 1}))
    await store.set(item=_make_item(key="dup", value={"v": 2}))

    retrieved = await store.get(scope=MemoryScope.TENANT, key="dup")
    assert retrieved is not None
    assert retrieved.value == {"v": 2}


async def test_delete_existing(db_path: str) -> None:
    """Delete returns True for existing items and removes them."""
    store = SqliteMemoryStore(db_path=db_path)
    await store.set(item=_make_item(key="to_delete"))

    assert await store.delete(scope=MemoryScope.TENANT, key="to_delete") is True
    assert await store.get(scope=MemoryScope.TENANT, key="to_delete") is None


async def test_delete_nonexistent(db_path: str) -> None:
    """Delete returns False for non-existent items."""
    store = SqliteMemoryStore(db_path=db_path)
    assert await store.delete(scope=MemoryScope.TENANT, key="nope") is False


async def test_list_by_scope(db_path: str) -> None:
    """List returns only items matching the requested scope."""
    store = SqliteMemoryStore(db_path=db_path)
    await store.set(item=_make_item(scope=MemoryScope.TENANT, key="b1"))
    await store.set(item=_make_item(scope=MemoryScope.TENANT, key="b2"))
    await store.set(item=_make_item(scope=MemoryScope.PROJECT, key="p1"))

    brand_items = await store.list_by_scope(scope=MemoryScope.TENANT)
    project_items = await store.list_by_scope(scope=MemoryScope.PROJECT)

    assert len(brand_items) == 2
    assert len(project_items) == 1
    assert {item.key for item in brand_items} == {"b1", "b2"}


async def test_cleanup_expired(db_path: str) -> None:
    """Cleanup removes expired items and returns count."""
    store = SqliteMemoryStore(db_path=db_path)
    # Already-expired item
    past = utc_now() - timedelta(hours=1)
    expired_item = MemoryItem(
        scope=MemoryScope.TENANT,
        key="expired",
        value={"gone": True},
        confidence=Confidence(0.5),
        created_at=past - timedelta(hours=2),
        updated_at=past - timedelta(hours=2),
        ttl=timedelta(hours=1),
        expires_at=past,
    )
    alive_item = _make_item(key="alive")

    await store.set(item=expired_item)
    await store.set(item=alive_item)

    removed = await store.cleanup_expired()
    assert removed == 1

    # Expired item gone, alive item still there
    assert await store.get(scope=MemoryScope.TENANT, key="expired") is None
    assert await store.get(scope=MemoryScope.TENANT, key="alive") is not None


async def test_list_by_scope_excludes_expired(db_path: str) -> None:
    """list_by_scope does not return expired items."""
    store = SqliteMemoryStore(db_path=db_path)
    past = utc_now() - timedelta(hours=1)
    expired_item = MemoryItem(
        scope=MemoryScope.TENANT,
        key="old",
        value={"stale": True},
        confidence=Confidence(0.5),
        created_at=past - timedelta(hours=2),
        updated_at=past - timedelta(hours=2),
        expires_at=past,
    )
    await store.set(item=expired_item)
    await store.set(item=_make_item(key="fresh"))

    items = await store.list_by_scope(scope=MemoryScope.TENANT)
    assert len(items) == 1
    assert items[0].key == "fresh"


async def test_persistence_across_instances(db_path: str) -> None:
    """Data survives closing and reopening a new store instance."""
    store1 = SqliteMemoryStore(db_path=db_path)
    await store1.set(item=_make_item(key="persistent", value={"survives": True}))

    # New instance, same db path
    store2 = SqliteMemoryStore(db_path=db_path)
    retrieved = await store2.get(scope=MemoryScope.TENANT, key="persistent")

    assert retrieved is not None
    assert retrieved.value == {"survives": True}


async def test_scope_path_preserved(db_path: str) -> None:
    """scope_path field roundtrips through SQLite."""
    store = SqliteMemoryStore(db_path=db_path)
    item = _make_item(key="pathed", scope_path="project/campaign/assets")
    await store.set(item=item)

    retrieved = await store.get(scope=MemoryScope.TENANT, key="pathed")
    assert retrieved is not None
    assert retrieved.scope_path == "project/campaign/assets"


async def test_scope_path_none_preserved(db_path: str) -> None:
    """scope_path=None roundtrips correctly."""
    store = SqliteMemoryStore(db_path=db_path)
    item = _make_item(key="no_path", scope_path=None)
    await store.set(item=item)

    retrieved = await store.get(scope=MemoryScope.TENANT, key="no_path")
    assert retrieved is not None
    assert retrieved.scope_path is None
