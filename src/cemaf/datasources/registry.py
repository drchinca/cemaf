"""DataSourceRegistry — read-only-boundary-enforcing connector registry (SPEC-02 §2 Inv 1).

Deliberately NOT built on `core/provider_registry.py`'s `ProviderRegistry[T]`.
`ProviderRegistry[T]` maps a backend name to a factory and instantiates on
demand; `register()` here accepts an ALREADY-CONSTRUCTED instance and must
reject it by introspecting the concrete class's public surface — a shape
`ProviderRegistry` has no hook for. Do not "simplify" this into a
`ProviderRegistry[T]` — that would silently drop the read-only enforcement
this class exists for.

## `vars(type(source))` mechanics

`vars(type(source))` is `ConcreteClass.__dict__` — it contains only names
declared directly at class-body scope. It does NOT walk the MRO (so a shared
base class's public members, inherited by a compliant subclass, are never
flagged — this matches SPEC-02's "excluding inherited members" language), and
it does NOT include instance attributes assigned in `__init__` (an unprefixed
`self.logger = ...` is invisible to this check). The second point is a known,
accepted gap: SPEC-02's Inv 1 acceptance scenario is about an extra *public
method* (e.g. `def write(...)`), and bound methods always resolve through the
class `__dict__` — so the literal acceptance criteria is still met.

Implementers should declare `source_id`/`capabilities` as plain class-body
assignments (not dataclass fields without `ClassVar`, which land on the
*instance*, invisible to this check) and keep any internal config on
underscore-prefixed instance attributes — the same shape `GateEvalInterceptor`
already uses (`self._id`, `self._evaluators`).

## Fail-fast boundary

No `StartupError` type exists anywhere in this codebase (SPEC-00's
"Startup-error owner" concept is unimplemented). `register()`'s synchronous
raise IS the fail-fast boundary — callers let it propagate uncaught during
their own composition-root code, which is functionally equivalent.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from cemaf.citation.registry import StaticSourceRegistry
from cemaf.datasources.exceptions import DuplicateSourceError, ReadOnlyViolationError
from cemaf.datasources.models import TENANT_OFFSET_BOUND, DataSourceCapability, SourceKind
from cemaf.datasources.protocols import DataSource

_REQUIRED_MEMBERS = ("source_id", "capabilities", "retrieve", "health")


class DataSourceRegistry:
    """Static read-only-port enforcement happens at register() — see module docstring."""

    ALLOWED_PUBLIC: ClassVar[frozenset[str]] = frozenset({"retrieve", "health", "source_id", "capabilities"})

    def __init__(self, *, tenant_priority_offsets: Mapping[str, int] | None = None) -> None:
        self._sources: dict[str, DataSource] = {}
        offsets = tenant_priority_offsets or {}
        for source_id, offset in offsets.items():
            if not (-TENANT_OFFSET_BOUND <= offset <= TENANT_OFFSET_BOUND):
                raise ReadOnlyViolationError(
                    f"priority_offset_overflow: {source_id!r} offset {offset} exceeds ±{TENANT_OFFSET_BOUND}"
                )
        self._tenant_priority_offsets = dict(offsets)

    def register(self, source: DataSource) -> None:
        """Reject sources whose concrete class declares any public attribute
        (`vars(type(source))`, name not starting with `_`) outside
        `ALLOWED_PUBLIC` — inherited members from base classes are NOT counted.

        Raises:
            ReadOnlyViolationError: extra public surface, or a required member missing.
            DuplicateSourceError: source.source_id already registered.
        """
        concrete = type(source)
        public_set = {name for name in vars(concrete) if not name.startswith("_")}
        extra = public_set - self.ALLOWED_PUBLIC
        if extra:
            raise ReadOnlyViolationError(
                f"{concrete.__name__} exposes disallowed public members: {sorted(extra)}"
            )
        for required in _REQUIRED_MEMBERS:
            if not hasattr(source, required):
                raise ReadOnlyViolationError(f"{concrete.__name__} missing required member {required!r}")

        source_id = source.source_id
        if source_id in self._sources:
            raise DuplicateSourceError(f"source_id already registered: {source_id!r}")
        self._sources[source_id] = source

    def get(self, source_id: str) -> DataSource:
        try:
            return self._sources[source_id]
        except KeyError:
            raise KeyError(f"unknown source_id: {source_id!r}") from None

    def list_capable(self, capability: DataSourceCapability) -> tuple[DataSource, ...]:
        return tuple(source for source in self._sources.values() if capability in source.capabilities)

    def source_ids(self) -> frozenset[str]:
        return frozenset(self._sources)

    def tenant_offset(self, source_id: str) -> int:
        """Configured tenant priority offset for source_id, or 0 if unconfigured."""
        return self._tenant_priority_offsets.get(source_id, 0)

    def __len__(self) -> int:
        return len(self._sources)


def source_registry_from_data_sources(registry: DataSourceRegistry) -> StaticSourceRegistry:
    """Build a StaticSourceRegistry over every registered DataSource's source_id,
    plus PullInterceptor's fixed KG source_id. Composition-root code combines
    this with any other known source_ids before building a citation
    membership check, or unions it into an agent's own known-sources set."""
    return StaticSourceRegistry.from_iterable(registry.source_ids() | {SourceKind.KG.value})
