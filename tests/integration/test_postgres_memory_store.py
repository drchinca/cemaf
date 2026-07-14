"""Offline integration tests for PostgresMemoryStore.

These tests drive the real PostgresMemoryStore methods against a small
asyncpg-shaped in-memory pool. They verify CEMAF's query/serialization behavior
without requiring a live database in the default suite. Real database smoke can
be run separately by wiring PostgresMemoryStore with an actual DSN.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.core.types import Confidence
from cemaf.core.utils import utc_now
from cemaf.memory.base import MemoryItem
from cemaf.memory.postgres_store import PostgresMemoryStore

_TEST_SCHEMA = "cemaf_test"


class _FakeAcquire:
    def __init__(self, conn: _FakeConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> _FakeConnection:
        return self._conn

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class _FakePool:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.closed = False
        self.conn = _FakeConnection(self)

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(self.conn)

    async def close(self) -> None:
        self.closed = True


class _FakeConnection:
    def __init__(self, pool: _FakePool) -> None:
        self._pool = pool

    async def execute(self, query: str, *params: Any) -> str:
        normalized = " ".join(query.strip().split()).upper()
        if normalized.startswith("CREATE SCHEMA") or normalized.startswith("DROP SCHEMA"):
            if normalized.startswith("DROP SCHEMA"):
                self._pool.rows.clear()
            return "OK"

        if normalized.startswith("INSERT INTO"):
            (
                tenant,
                scope,
                key,
                value_json,
                confidence,
                created_at,
                updated_at,
                ttl,
                expires_at,
                scope_path,
            ) = params
            self._pool.rows[(tenant, scope, key)] = {
                "tenant_id": tenant,
                "scope": scope,
                "key": key,
                "value_json": value_json,
                "confidence": confidence,
                "created_at": created_at,
                "updated_at": updated_at,
                "ttl_seconds": ttl,
                "expires_at": expires_at,
                "scope_path": scope_path,
            }
            return "INSERT 0 1"

        if normalized.startswith("UPDATE"):
            expires_at, tenant, scope, key = params
            row = self._pool.rows.get((tenant, scope, key))
            if row is None:
                return "UPDATE 0"
            row["expires_at"] = expires_at
            return "UPDATE 1"

        if normalized.startswith("DELETE FROM") and "SCOPE = $2 AND KEY = $3" in normalized:
            tenant, scope, key = params
            removed = self._pool.rows.pop((tenant, scope, key), None)
            return f"DELETE {1 if removed is not None else 0}"

        if normalized.startswith("DELETE FROM") and "EXPIRES_AT IS NOT NULL" in normalized:
            tenant, now = params
            keys = [
                key
                for key, row in self._pool.rows.items()
                if key[0] == tenant and row["expires_at"] is not None and row["expires_at"] < now
            ]
            for key in keys:
                self._pool.rows.pop(key, None)
            return f"DELETE {len(keys)}"

        raise AssertionError(f"unexpected SQL execute: {query}")

    async def fetchrow(self, query: str, *params: Any) -> dict[str, Any] | None:
        tenant, scope, key = params
        row = self._pool.rows.get((tenant, scope, key))
        return dict(row) if row is not None else None

    async def fetch(self, query: str, *params: Any) -> list[dict[str, Any]]:
        tenant, scope, now, *exclude_values = params
        excluded_fields = re.findall(r"value_json->>'([^']+)'", query)
        rows: list[dict[str, Any]] = []

        for (row_tenant, row_scope, _), row in self._pool.rows.items():
            if row_tenant != tenant or row_scope != scope:
                continue
            expires_at = row["expires_at"]
            if expires_at is not None and expires_at <= now:
                continue

            value = json.loads(row["value_json"])
            excluded = False
            for field_name, field_excluded_values in zip(excluded_fields, exclude_values, strict=False):
                blocked = {str(v) for v in field_excluded_values}
                if str(value.get(field_name)) in blocked:
                    excluded = True
                    break
            if not excluded:
                rows.append(dict(row))
        return rows


def _make_item(
    *,
    scope: MemoryScope = MemoryScope.TENANT,
    key: str = "test_key",
    value: dict[str, Any] | None = None,
    confidence: float = 0.9,
    ttl: timedelta | None = None,
    scope_path: str | None = None,
) -> MemoryItem:
    return MemoryItem(
        scope=scope,
        key=key,
        value=value or {"data": "hello"},
        confidence=Confidence(confidence),
        ttl=ttl,
        scope_path=scope_path,
    )


@pytest.fixture
async def store() -> AsyncIterator[PostgresMemoryStore]:
    """Fresh PostgresMemoryStore using an asyncpg-shaped fake pool."""

    s = PostgresMemoryStore(dsn="postgresql://offline", schema=_TEST_SCHEMA, tenant_id="test_tenant")
    s._pool = _FakePool()  # type: ignore[attr-defined]
    await s._ensure_schema()
    try:
        yield s
    finally:
        await s.close()


async def test_set_get_roundtrip(store: PostgresMemoryStore) -> None:
    """All MemoryItem fields survive a write/read round-trip through the Postgres adapter."""
    item = _make_item(
        key="roundtrip",
        value={"nested": {"count": 42}, "tag": "alpha"},
        confidence=0.75,
        scope_path="brand/sub",
    )
    await store.set(item=item)
    retrieved = await store.get(scope=MemoryScope.TENANT, key="roundtrip")

    assert retrieved is not None
    assert retrieved.scope == MemoryScope.TENANT
    assert retrieved.key == "roundtrip"
    assert retrieved.value == {"nested": {"count": 42}, "tag": "alpha"}
    assert abs(float(retrieved.confidence) - 0.75) < 1e-5
    assert retrieved.scope_path == "brand/sub"
    assert retrieved.created_at.year == item.created_at.year


async def test_get_returns_none_for_expired(store: PostgresMemoryStore) -> None:
    """An item whose expires_at has passed is treated as absent."""
    item = _make_item(key="expiring", ttl=timedelta(milliseconds=10))
    await store.set(item=item)

    pool = await store._ensure_pool()
    past = utc_now() - timedelta(seconds=10)
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE {_TEST_SCHEMA}.memory_items "
            f"SET expires_at = $1 "
            f"WHERE tenant_id = $2 AND scope = $3 AND key = $4",
            past,
            "test_tenant",
            MemoryScope.TENANT.value,
            "expiring",
        )

    result = await store.get(scope=MemoryScope.TENANT, key="expiring")
    assert result is None


async def test_delete_returns_true_if_existed(store: PostgresMemoryStore) -> None:
    """delete() returns True for an existing key, False on a second call."""
    item = _make_item(key="deleteme")
    await store.set(item=item)

    first = await store.delete(scope=MemoryScope.TENANT, key="deleteme")
    second = await store.delete(scope=MemoryScope.TENANT, key="deleteme")

    assert first is True
    assert second is False


async def test_list_by_scope_excludes_expired(store: PostgresMemoryStore) -> None:
    """list_by_scope returns only live items; expired rows are filtered by the query."""
    items = [
        _make_item(key="live_1", value={"n": 1}),
        _make_item(key="live_2", value={"n": 2}),
        _make_item(key="expired", value={"n": 3}),
    ]
    for it in items:
        await store.set(item=it)

    pool = await store._ensure_pool()
    past = utc_now() - timedelta(seconds=5)
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE {_TEST_SCHEMA}.memory_items "
            f"SET expires_at = $1 "
            f"WHERE tenant_id = $2 AND scope = $3 AND key = $4",
            past,
            "test_tenant",
            MemoryScope.TENANT.value,
            "expired",
        )

    results = await store.list_by_scope(scope=MemoryScope.TENANT)
    keys = {r.key for r in results}
    assert "live_1" in keys
    assert "live_2" in keys
    assert "expired" not in keys


async def test_exclude_filter(store: PostgresMemoryStore) -> None:
    """exclude_filter prevents rows whose JSON field matches the excluded values."""
    await store.set(item=_make_item(key="class_a", value={"class": "A", "x": 1}))
    await store.set(item=_make_item(key="class_b", value={"class": "B", "x": 2}))
    await store.set(item=_make_item(key="class_c", value={"class": "C", "x": 3}))

    results = await store.list_by_scope(
        scope=MemoryScope.TENANT,
        exclude_filter={"class": ["B", "C"]},
    )
    keys = {r.key for r in results}
    assert "class_a" in keys
    assert "class_b" not in keys
    assert "class_c" not in keys


async def test_tenant_isolation() -> None:
    """Two stores with different tenant_ids cannot see each other's data."""
    pool = _FakePool()
    store_alpha = PostgresMemoryStore(dsn="postgresql://offline", schema=_TEST_SCHEMA, tenant_id="alpha")
    store_beta = PostgresMemoryStore(dsn="postgresql://offline", schema=_TEST_SCHEMA, tenant_id="beta")
    store_alpha._pool = pool  # type: ignore[attr-defined]
    store_beta._pool = pool  # type: ignore[attr-defined]

    try:
        await store_alpha._ensure_schema()
        await store_beta._ensure_schema()
        await store_alpha.set(item=_make_item(key="secret_alpha", value={"owner": "alpha"}))
        await store_beta.set(item=_make_item(key="secret_beta", value={"owner": "beta"}))

        alpha_sees = await store_alpha.get(scope=MemoryScope.TENANT, key="secret_beta")
        beta_sees = await store_beta.get(scope=MemoryScope.TENANT, key="secret_alpha")
        alpha_list = await store_alpha.list_by_scope(scope=MemoryScope.TENANT)
        beta_list = await store_beta.list_by_scope(scope=MemoryScope.TENANT)

        assert alpha_sees is None
        assert beta_sees is None
        assert all(r.value.get("owner") == "alpha" for r in alpha_list)
        assert all(r.value.get("owner") == "beta" for r in beta_list)
    finally:
        await store_alpha.close()
        await store_beta.close()
