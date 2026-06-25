"""SQLite-backed persistent MemoryStore implementation.

Production-grade persistence for single-host deployments:
- One long-lived aiosqlite connection per store instance (opened lazily)
- WAL journal mode for concurrent readers + one writer without blocking
- busy_timeout so SQLITE_BUSY turns into a bounded wait instead of an error
- asyncio.Lock serializes in-process writes to the connection
- explicit close() for graceful shutdown
"""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import aiosqlite

from cemaf.core.enums import MemoryScope
from cemaf.core.types import Confidence
from cemaf.core.utils import utc_now
from cemaf.memory.base import MemoryItem

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS memory_items (
    scope TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    ttl_seconds REAL,
    expires_at TEXT,
    scope_path TEXT,
    PRIMARY KEY (scope, key)
)
"""

_CREATE_INDEX_EXPIRES = (
    "CREATE INDEX IF NOT EXISTS idx_memory_items_expires_at "
    "ON memory_items(expires_at) WHERE expires_at IS NOT NULL"
)


def _row_to_item(row: aiosqlite.Row) -> MemoryItem:
    """Deserialize a database row into a MemoryItem."""
    ttl_seconds = row[6]
    expires_at_str = row[7]
    return MemoryItem(
        scope=MemoryScope(row[0]),
        key=row[1],
        value=json.loads(row[2]),
        confidence=Confidence(row[3]),
        created_at=datetime.fromisoformat(row[4]),
        updated_at=datetime.fromisoformat(row[5]),
        ttl=timedelta(seconds=ttl_seconds) if ttl_seconds is not None else None,
        expires_at=datetime.fromisoformat(expires_at_str) if expires_at_str is not None else None,
        scope_path=row[8],
    )


class SqliteMemoryStore:
    """Persistent memory store backed by SQLite via aiosqlite."""

    def __init__(
        self,
        *,
        db_path: str = "cemaf_memory.db",
        busy_timeout_ms: int = 5000,
        journal_mode: str = "WAL",
    ) -> None:
        self._db_path = db_path
        self._busy_timeout_ms = busy_timeout_ms
        self._journal_mode = journal_mode
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> SqliteMemoryStore:
        """Allow `async with` usage for deterministic connection cleanup."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        await self.close()

    async def _connection(self) -> aiosqlite.Connection:
        """Return the lazy-initialized, pragma-tuned connection."""
        if self._conn is not None:
            return self._conn
        async with self._lock:
            if self._conn is not None:  # double-check after acquire
                return self._conn
            conn = await aiosqlite.connect(self._db_path)
            # WAL gives us concurrent readers + a single writer without
            # locking the whole file — essential under any concurrent load.
            await conn.execute(f"PRAGMA journal_mode={self._journal_mode}")
            # busy_timeout turns SQLITE_BUSY into a bounded wait instead of
            # an immediate error. 5s is enough to ride out any in-process
            # writer contention.
            await conn.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
            # synchronous=NORMAL is the WAL-recommended level — durable on
            # crash but doesn't fsync on every commit.
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.execute(_CREATE_TABLE)
            await conn.execute(_CREATE_INDEX_EXPIRES)
            await conn.commit()
            self._conn = conn
        return self._conn

    async def close(self) -> None:
        """Close the underlying connection. Idempotent."""
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None

    async def get(self, scope: MemoryScope, key: str) -> MemoryItem | None:
        """Retrieve a memory item by scope and key."""
        conn = await self._connection()
        async with conn.execute(
            "SELECT scope, key, value_json, confidence, created_at, updated_at, "
            "ttl_seconds, expires_at, scope_path FROM memory_items "
            "WHERE scope = ? AND key = ?",
            (scope.value, key),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        item = _row_to_item(row)
        if item.is_expired:
            await self.delete(scope=scope, key=key)
            return None
        return item

    async def set(self, item: MemoryItem) -> None:
        """Store or replace a memory item."""
        conn = await self._connection()
        async with self._lock:
            await conn.execute(
                "INSERT OR REPLACE INTO memory_items "
                "(scope, key, value_json, confidence, created_at, "
                "updated_at, ttl_seconds, expires_at, scope_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item.scope.value,
                    item.key,
                    json.dumps(item.value),
                    float(item.confidence),
                    item.created_at.isoformat(),
                    item.updated_at.isoformat(),
                    item.ttl.total_seconds() if item.ttl is not None else None,
                    item.expires_at.isoformat() if item.expires_at is not None else None,
                    item.scope_path,
                ),
            )
            await conn.commit()

    async def delete(self, scope: MemoryScope, key: str) -> bool:
        """Delete a memory item, returning True if it existed."""
        conn = await self._connection()
        async with self._lock:
            cursor = await conn.execute(
                "DELETE FROM memory_items WHERE scope = ? AND key = ?",
                (scope.value, key),
            )
            await conn.commit()
            return bool(cursor.rowcount > 0)

    async def list_by_scope(self, scope: MemoryScope) -> tuple[MemoryItem, ...]:
        """List all non-expired items in a scope."""
        conn = await self._connection()
        now_iso = utc_now().isoformat()
        async with conn.execute(
            "SELECT scope, key, value_json, confidence, created_at, updated_at, "
            "ttl_seconds, expires_at, scope_path FROM memory_items "
            "WHERE scope = ? AND (expires_at IS NULL OR expires_at > ?)",
            (scope.value, now_iso),
        ) as cursor:
            rows = await cursor.fetchall()
        return tuple(_row_to_item(row) for row in rows)

    async def cleanup_expired(self) -> int:
        """Remove all expired items, returning count removed."""
        conn = await self._connection()
        now_iso = utc_now().isoformat()
        async with self._lock:
            cursor = await conn.execute(
                "DELETE FROM memory_items WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now_iso,),
            )
            await conn.commit()
            return int(cursor.rowcount)


async def load_items_by_scopes(
    *,
    db_path: str | Path,
    scopes: tuple[MemoryScope, ...],
) -> tuple[MemoryItem, ...]:
    """Load all persisted items for the given scopes through ``SqliteMemoryStore``."""

    store = SqliteMemoryStore(db_path=str(db_path))
    try:
        items: list[MemoryItem] = []
        for scope in scopes:
            items.extend(await store.list_by_scope(scope))
        return tuple(items)
    finally:
        await store.close()


def load_items_by_scopes_sync(
    *,
    db_path: str | Path,
    scopes: tuple[MemoryScope, ...],
) -> tuple[MemoryItem, ...]:
    """Synchronous wrapper for ``load_items_by_scopes`` that is safe in or out of an event loop."""

    async def _load() -> tuple[MemoryItem, ...]:
        return await load_items_by_scopes(db_path=db_path, scopes=scopes)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_load())

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(lambda: asyncio.run(_load()))
        return future.result()
