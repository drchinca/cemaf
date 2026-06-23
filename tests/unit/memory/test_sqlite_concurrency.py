"""Regression tests — SqliteMemoryStore must tolerate concurrent writes.

Before the fix, every operation opened its own aiosqlite connection with
no WAL + no busy_timeout. Under concurrent load this raised SQLITE_BUSY
silently (the error bubbled up as `OperationalError: database is locked`).
Production persistence was single-writer.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.core.types import Confidence
from cemaf.memory.base import MemoryItem
from cemaf.memory.sqlite_store import SqliteMemoryStore


def _item(key: str, value: str = "v") -> MemoryItem:
    return MemoryItem(scope=MemoryScope.PROJECT, key=key, value=value, confidence=Confidence(1.0))


@pytest.mark.asyncio
async def test_concurrent_writes_do_not_raise(tmp_path: Path) -> None:
    """100 concurrent set() calls with WAL + busy_timeout complete cleanly."""
    store = SqliteMemoryStore(db_path=str(tmp_path / "concurrent.db"))
    try:
        # Fire 100 writes in parallel to distinct keys
        await asyncio.gather(*(store.set(item=_item(f"k{i}", f"v{i}")) for i in range(100)))
        items = await store.list_by_scope(scope=MemoryScope.PROJECT)
        assert len(items) == 100
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_concurrent_reads_and_writes_coexist(tmp_path: Path) -> None:
    """WAL lets readers proceed while writers are active."""
    store = SqliteMemoryStore(db_path=str(tmp_path / "rw.db"))
    try:
        # Pre-seed
        await asyncio.gather(*(store.set(item=_item(f"seed{i}")) for i in range(20)))

        async def writer(i: int) -> None:
            await store.set(item=_item(f"w{i}"))

        async def reader() -> int:
            items = await store.list_by_scope(scope=MemoryScope.PROJECT)
            return len(items)

        results = await asyncio.gather(
            *[writer(i) for i in range(30)],
            *[reader() for _ in range(30)],
        )
        # No exceptions; all readers saw ≥20 items, writers all returned None
        read_counts = [r for r in results if isinstance(r, int)]
        assert all(c >= 20 for c in read_counts)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_multiple_store_instances_share_one_writer_lane(tmp_path: Path) -> None:
    """Separate store instances pointed at one db should not trip SQLITE_BUSY."""
    stores = [SqliteMemoryStore(db_path=str(tmp_path / "multi-instance.db")) for _ in range(4)]
    try:
        await asyncio.gather(*(stores[i % len(stores)].set(item=_item(f"k{i}", f"v{i}")) for i in range(200)))
        items = await stores[0].list_by_scope(scope=MemoryScope.PROJECT)
        assert len(items) == 200
        assert {item.key for item in items} == {f"k{i}" for i in range(200)}
    finally:
        await asyncio.gather(*(store.close() for store in stores))


@pytest.mark.asyncio
async def test_wal_pragma_is_set(tmp_path: Path) -> None:
    """Journal mode must be WAL — regression for the root cause."""
    store = SqliteMemoryStore(db_path=str(tmp_path / "pragma.db"))
    try:
        conn = await store._connection()
        async with conn.execute("PRAGMA journal_mode") as cursor:
            row = await cursor.fetchone()
        assert row is not None
        assert row[0].upper() == "WAL"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_busy_timeout_pragma_is_set(tmp_path: Path) -> None:
    """busy_timeout must be non-zero so concurrent writers block instead of erroring."""
    store = SqliteMemoryStore(db_path=str(tmp_path / "pragma.db"), busy_timeout_ms=3000)
    try:
        conn = await store._connection()
        async with conn.execute("PRAGMA busy_timeout") as cursor:
            row = await cursor.fetchone()
        assert row is not None
        assert int(row[0]) == 3000
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_close_is_idempotent(tmp_path: Path) -> None:
    store = SqliteMemoryStore(db_path=str(tmp_path / "close.db"))
    await store.set(item=_item("k"))
    await store.close()
    await store.close()  # second call must not raise
    # Can reopen after close
    await store.set(item=_item("after-close"))
    items = await store.list_by_scope(scope=MemoryScope.PROJECT)
    assert {i.key for i in items} == {"k", "after-close"}
    await store.close()
