"""DataSources module — read-only enterprise connector protocol (SPEC-02).

Provides:
- DataSourceCapability, HealthStatus, SourceKind: closed enums over connector
  capability/liveness/chunk-origin
- EntityRef, RetrievalQuery, CiteableChunk: the retrieval request/result shapes
- DataSource: the read-only connector Protocol
- DataSourceRegistry: registry enforcing the read-only boundary at register()
- EntityExtractor, DefaultEntityExtractor: pluggable entity extraction over free text
"""

from cemaf.datasources.entity_extractor import DefaultEntityExtractor
from cemaf.datasources.exceptions import DuplicateSourceError, ReadOnlyViolationError
from cemaf.datasources.models import (
    TENANT_OFFSET_BOUND,
    CiteableChunk,
    DataSourceCapability,
    EntityRef,
    HealthStatus,
    RetrievalQuery,
    SourceKind,
)
from cemaf.datasources.protocols import DataSource, EntityExtractor
from cemaf.datasources.registry import DataSourceRegistry, source_registry_from_data_sources

__all__ = [
    # Models
    "DataSourceCapability",
    "HealthStatus",
    "SourceKind",
    "EntityRef",
    "RetrievalQuery",
    "CiteableChunk",
    "TENANT_OFFSET_BOUND",
    # Protocols
    "DataSource",
    "EntityExtractor",
    # Registry
    "DataSourceRegistry",
    "DuplicateSourceError",
    "ReadOnlyViolationError",
    "source_registry_from_data_sources",
    # Entity extraction
    "DefaultEntityExtractor",
]
