"""SQLite-backed `WritableBlueprintSource` — the production catalog for growing libraries.

A team that wants its `BlueprintLibrary` to persist entries across process
restarts and accept runtime writes (from a harvester, an admin CLI, an
HTTP endpoint) points at a single SQLite file via `SqliteBlueprintSource`.
The same file can be version-controlled, backed up, inspected with any
SQLite tool, and swapped between processes without ceremony.

This mirrors the `SqliteMemoryStore` pattern exactly — one long-lived
aiosqlite connection, WAL journal mode, `busy_timeout` for bounded
contention, an `asyncio.Lock` serializing in-process writers, and
explicit `close()` for graceful shutdown.

Storage model:

    CREATE TABLE blueprint_entries (
        id            TEXT PRIMARY KEY,
        kind          TEXT NOT NULL,         -- snapshot / factory / recipe
        title         TEXT NOT NULL,
        description   TEXT NOT NULL,
        tags_json     TEXT NOT NULL,         -- json-serialized tuple[str, ...]
        source        TEXT NOT NULL,
        path          TEXT NOT NULL,
        version       TEXT NOT NULL,
        payload_json  TEXT NOT NULL,         -- whichever of snapshot/ref/recipe applies
        metadata_json TEXT NOT NULL,
        created_at    TEXT NOT NULL
    )

`append()` is idempotent upsert keyed by `id` (`INSERT OR REPLACE`), so
harvesters using content-addressed ids can write freely without dedup
logic at their layer.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from typing import Any

import aiosqlite

from cemaf.blueprint.library import BlueprintEntry, BlueprintEntryKind
from cemaf.core.utils import utc_now

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS blueprint_entries (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    title         TEXT NOT NULL,
    description   TEXT NOT NULL,
    tags_json     TEXT NOT NULL,
    source        TEXT NOT NULL,
    path          TEXT NOT NULL,
    version       TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at    TEXT NOT NULL
)
"""

_CREATE_INDEX_KIND = "CREATE INDEX IF NOT EXISTS idx_blueprint_entries_kind ON blueprint_entries(kind)"


def _payload_for(entry: BlueprintEntry) -> dict[str, Any]:
    """Extract the kind-specific payload as a dict for JSON serialization."""
    match entry.kind:
        case BlueprintEntryKind.SNAPSHOT:
            assert entry.snapshot is not None  # guaranteed by __post_init__
            return entry.snapshot
        case BlueprintEntryKind.FACTORY:
            assert entry.factory_ref is not None
            return {"factory_ref": entry.factory_ref}
        case BlueprintEntryKind.RECIPE:
            assert entry.recipe is not None
            return entry.recipe


def _row_to_entry(row: aiosqlite.Row) -> BlueprintEntry:
    """Deserialize a blueprint_entries row into a BlueprintEntry."""
    kind = BlueprintEntryKind(row[1])
    payload = json.loads(row[8])
    tags = tuple(json.loads(row[4]))
    metadata = json.loads(row[9])

    snapshot: dict[str, Any] | None = None
    factory_ref: str | None = None
    recipe: dict[str, Any] | None = None
    match kind:
        case BlueprintEntryKind.SNAPSHOT:
            snapshot = payload
        case BlueprintEntryKind.FACTORY:
            factory_ref = payload["factory_ref"]
        case BlueprintEntryKind.RECIPE:
            recipe = payload

    return BlueprintEntry(
        id=row[0],
        kind=kind,
        title=row[2],
        description=row[3],
        tags=tags,
        source=row[5],
        path=row[6],
        version=row[7],
        snapshot=snapshot,
        factory_ref=factory_ref,
        recipe=recipe,
        metadata=metadata,
    )


class SqliteBlueprintSource:
    """Persistent blueprint catalog backed by SQLite via aiosqlite."""

    def __init__(
        self,
        *,
        db_path: str = "cemaf_blueprints.db",
        name: str | None = None,
        busy_timeout_ms: int = 5000,
        journal_mode: str = "WAL",
    ) -> None:
        self._db_path = db_path
        self._name = name or f"sqlite:{db_path}"
        self._busy_timeout_ms = busy_timeout_ms
        self._journal_mode = journal_mode
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return self._name

    async def _connection(self) -> aiosqlite.Connection:
        """Return the lazy-initialized, pragma-tuned connection."""
        if self._conn is not None:
            return self._conn
        async with self._lock:
            if self._conn is not None:
                return self._conn
            conn = await aiosqlite.connect(self._db_path)
            await conn.execute(f"PRAGMA journal_mode={self._journal_mode}")
            await conn.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.execute(_CREATE_TABLE)
            await conn.execute(_CREATE_INDEX_KIND)
            await conn.commit()
            self._conn = conn
        return self._conn

    async def close(self) -> None:
        """Close the underlying connection. Idempotent."""
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None

    async def append(self, *, entry: BlueprintEntry) -> None:
        """Upsert `entry` by id. Idempotent — harvester can call with the same id freely."""
        conn = await self._connection()
        stamped_source = entry.source or self._name
        payload_json = json.dumps(_payload_for(entry))
        async with self._lock:
            await conn.execute(
                """
                INSERT OR REPLACE INTO blueprint_entries
                (id, kind, title, description, tags_json, source, path, version,
                 payload_json, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.id,
                    entry.kind.value,
                    entry.title,
                    entry.description,
                    json.dumps(list(entry.tags)),
                    stamped_source,
                    entry.path,
                    entry.version,
                    payload_json,
                    json.dumps(entry.metadata),
                    utc_now().isoformat(),
                ),
            )
            await conn.commit()

    def load(self) -> Iterable[BlueprintEntry]:
        """Yield every stored entry. Runs a blocking SELECT — intended for boot-time wiring.

        Mirrors the async `append` path's pragmas — WAL + `busy_timeout` —
        so a concurrent writer (harvester appending under the aiosqlite
        lock) doesn't cause `SQLITE_BUSY` on this reader. Without the
        timeout the sync reader gives up immediately on contention.
        """
        # Sync sqlite3 connection — BlueprintSource.load() is a synchronous generator
        # and callers (BlueprintLibrary.register_from) may run it outside an event
        # loop at import time.
        import sqlite3

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(f"PRAGMA journal_mode={self._journal_mode}")
            conn.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
            conn.execute(_CREATE_TABLE)
            conn.execute(_CREATE_INDEX_KIND)
            cursor = conn.execute(
                "SELECT id, kind, title, description, tags_json, source, path, version, "
                "payload_json, metadata_json, created_at "
                "FROM blueprint_entries ORDER BY created_at ASC"
            )
            for row in cursor.fetchall():
                yield _row_to_entry(row)


__all__ = ["SqliteBlueprintSource"]
