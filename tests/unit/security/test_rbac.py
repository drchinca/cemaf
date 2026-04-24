"""Unit tests for cemaf.security.rbac."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.core.types import Confidence
from cemaf.memory.base import InMemoryStore, MemoryItem
from cemaf.security.mappings import DictMappingProvider
from cemaf.security.rbac import (
    ROLE_READER,
    ROLE_SYSTEM,
    ROLE_WRITER,
    PermissionDeniedError,
    RBACEnforcer,
    RBACMemoryStore,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def make_item(
    key: str = "k1",
    scope: MemoryScope = MemoryScope.PROJECT,
    scope_path: str | None = None,
    value: dict | None = None,
) -> MemoryItem:
    return MemoryItem(
        scope=scope,
        key=key,
        value=value or {"data": "hello"},
        confidence=Confidence(1.0),
        scope_path=scope_path,
    )


def _make_provider(roles: list[str], direct_access: list[dict] | None = None) -> DictMappingProvider:
    data: dict[str, Any] = {
        "users": {
            "principal": {
                "type": "user",
                "attributes": {},
                "roles": roles,
                "direct_access": direct_access or [],
            }
        },
        "teams": {},
    }
    return DictMappingProvider(data)


# ---------------------------------------------------------------------------
# RBACEnforcer — role-based
# ---------------------------------------------------------------------------


def test_reader_cannot_write() -> None:
    provider = _make_provider([ROLE_READER])
    enforcer = RBACEnforcer(provider)
    assert enforcer.can("principal", "write", MemoryScope.PROJECT) is False


def test_writer_can_read_and_write() -> None:
    provider = _make_provider([ROLE_WRITER])
    enforcer = RBACEnforcer(provider)
    assert enforcer.can("principal", "read", MemoryScope.PROJECT) is True
    assert enforcer.can("principal", "write", MemoryScope.PROJECT) is True


def test_writer_cannot_admin() -> None:
    provider = _make_provider([ROLE_WRITER])
    enforcer = RBACEnforcer(provider)
    assert enforcer.can("principal", "admin", MemoryScope.PROJECT) is False


def test_system_always_passes() -> None:
    provider = _make_provider([ROLE_SYSTEM])
    enforcer = RBACEnforcer(provider)
    for action in ("read", "write", "delete", "list", "admin", "bypass", "unknown_action"):
        assert enforcer.can("principal", action, MemoryScope.SESSION) is True


def test_unknown_principal_denied() -> None:
    provider = _make_provider([ROLE_READER])
    enforcer = RBACEnforcer(provider)
    # "ghost" is not in the provider
    assert enforcer.can("ghost", "read", MemoryScope.PROJECT) is False


# ---------------------------------------------------------------------------
# RBACEnforcer — direct_access grants
# ---------------------------------------------------------------------------


def test_direct_access_grant_allows_action() -> None:
    provider = _make_provider(
        roles=[],
        direct_access=[
            {"scope": "session", "actions": ["read"]}
        ],
    )
    enforcer = RBACEnforcer(provider)
    assert enforcer.can("principal", "read", MemoryScope.SESSION) is True
    assert enforcer.can("principal", "write", MemoryScope.SESSION) is False


def test_direct_access_scope_path_prefix_required() -> None:
    """Grant with scope_path_prefix only applies when scope_path starts with prefix."""
    provider = _make_provider(
        roles=[],
        direct_access=[
            {
                "scope": "project",
                "scope_path_prefix": "/intel/",
                "actions": ["read"],
            }
        ],
    )
    enforcer = RBACEnforcer(provider)
    # Matching prefix
    assert enforcer.can("principal", "read", MemoryScope.PROJECT, "/intel/ops") is True
    # Non-matching prefix
    assert enforcer.can("principal", "read", MemoryScope.PROJECT, "/finance/") is False
    # No scope_path provided
    assert enforcer.can("principal", "read", MemoryScope.PROJECT, None) is False


# ---------------------------------------------------------------------------
# RBACMemoryStore — permission enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rbac_store_reader_can_get() -> None:
    inner = InMemoryStore()
    item = make_item()
    await inner.set(item)

    provider = _make_provider([ROLE_READER])
    enforcer = RBACEnforcer(provider)
    store = RBACMemoryStore(inner=inner, enforcer=enforcer, principal_id="principal")

    result = await store.get(MemoryScope.PROJECT, "k1")
    assert result is not None
    assert result.key == "k1"


@pytest.mark.asyncio
async def test_rbac_store_reader_cannot_write_raises() -> None:
    inner = InMemoryStore()
    provider = _make_provider([ROLE_READER])
    enforcer = RBACEnforcer(provider)
    store = RBACMemoryStore(inner=inner, enforcer=enforcer, principal_id="principal")

    with pytest.raises(PermissionDeniedError):
        await store.set(make_item())


@pytest.mark.asyncio
async def test_scope_path_prefix_filters_list() -> None:
    """Items outside the principal's scope_path_prefix are excluded from list results."""
    inner = InMemoryStore()

    # Two items: one within /intel/, one outside
    await inner.set(make_item(key="intel_item", scope_path="/intel/ops/plan"))
    await inner.set(make_item(key="finance_item", scope_path="/finance/q4"))

    provider = _make_provider(
        roles=[],
        direct_access=[
            {"scope": "project", "scope_path_prefix": "/intel/", "actions": ["read", "list"]}
        ],
    )
    enforcer = RBACEnforcer(provider)
    store = RBACMemoryStore(inner=inner, enforcer=enforcer, principal_id="principal")

    results = await store.list_by_scope(MemoryScope.PROJECT)
    keys = {r.key for r in results}
    assert "intel_item" in keys
    assert "finance_item" not in keys


@pytest.mark.asyncio
async def test_denied_access_appends_audit_entry() -> None:
    """When access is denied, an ACCESS_DENIED entry is appended to audit_log."""
    inner = InMemoryStore()
    provider = _make_provider([ROLE_READER])  # cannot write
    enforcer = RBACEnforcer(provider)

    # Use a real EventBusAuditLog so we can inspect appended entries
    from cemaf.audit.subscriber import EventBusAuditLog  # noqa: PLC0415

    audit_log = EventBusAuditLog()
    store = RBACMemoryStore(
        inner=inner,
        enforcer=enforcer,
        principal_id="principal",
        audit_log=audit_log,
    )

    with pytest.raises(PermissionDeniedError):
        await store.set(make_item())

    # Give background thread a moment to append
    await asyncio.sleep(0.05)

    from cemaf.audit.models import AuditEntryType  # noqa: PLC0415

    entries = await audit_log.query(entry_type=AuditEntryType.ACCESS_DENIED)
    assert len(entries) >= 1
    assert entries[0].source == "principal"
    assert entries[0].payload["action"] == "write"


@pytest.mark.asyncio
async def test_cleanup_expired_delegates_without_rbac() -> None:
    """cleanup_expired() bypasses RBAC — no exception even for READER."""
    inner = InMemoryStore()
    provider = _make_provider([ROLE_READER])
    enforcer = RBACEnforcer(provider)
    store = RBACMemoryStore(inner=inner, enforcer=enforcer, principal_id="principal")

    # Should not raise
    count = await store.cleanup_expired()
    assert count == 0


@pytest.mark.asyncio
async def test_rbac_store_propagates_redaction_hook() -> None:
    """Redaction hook set on inner store is applied by RBACMemoryStore.get()."""
    inner = InMemoryStore()
    item = make_item(value={"secret": "topsecret", "public": "open"})
    await inner.set(item)

    from cemaf.security.masking import MaskingPipeline, MaskingRule, MaskingStrategy, create_masking_hook  # noqa: PLC0415

    rule = MaskingRule(field="secret", strategy=MaskingStrategy.MASK)
    pipeline = MaskingPipeline(rules=[rule])
    hook = create_masking_hook(pipeline)
    inner.set_redaction_hook(hook)

    provider = _make_provider([ROLE_READER])
    enforcer = RBACEnforcer(provider)
    store = RBACMemoryStore(inner=inner, enforcer=enforcer, principal_id="principal")

    result = await store.get(MemoryScope.PROJECT, "k1")
    assert result is not None
    assert result.value["secret"] == "*****"
    assert result.value["public"] == "open"
