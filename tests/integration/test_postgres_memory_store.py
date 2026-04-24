"""Integration tests for PostgresMemoryStore.

Requires a live PostgreSQL instance. All tests are skipped when:
- asyncpg is not installed, OR
- CEMAF_POSTGRES_DSN environment variable is not set.

Run with:
    CEMAF_POSTGRES_DSN=postgresql://user:pass@localhost/cemaf_test pytest \
        tests/integration/test_postgres_memory_store.py -v
"""

import asyncio
import os

import pytest

asyncpg = pytest.importorskip("asyncpg", reason="asyncpg not installed")

_DSN = os.getenv("CEMAF_POSTGRES_DSN", "")
pytestmark = pytest.mark.skipif(
    not _DSN,
    reason="CEMAF_POSTGRES_DSN not set — skipping Postgres integration tests",
)

import json
from datetime import timedelta

from cemaf.core.enums import MemoryScope
from cemaf.core.types import Confidence
from cemaf.core.utils import utc_now
from cemaf.memory.base import MemoryItem
from cemaf.memory.postgres_store import PostgresMemoryStore

_TEST_SCHEMA = "cemaf_test"


def _make_item(
    *,
    scope: MemoryScope = MemoryScope.BRAND,
    key: str = "test_key",
    value: dict | None = None,
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
async def store() -> "AsyncIterator[PostgresMemoryStore]":
    """Fresh PostgresMemoryStore using a test schema, cleaned up after each test."""
    from collections.abc import AsyncIterator

    s = PostgresMemoryStore(dsn=_DSN, schema=_TEST_SCHEMA, tenant_id="test_tenant")
    pool = await s._ensure_pool()
    # Wipe schema between tests for isolation
    async with pool.acquire() as conn:
        await conn.execute(f"DROP SCHEMA IF EXISTS {_TEST_SCHEMA} CASCADE")
    await s._ensure_schema()
    try:
        yield s
    finally:
        async with pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {_TEST_SCHEMA} CASCADE")
        await s.close()


async def test_set_get_roundtrip(store: PostgresMemoryStore) -> None:
    """All MemoryItem fields survive a write/read round-trip through Postgres."""
    item = _make_item(
        key="roundtrip",
        value={"nested": {"count": 42}, "tag": "alpha"},
        confidence=0.75,
        scope_path="brand/sub",
    )
    await store.set(item=item)
    retrieved = await store.get(scope=MemoryScope.BRAND, key="roundtrip")

    assert retrieved is not None
    assert retrieved.scope == MemoryScope.BRAND
    assert retrieved.key == "roundtrip"
    assert retrieved.value == {"nested": {"count": 42}, "tag": "alpha"}
    assert abs(float(retrieved.confidence) - 0.75) < 1e-5
    assert retrieved.scope_path == "brand/sub"
    # Timestamps are timezone-aware coming back from asyncpg; compare up to the second
    assert retrieved.created_at.year == item.created_at.year


async def test_get_returns_none_for_expired(store: PostgresMemoryStore) -> None:
    """An item whose expires_at has passed is treated as absent."""
    item = _make_item(key="expiring", ttl=timedelta(milliseconds=10))
    await store.set(item=item)

    # Force expires_at to the past by directly writing an already-expired timestamp
    pool = await store._ensure_pool()
    past = utc_now() - timedelta(seconds=10)
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE {_TEST_SCHEMA}.memory_items "
            f"SET expires_at = $1 "
            f"WHERE tenant_id = $2 AND scope = $3 AND key = $4",
            past,
            "test_tenant",
            MemoryScope.BRAND.value,
            "expiring",
        )

    result = await store.get(scope=MemoryScope.BRAND, key="expiring")
    assert result is None


async def test_delete_returns_true_if_existed(store: PostgresMemoryStore) -> None:
    """delete() returns True for an existing key, False on a second call."""
    item = _make_item(key="deleteme")
    await store.set(item=item)

    first = await store.delete(scope=MemoryScope.BRAND, key="deleteme")
    second = await store.delete(scope=MemoryScope.BRAND, key="deleteme")

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

    # Manually expire the third item
    pool = await store._ensure_pool()
    past = utc_now() - timedelta(seconds=5)
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE {_TEST_SCHEMA}.memory_items "
            f"SET expires_at = $1 "
            f"WHERE tenant_id = $2 AND scope = $3 AND key = $4",
            past,
            "test_tenant",
            MemoryScope.BRAND.value,
            "expired",
        )

    results = await store.list_by_scope(scope=MemoryScope.BRAND)
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
        scope=MemoryScope.BRAND,
        exclude_filter={"class": ["B", "C"]},
    )
    keys = {r.key for r in results}
    assert "class_a" in keys
    assert "class_b" not in keys
    assert "class_c" not in keys


async def test_tenant_isolation(store: PostgresMemoryStore) -> None:
    """Two stores with different tenant_ids cannot see each other's data."""
    store_alpha = PostgresMemoryStore(dsn=_DSN, schema=_TEST_SCHEMA, tenant_id="alpha")
    store_beta = PostgresMemoryStore(dsn=_DSN, schema=_TEST_SCHEMA, tenant_id="beta")

    try:
        await store_alpha.set(item=_make_item(key="secret_alpha", value={"owner": "alpha"}))
        await store_beta.set(item=_make_item(key="secret_beta", value={"owner": "beta"}))

        alpha_sees = await store_alpha.get(scope=MemoryScope.BRAND, key="secret_beta")
        beta_sees = await store_beta.get(scope=MemoryScope.BRAND, key="secret_alpha")
        alpha_list = await store_alpha.list_by_scope(scope=MemoryScope.BRAND)
        beta_list = await store_beta.list_by_scope(scope=MemoryScope.BRAND)

        assert alpha_sees is None
        assert beta_sees is None
        assert all(r.value.get("owner") == "alpha" for r in alpha_list)
        assert all(r.value.get("owner") == "beta" for r in beta_list)
    finally:
        await store_alpha.close()
        await store_beta.close()
