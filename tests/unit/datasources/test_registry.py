"""Unit tests for DataSourceRegistry — the read-only-boundary enforcement (SPEC-02 Inv 1)."""

from typing import ClassVar

import pytest

from cemaf.datasources.exceptions import DuplicateSourceError, ReadOnlyViolationError
from cemaf.datasources.models import DataSourceCapability, HealthStatus
from cemaf.datasources.registry import DataSourceRegistry, source_registry_from_data_sources


class _GoodSource:
    source_id: ClassVar[str] = "good"
    capabilities: ClassVar[frozenset[DataSourceCapability]] = frozenset({DataSourceCapability.SEARCH})

    async def retrieve(self, *, query: object, budget: object) -> tuple:
        return ()

    async def health(self) -> HealthStatus:
        return HealthStatus.HEALTHY


class _WriteCapableSource:
    """SPEC-02 Inv 1's literal acceptance scenario — an extra public method."""

    source_id: ClassVar[str] = "bad"
    capabilities: ClassVar[frozenset[DataSourceCapability]] = frozenset({DataSourceCapability.SEARCH})

    async def retrieve(self, *, query: object, budget: object) -> tuple:
        return ()

    async def health(self) -> HealthStatus:
        return HealthStatus.HEALTHY

    async def write(self, data: object) -> None:  # extra public surface — must be rejected
        pass


class _MissingHealthSource:
    source_id: ClassVar[str] = "incomplete"
    capabilities: ClassVar[frozenset[DataSourceCapability]] = frozenset({DataSourceCapability.SEARCH})

    async def retrieve(self, *, query: object, budget: object) -> tuple:
        return ()


class _BaseWithPublicHelper:
    """A shared base class with its own public method."""

    def helper(self) -> str:
        return "base helper"


class _CompliantSubclass(_BaseWithPublicHelper):
    """Inherits `helper` from its base — vars() doesn't walk the MRO, so this
    should register cleanly even though `helper` is public, per SPEC-02's
    'excluding inherited members' language."""

    source_id: ClassVar[str] = "compliant-subclass"
    capabilities: ClassVar[frozenset[DataSourceCapability]] = frozenset({DataSourceCapability.SEARCH})

    async def retrieve(self, *, query: object, budget: object) -> tuple:
        return ()

    async def health(self) -> HealthStatus:
        return HealthStatus.HEALTHY


class _InstanceAttributeLeakSource:
    """Known, documented gap: an unprefixed instance attribute assigned in
    __init__ is invisible to vars(type(source)) — this does NOT get rejected.
    This test documents the limitation rather than leaving it a silent surprise."""

    source_id: ClassVar[str] = "instance-leak"
    capabilities: ClassVar[frozenset[DataSourceCapability]] = frozenset({DataSourceCapability.SEARCH})

    def __init__(self) -> None:
        self.logger = "not caught by the class-scope check"

    async def retrieve(self, *, query: object, budget: object) -> tuple:
        return ()

    async def health(self) -> HealthStatus:
        return HealthStatus.HEALTHY


class TestDataSourceRegistryReadOnlyBoundary:
    def test_compliant_source_registers(self) -> None:
        registry = DataSourceRegistry()
        registry.register(_GoodSource())
        assert len(registry) == 1
        assert registry.source_ids() == frozenset({"good"})

    def test_extra_public_method_rejected(self) -> None:
        registry = DataSourceRegistry()
        with pytest.raises(ReadOnlyViolationError, match="write"):
            registry.register(_WriteCapableSource())

    def test_missing_required_member_rejected(self) -> None:
        registry = DataSourceRegistry()
        with pytest.raises(ReadOnlyViolationError, match="health"):
            registry.register(_MissingHealthSource())

    def test_duplicate_source_id_rejected(self) -> None:
        registry = DataSourceRegistry()
        registry.register(_GoodSource())
        with pytest.raises(DuplicateSourceError):
            registry.register(_GoodSource())

    def test_inherited_public_member_not_flagged(self) -> None:
        """vars() doesn't walk the MRO — a subclass inheriting a public method
        from a shared base is NOT rejected, matching SPEC-02's exemption."""
        registry = DataSourceRegistry()
        registry.register(_CompliantSubclass())
        assert len(registry) == 1

    def test_instance_attribute_leak_is_not_caught(self) -> None:
        """Documents the known, accepted gap: instance attributes assigned in
        __init__ are invisible to the class-scope vars() check."""
        registry = DataSourceRegistry()
        registry.register(_InstanceAttributeLeakSource())  # does NOT raise
        assert len(registry) == 1

    def test_get_unknown_source_id_raises_key_error(self) -> None:
        registry = DataSourceRegistry()
        with pytest.raises(KeyError):
            registry.get("nonexistent")

    def test_list_capable_filters_by_capability(self) -> None:
        registry = DataSourceRegistry()
        registry.register(_GoodSource())
        assert registry.list_capable(DataSourceCapability.SEARCH) == (registry.get("good"),)
        assert registry.list_capable(DataSourceCapability.RELATIONS) == ()


class TestTenantPriorityOffsets:
    def test_within_bound_accepted(self) -> None:
        registry = DataSourceRegistry(tenant_priority_offsets={"good": 10})
        assert registry.tenant_offset("good") == 10

    def test_unconfigured_source_defaults_to_zero(self) -> None:
        registry = DataSourceRegistry()
        assert registry.tenant_offset("unknown") == 0

    def test_out_of_bound_offset_rejected_at_construction(self) -> None:
        with pytest.raises(ReadOnlyViolationError, match="priority_offset_overflow"):
            DataSourceRegistry(tenant_priority_offsets={"good": 11})


class TestSourceRegistryFromDataSources:
    def test_includes_registered_and_fixed_source_ids(self) -> None:
        """PullInterceptor no longer emits memory-sourced chunks (that pull was
        removed as a fix for double-surfacing memory content), so 'memory' is
        NOT in the fixed allow-list — only 'kg' plus every registered source_id."""
        registry = DataSourceRegistry()
        registry.register(_GoodSource())
        source_registry = source_registry_from_data_sources(registry)
        assert source_registry.is_known("good")
        assert source_registry.is_known("kg")
        assert not source_registry.is_known("memory")
        assert not source_registry.is_known("fabricated")
