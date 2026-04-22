"""Regression tests — get_logger() must NOT mutate the global.

Before the fix, each get_logger(...) rebound the module global `_logger` to
a context-accumulated copy. Tenant A's context leaked into tenant B's log
records, and the root logger grew unboundedly. This suite proves the global
stays pristine after scoped lookups.
"""

from __future__ import annotations

import pytest

from cemaf.observability import config as obs_config
from cemaf.observability.config import (
    configure_logging,
    get_logger,
    reset_observability,
)


@pytest.fixture(autouse=True)
def reset_after_each_test() -> None:
    reset_observability()
    yield
    reset_observability()


def test_scoped_logger_does_not_mutate_global() -> None:
    configure_logging()
    root_before = obs_config._logger

    # Hit it many times with distinct tenants
    for tenant in ("tenant-a", "tenant-b", "tenant-c"):
        get_logger("routes.api", tenant_id=tenant, run_id="r1")

    root_after = obs_config._logger
    assert root_before is root_after, "get_logger() must not rebind the global"


def test_tenant_context_does_not_bleed_across_lookups() -> None:
    configure_logging()

    tenant_a = get_logger("api", tenant_id="A")
    tenant_b = get_logger("api", tenant_id="B")

    # Different scoped instances
    assert tenant_a is not tenant_b

    # Neither the global nor a fresh lookup carries the earlier tenant's context
    fresh = get_logger()
    # The root logger's context should not contain either tenant id
    fresh_ctx = getattr(fresh, "_context", None) or getattr(fresh, "context", None) or {}
    assert "tenant_id" not in fresh_ctx


def test_repeated_calls_do_not_unbounded_grow_global() -> None:
    """Performance regression: old impl stacked context N deep after N calls."""
    configure_logging()
    root_before = obs_config._logger

    for i in range(100):
        get_logger(f"comp_{i}", call_id=str(i))

    root_after = obs_config._logger
    assert root_before is root_after


def test_returns_configured_logger_when_no_args() -> None:
    configure_logging()
    a = get_logger()
    b = get_logger()
    # No args = return the configured root (not a new scope)
    assert a is b
    assert a is obs_config._logger


def test_name_only_lookup_returns_scoped_without_mutating_global() -> None:
    configure_logging()
    root_before = obs_config._logger
    scoped = get_logger("memory.sqlite")
    # Scoped is NOT the root
    assert scoped is not root_before
    # Global is still the original root
    assert obs_config._logger is root_before
