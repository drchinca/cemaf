"""BYO MemoryStore — durable agent memory on your own backend.

Use-case: you want agent memory that survives a process restart on a single box
— SQLite, not Redis. Subclass the `MemoryStore` ABC; CEMAF's MemoryManager
(semantic recall, scoping, dedup) runs on top of it unchanged.

Best practice shown: implement the storage contract only, then compose it through
`create_memory_manager` — the manager owns recall/scoping, your class owns bytes.

Usage:
    uv run python examples/byo/byo_memory.py
"""

import asyncio
import json
import sqlite3

from cemaf.core.enums import MemoryScope
from cemaf.memory.base import MemoryItem, MemoryStore
from cemaf.memory.factories import create_memory_manager
from cemaf.memory.semantic import MemoryQuery


class SqliteMemoryStore(MemoryStore):
    """A MemoryStore backed by SQLite (in-memory here; pass a path to persist)."""

    def __init__(self, database: str = ":memory:") -> None:
        super().__init__()
        self._db = sqlite3.connect(database)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS memory "
            "(scope TEXT, key TEXT, value TEXT, confidence REAL, PRIMARY KEY (scope, key))"
        )

    async def get(self, scope: MemoryScope, key: str) -> MemoryItem | None:
        row = self._db.execute(
            "SELECT value, confidence FROM memory WHERE scope = ? AND key = ?",
            (scope.value, key),
        ).fetchone()
        if row is None:
            return None
        value, confidence = row
        item = MemoryItem(scope=scope, key=key, value=json.loads(value), confidence=confidence)
        return None if item.is_expired else item

    async def set(self, item: MemoryItem) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO memory (scope, key, value, confidence) VALUES (?, ?, ?, ?)",
            (item.scope.value, item.key, json.dumps(item.value), float(item.confidence)),
        )
        self._db.commit()

    async def delete(self, scope: MemoryScope, key: str) -> bool:
        cursor = self._db.execute("DELETE FROM memory WHERE scope = ? AND key = ?", (scope.value, key))
        self._db.commit()
        return cursor.rowcount > 0

    async def list_by_scope(self, scope: MemoryScope) -> tuple[MemoryItem, ...]:
        rows = self._db.execute(
            "SELECT key, value, confidence FROM memory WHERE scope = ?", (scope.value,)
        ).fetchall()
        return tuple(
            MemoryItem(scope=scope, key=key, value=json.loads(value), confidence=confidence)
            for key, value, confidence in rows
        )

    async def cleanup_expired(self) -> int:
        return 0  # TTLs are honored on read via MemoryItem.is_expired


async def main() -> None:
    manager = create_memory_manager(memory_store=SqliteMemoryStore())

    await manager.remember(
        MemoryScope.SESSION,
        "fav_color",
        {"color": "teal"},
        confidence=0.9,
        content_for_embedding="the user's favorite color is teal",
    )

    by_key = await manager.recall_by_key(MemoryScope.SESSION, "fav_color")
    semantic = await manager.recall(MemoryQuery(text="color", scope=MemoryScope.SESSION, limit=3))

    assert by_key is not None and by_key.value == {"color": "teal"}

    print(f"recall_by_key : {by_key.key} = {by_key.value} (conf {by_key.confidence})")
    print(f"semantic hits : {[r.item.key for r in semantic]}")


if __name__ == "__main__":
    asyncio.run(main())
