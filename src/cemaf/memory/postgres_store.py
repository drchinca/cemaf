"""PostgreSQL-backed persistent MemoryStore implementation.

Production-grade persistence for multi-host deployments:
- asyncpg connection pool (min/max size configurable) with 30-second command timeout
- Tenant isolation column on every row; all queries are tenant-scoped
- BRIN index on expires_at avoids full-table scans for TTL cleanup
- GIN index on value_json allows server-side JSONB containment checks
- Schema name parameter keeps CEMAF tables in their own namespace
- Inherits redaction and serialization hooks from MemoryStore ABC
"""

import json
from datetime import datetime, timedelta
from typing import Any

from cemaf.core.enums import MemoryScope
from cemaf.core.types import Confidence
from cemaf.core.utils import utc_now
from cemaf.memory.base import MemoryItem, MemoryStore


def _row_to_item(row: Any) -> MemoryItem:
    ttl_seconds = row["ttl_seconds"]
    expires_at_raw = row["expires_at"]
    # asyncpg returns TIMESTAMPTZ as aware datetime objects directly
    if isinstance(expires_at_raw, datetime):
        expires_at = expires_at_raw
    elif isinstance(expires_at_raw, str):
        expires_at = datetime.fromisoformat(expires_at_raw)
    else:
        expires_at = None

    created_at = row["created_at"]
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)

    updated_at = row["updated_at"]
    if isinstance(updated_at, str):
        updated_at = datetime.fromisoformat(updated_at)

    return MemoryItem(
        scope=MemoryScope(row["scope"]),
        key=row["key"],
        value=(
            json.loads(row["value_json"]) if isinstance(row["value_json"], str) else dict(row["value_json"])
        ),
        confidence=Confidence(float(row["confidence"])),
        created_at=created_at,
        updated_at=updated_at,
        ttl=timedelta(seconds=ttl_seconds) if ttl_seconds is not None else None,
        expires_at=expires_at,
        scope_path=row["scope_path"],
    )


class PostgresMemoryStore(MemoryStore):
    """Persistent memory store backed by PostgreSQL via asyncpg.

    Multi-tenant: every write includes tenant_id; every query filters by it.
    Pool is initialized lazily on first use so construction is synchronous.
    """

    def __init__(
        self,
        *,
        dsn: str,
        tenant_id: str = "default",
        pool_min: int = 2,
        pool_max: int = 10,
        schema: str = "cemaf",
    ) -> None:
        super().__init__()
        self._dsn = dsn
        self._tenant_id = tenant_id
        self._pool_min = pool_min
        self._pool_max = pool_max
        self._schema = schema
        self._pool: Any | None = None

    async def _ensure_pool(self) -> Any:
        if self._pool is not None:
            return self._pool
        try:
            import asyncpg
        except ImportError as exc:
            raise ImportError(
                "asyncpg is required for PostgresMemoryStore. Install it with: pip install 'cemaf[postgres]'"
            ) from exc

        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=self._pool_min,
            max_size=self._pool_max,
            command_timeout=30,
        )
        await self._ensure_schema()
        return self._pool

    async def _ensure_schema(self) -> None:
        pool = self._pool
        s = self._schema
        ddl = f"""
            CREATE SCHEMA IF NOT EXISTS {s};
            CREATE TABLE IF NOT EXISTS {s}.memory_items (
                tenant_id TEXT NOT NULL DEFAULT 'default',
                scope TEXT NOT NULL,
                key TEXT NOT NULL,
                value_json JSONB NOT NULL,
                confidence REAL NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                ttl_seconds REAL,
                expires_at TIMESTAMPTZ,
                scope_path TEXT,
                PRIMARY KEY (tenant_id, scope, key)
            );
            CREATE INDEX IF NOT EXISTS idx_mi_expires
                ON {s}.memory_items USING BRIN (expires_at);
            CREATE INDEX IF NOT EXISTS idx_mi_gin
                ON {s}.memory_items USING GIN (value_json);
        """
        async with pool.acquire() as conn:
            await conn.execute(ddl)

    async def close(self) -> None:
        """Close the pool. Idempotent."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def get(self, scope: MemoryScope, key: str) -> MemoryItem | None:
        """Retrieve a non-expired item by scope and key."""
        pool = await self._ensure_pool()
        s = self._schema
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT scope, key, value_json::text, confidence, created_at, updated_at, "
                f"ttl_seconds, expires_at, scope_path "
                f"FROM {s}.memory_items "
                f"WHERE tenant_id = $1 AND scope = $2 AND key = $3",
                self._tenant_id,
                scope.value,
                key,
            )
        if row is None:
            return None
        item = _row_to_item(row)
        if item.is_expired:
            await self.delete(scope=scope, key=key)
            return None
        return self._apply_redaction(item)

    async def set(self, item: MemoryItem) -> None:
        """Upsert a memory item, replacing on (tenant_id, scope, key) conflict."""
        pool = await self._ensure_pool()
        s = self._schema
        async with pool.acquire() as conn:
            await conn.execute(
                f"INSERT INTO {s}.memory_items "
                f"(tenant_id, scope, key, value_json, confidence, created_at, updated_at, "
                f"ttl_seconds, expires_at, scope_path) "
                f"VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9, $10) "
                f"ON CONFLICT (tenant_id, scope, key) DO UPDATE SET "
                f"value_json = EXCLUDED.value_json, "
                f"confidence = EXCLUDED.confidence, "
                f"updated_at = EXCLUDED.updated_at, "
                f"ttl_seconds = EXCLUDED.ttl_seconds, "
                f"expires_at = EXCLUDED.expires_at, "
                f"scope_path = EXCLUDED.scope_path",
                self._tenant_id,
                item.scope.value,
                item.key,
                json.dumps(item.value),
                float(item.confidence),
                item.created_at,
                item.updated_at,
                item.ttl.total_seconds() if item.ttl is not None else None,
                item.expires_at,
                item.scope_path,
            )

    async def delete(self, scope: MemoryScope, key: str) -> bool:
        """Delete an item, returning True if it existed."""
        pool = await self._ensure_pool()
        s = self._schema
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM {s}.memory_items WHERE tenant_id = $1 AND scope = $2 AND key = $3",
                self._tenant_id,
                scope.value,
                key,
            )
        # asyncpg returns "DELETE N" as a string
        count = int(result.split()[-1])
        return count > 0

    async def list_by_scope(
        self,
        scope: MemoryScope,
        exclude_filter: dict[str, list[Any]] | None = None,
    ) -> tuple[MemoryItem, ...]:
        """List all non-expired items in a scope with optional value-field exclusion.

        exclude_filter: maps a top-level JSON field name to values to exclude.
        Translates to AND value_json->>'field' != ALL($N) per excluded field.
        """
        pool = await self._ensure_pool()
        s = self._schema
        now = utc_now()

        params: list[Any] = [self._tenant_id, scope.value, now]
        where_clauses = [
            "tenant_id = $1",
            "scope = $2",
            "(expires_at IS NULL OR expires_at > $3)",
        ]

        if exclude_filter:
            for field_name, excluded_values in exclude_filter.items():
                idx = len(params) + 1
                params.append(excluded_values)
                where_clauses.append(f"value_json->>'{field_name}' != ALL(${idx}::text[])")

        query = (
            f"SELECT scope, key, value_json::text, confidence, created_at, updated_at, "
            f"ttl_seconds, expires_at, scope_path "
            f"FROM {s}.memory_items "
            f"WHERE {' AND '.join(where_clauses)}"
        )

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        items = []
        for row in rows:
            item = self._apply_redaction(_row_to_item(row))
            if item is not None:
                items.append(item)
        return tuple(items)

    async def cleanup_expired(self) -> int:
        """Remove all expired items, returning count removed."""
        pool = await self._ensure_pool()
        s = self._schema
        now = utc_now()
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM {s}.memory_items "
                f"WHERE tenant_id = $1 AND expires_at IS NOT NULL AND expires_at < $2",
                self._tenant_id,
                now,
            )
        return int(result.split()[-1])
