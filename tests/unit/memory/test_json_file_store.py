"""Unit tests for JsonFileMemoryStore."""

import json
from datetime import timedelta
from pathlib import Path

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.core.types import Confidence
from cemaf.memory.base import JsonFileMemoryStore, MemoryItem

# ---------------------------------------------------------------------------
# Contract tests (define the interface before trusting the implementation)
# ---------------------------------------------------------------------------


class TestJsonFileStoreContract:
    """Verify JsonFileMemoryStore satisfies the MemoryStore protocol."""

    @pytest.mark.asyncio
    async def test_get_missing_key_returns_none(self, tmp_path: Path) -> None:
        store = JsonFileMemoryStore(path=tmp_path / "mem.json")
        result = await store.get(MemoryScope.PROJECT, "missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_then_get_roundtrip(self, tmp_path: Path) -> None:
        store = JsonFileMemoryStore(path=tmp_path / "mem.json")
        item = MemoryItem(scope=MemoryScope.PROJECT, key="k", value={"v": 1})
        await store.set(item)
        fetched = await store.get(MemoryScope.PROJECT, "k")
        assert fetched is not None
        assert fetched.key == "k"
        assert fetched.value == {"v": 1}

    @pytest.mark.asyncio
    async def test_delete_returns_true_for_existing_key(self, tmp_path: Path) -> None:
        store = JsonFileMemoryStore(path=tmp_path / "mem.json")
        item = MemoryItem(scope=MemoryScope.PROJECT, key="k", value={})
        await store.set(item)
        deleted = await store.delete(MemoryScope.PROJECT, "k")
        assert deleted is True

    @pytest.mark.asyncio
    async def test_delete_returns_false_for_missing_key(self, tmp_path: Path) -> None:
        store = JsonFileMemoryStore(path=tmp_path / "mem.json")
        deleted = await store.delete(MemoryScope.PROJECT, "ghost")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_list_by_scope_only_returns_matching_scope(self, tmp_path: Path) -> None:
        store = JsonFileMemoryStore(path=tmp_path / "mem.json")
        await store.set(MemoryItem(scope=MemoryScope.PROJECT, key="p1", value={}))
        await store.set(MemoryItem(scope=MemoryScope.TENANT, key="b1", value={}))
        results = await store.list_by_scope(MemoryScope.PROJECT)
        assert len(results) == 1
        assert results[0].scope == MemoryScope.PROJECT


# ---------------------------------------------------------------------------
# Unit tests — persistence behaviour
# ---------------------------------------------------------------------------


class TestJsonFileStorePersistence:
    """Verify data survives process restarts (new store instance, same file)."""

    @pytest.mark.asyncio
    async def test_data_persists_across_store_instances(self, tmp_path: Path) -> None:
        path = tmp_path / "mem.json"
        store1 = JsonFileMemoryStore(path=path)
        await store1.set(MemoryItem(scope=MemoryScope.TENANT, key="company", value={"name": "Acme"}))

        # New instance reads from the same file
        store2 = JsonFileMemoryStore(path=path)
        item = await store2.get(MemoryScope.TENANT, "company")
        assert item is not None
        assert item.value == {"name": "Acme"}

    @pytest.mark.asyncio
    async def test_delete_persists_across_store_instances(self, tmp_path: Path) -> None:
        path = tmp_path / "mem.json"
        store1 = JsonFileMemoryStore(path=path)
        await store1.set(MemoryItem(scope=MemoryScope.PROJECT, key="k", value={}))
        await store1.delete(MemoryScope.PROJECT, "k")

        store2 = JsonFileMemoryStore(path=path)
        assert await store2.get(MemoryScope.PROJECT, "k") is None

    @pytest.mark.asyncio
    async def test_file_is_human_readable_json(self, tmp_path: Path) -> None:
        path = tmp_path / "mem.json"
        store = JsonFileMemoryStore(path=path)
        await store.set(
            MemoryItem(
                scope=MemoryScope.PROJECT,
                key="readable",
                value={"info": "hello"},
                confidence=Confidence(0.9),
            )
        )

        raw = json.loads(path.read_text())
        assert isinstance(raw, dict)
        record = next(iter(raw.values()))
        assert record["key"] == "readable"
        assert record["value"] == {"info": "hello"}
        assert record["confidence"] == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_parent_directories_created_automatically(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "deep" / "mem.json"
        store = JsonFileMemoryStore(path=path)
        await store.set(MemoryItem(scope=MemoryScope.TENANT, key="k", value={}))
        assert path.exists()

    @pytest.mark.asyncio
    async def test_expired_items_not_loaded_on_startup(self, tmp_path: Path) -> None:
        path = tmp_path / "mem.json"
        store1 = JsonFileMemoryStore(path=path)
        item = MemoryItem(
            scope=MemoryScope.SESSION,
            key="tmp",
            value={},
            ttl=timedelta(seconds=-1),  # already expired
        )
        # Write directly to bypass in-memory expiry guard
        store1._data[item.full_key] = item
        store1._save()

        store2 = JsonFileMemoryStore(path=path)
        assert await store2.get(MemoryScope.SESSION, "tmp") is None

    @pytest.mark.asyncio
    async def test_cleanup_expired_removes_and_saves(self, tmp_path: Path) -> None:
        path = tmp_path / "mem.json"
        store = JsonFileMemoryStore(path=path)
        item = MemoryItem(
            scope=MemoryScope.SESSION,
            key="tmp",
            value={},
            ttl=timedelta(seconds=-1),
        )
        store._data[item.full_key] = item
        store._save()

        removed = await store.cleanup_expired()
        assert removed == 1
        assert not json.loads(path.read_text())  # file is now empty dict

    @pytest.mark.asyncio
    async def test_nonexistent_file_starts_empty(self, tmp_path: Path) -> None:
        store = JsonFileMemoryStore(path=tmp_path / "does_not_exist.json")
        items = await store.list_by_scope(MemoryScope.TENANT)
        assert items == ()

    @pytest.mark.asyncio
    async def test_corrupt_file_starts_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "corrupt.json"
        path.write_text("NOT VALID JSON {{{{")
        store = JsonFileMemoryStore(path=path)
        items = await store.list_by_scope(MemoryScope.TENANT)
        assert items == ()
