"""Unit tests for PostgresMemoryStore internals — no database required."""

import json
from datetime import UTC, datetime, timedelta

from cemaf.core.enums import MemoryScope
from cemaf.memory.postgres_store import _row_to_item


def _make_row(
    *,
    scope: str = "tenant",
    key: str = "k",
    value: dict | None = None,
    confidence: float = 0.8,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    ttl_seconds: float | None = None,
    expires_at: datetime | None = None,
    scope_path: str | None = None,
) -> dict:
    """Build a dict that mimics an asyncpg Record with subscript access."""
    now = datetime.now(UTC)
    return {
        "scope": scope,
        "key": key,
        "value_json": json.dumps(value or {"x": 1}),
        "confidence": confidence,
        "created_at": created_at or now,
        "updated_at": updated_at or now,
        "ttl_seconds": ttl_seconds,
        "expires_at": expires_at,
        "scope_path": scope_path,
    }


async def test_row_to_item_roundtrip_no_expiry() -> None:
    """_row_to_item handles None expires_at and None scope_path without error."""
    row = _make_row(
        key="no_expiry",
        value={"hello": "world"},
        confidence=0.95,
        ttl_seconds=None,
        expires_at=None,
        scope_path=None,
    )
    item = _row_to_item(row)

    assert item.scope == MemoryScope.TENANT
    assert item.key == "no_expiry"
    assert item.value == {"hello": "world"}
    assert abs(float(item.confidence) - 0.95) < 1e-5
    assert item.ttl is None
    assert item.expires_at is None
    assert item.scope_path is None


async def test_row_to_item_with_expiry() -> None:
    """_row_to_item correctly reconstructs TTL and expires_at from a live row."""
    now = datetime.now(UTC)
    expires = now + timedelta(hours=1)
    row = _make_row(
        key="with_expiry",
        ttl_seconds=3600.0,
        expires_at=expires,
        scope_path="project/sub",
    )
    item = _row_to_item(row)

    assert item.ttl is not None
    assert abs(item.ttl.total_seconds() - 3600.0) < 1.0
    assert item.expires_at is not None
    assert item.scope_path == "project/sub"


async def test_row_to_item_string_timestamps() -> None:
    """_row_to_item handles isoformat string timestamps (test/migration scenarios)."""
    now_str = datetime.now(UTC).isoformat()
    expires_str = (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
    row = _make_row(
        key="str_ts",
        ttl_seconds=1800.0,
        expires_at=None,
        scope_path=None,
    )
    # Override with string timestamps
    row["created_at"] = now_str
    row["updated_at"] = now_str
    row["expires_at"] = expires_str
    item = _row_to_item(row)

    assert item.expires_at is not None
    assert item.key == "str_ts"


async def test_row_to_item_nested_value() -> None:
    """_row_to_item deserializes complex nested JSON correctly."""
    nested = {"a": [1, 2, 3], "b": {"c": True, "d": None}}
    row = _make_row(key="nested", value=nested)
    item = _row_to_item(row)

    assert item.value == nested
