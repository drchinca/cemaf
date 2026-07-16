"""DataSources module — read-only enterprise connector protocol (SPEC-02).

Provides:
- DataSourceCapability, HealthStatus: closed enums over connector capability/liveness
- EntityRef, RetrievalQuery, CiteableChunk: the retrieval request/result shapes
- DataSource: the read-only connector Protocol
- DataSourceRegistry: registry enforcing the read-only boundary at register()
- EntityExtractor, DefaultEntityExtractor: pluggable entity extraction over free text
"""

from cemaf.datasources.entity_extractor import DefaultEntityExtractor
from cemaf.datasources.exceptions import DuplicateSourceError, ReadOnlyViolationError
from cemaf.datasources.models import (
    CiteableChunk,
    DataSourceCapability,
    EntityRef,
    HealthStatus,
    RetrievalQuery,
)
from cemaf.datasources.protocols import DataSource, EntityExtractor
from cemaf.datasources.registry import DataSourceRegistry, source_registry_from_data_sources

__all__ = [
    # Models
    "DataSourceCapability",
    "HealthStatus",
    "EntityRef",
    "RetrievalQuery",
    "CiteableChunk",
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
