"""SQLite-backed persistent MemoryStore implementation."""

import json
from datetime import datetime, timedelta

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

    def __init__(self, *, db_path: str = "cemaf_memory.db") -> None:
        self._db_path = db_path
        self._initialized = False

    async def _ensure_table(self) -> None:
        """Create the table if it doesn't exist yet."""
        if self._initialized:
            return
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_CREATE_TABLE)
            await db.commit()
        self._initialized = True

    async def get(self, scope: MemoryScope, key: str) -> MemoryItem | None:
        """Retrieve a memory item by scope and key."""
        await self._ensure_table()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT scope, key, value_json, confidence, created_at, updated_at, "
                "ttl_seconds, expires_at, scope_path FROM memory_items WHERE scope = ? AND key = ?",
                (scope.value, key),
            )
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
        await self._ensure_table()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
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
            await db.commit()

    async def delete(self, scope: MemoryScope, key: str) -> bool:
        """Delete a memory item, returning True if it existed."""
        await self._ensure_table()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM memory_items WHERE scope = ? AND key = ?",
                (scope.value, key),
            )
            await db.commit()
            return bool(cursor.rowcount > 0)

    async def list_by_scope(self, scope: MemoryScope) -> tuple[MemoryItem, ...]:
        """List all non-expired items in a scope."""
        await self._ensure_table()
        now_iso = utc_now().isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT scope, key, value_json, confidence, created_at, updated_at, "
                "ttl_seconds, expires_at, scope_path FROM memory_items "
                "WHERE scope = ? AND (expires_at IS NULL OR expires_at > ?)",
                (scope.value, now_iso),
            )
            rows = await cursor.fetchall()
            return tuple(_row_to_item(row) for row in rows)

    async def cleanup_expired(self) -> int:
        """Remove all expired items, returning count removed."""
        await self._ensure_table()
        now_iso = utc_now().isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM memory_items WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now_iso,),
            )
            await db.commit()
            return int(cursor.rowcount)
