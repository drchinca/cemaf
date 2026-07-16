"""DataSource protocol — read-only enterprise connector contract (SPEC-02 §2).

Not `@runtime_checkable`: DataSourceRegistry.register() enforces the read-only
boundary by inspecting `vars(type(source))` for exact public-surface match,
not just method presence. A presence-only `isinstance` check would give a
false sense that the boundary is being enforced at the wrong granularity —
see `datasources/registry.py` for the real check.
"""

from __future__ import annotations

from typing import ClassVar, Protocol, runtime_checkable

from cemaf.context.budget import TokenBudget
from cemaf.datasources.models import (
    CiteableChunk,
    DataSourceCapability,
    EntityRef,
    HealthStatus,
    RetrievalQuery,
)


class DataSource(Protocol):
    """Read-only enterprise connector. Protocol surface has NO write methods.

    Implementations MUST declare `source_id`/`capabilities` as class-body
    attributes (not dataclass fields without `ClassVar`, and not instance
    attributes set in `__init__`) — see the registry module docstring for why.
    """

    source_id: ClassVar[str]
    capabilities: ClassVar[frozenset[DataSourceCapability]]

    async def retrieve(self, *, query: RetrievalQuery, budget: TokenBudget) -> tuple[CiteableChunk, ...]: ...

    async def health(self) -> HealthStatus: ...


@runtime_checkable
class EntityExtractor(Protocol):
    """Pluggable entity extraction over free text.

    `@runtime_checkable` here (unlike DataSource) since there's no read-only
    boundary to enforce — a presence-only isinstance check is sufficient.
    """

    version: ClassVar[str]

    def extract(self, *, text: str) -> tuple[EntityRef, ...]: ...
